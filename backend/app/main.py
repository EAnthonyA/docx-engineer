import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .auth import clear_session, create_session, verify_password, verify_session
from .jobs import JOBS_DIR, Job, cleanup_old_jobs, create_job, get_job
from . import docx_inspect, gemini, sandbox

log = logging.getLogger("main")

MAX_ATTEMPTS = 5
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_INSTRUCTION_LEN = 2000

_thread_pool = ThreadPoolExecutor(max_workers=4)


@asynccontextmanager
async def lifespan(app: FastAPI):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(lifespan=lifespan)

_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    password: str


@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response):
    if not verify_password(req.password):
        raise HTTPException(401, "Invalid password")
    create_session(response)
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response):
    clear_session(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(_: bool = Depends(verify_session)):
    return {"user": "admin"}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def _job_resp(job: Job) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "instruction": job.instruction,
        "diff": job.diff,
        "last_error": job.last_error,
    }


@app.post("/api/jobs")
async def create_new_job(
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_session),
    file: UploadFile = File(...),
    instruction: str = Form(...),
):
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, "Only .docx files accepted")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large (max 50 MB)")

    instruction = instruction.strip()
    if not instruction:
        raise HTTPException(400, "Instruction is required")
    if len(instruction) > MAX_INSTRUCTION_LEN:
        raise HTTPException(400, f"Instruction too long (max {MAX_INSTRUCTION_LEN} characters)")

    job = create_job(instruction)
    Path(job.input_path).write_bytes(content)

    background_tasks.add_task(_run_agent_loop, job.id)
    return _job_resp(job)


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str, _: bool = Depends(verify_session)):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_resp(job)


@app.get("/api/jobs/{job_id}/download")
def download_result(job_id: str, _: bool = Depends(verify_session)):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "needs_review":
        raise HTTPException(400, "Result not ready for download")
    if not job.output_path or not Path(job.output_path).exists():
        raise HTTPException(404, "Output file missing")
    return FileResponse(
        job.output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="result.docx",
    )


class RefineRequest(BaseModel):
    note: str


@app.post("/api/jobs/{job_id}/refine")
async def refine_job(
    job_id: str,
    req: RefineRequest,
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_session),
):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in ("needs_review", "stuck"):
        raise HTTPException(400, "Job cannot be refined in its current state")

    note = req.note.strip()
    if not note:
        raise HTTPException(400, "Refinement note is required")

    if job.last_script:
        job.history.append((job.last_script, f"User feedback: {note}"))

    job.status = "running"
    job.output_path = None
    job.diff = None
    job.last_error = None

    background_tasks.add_task(_run_agent_loop, job.id)
    return _job_resp(job)


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Agent loop (runs in thread pool — blocking I/O is intentional here)
# ---------------------------------------------------------------------------

def _run_agent_loop(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    job_dir = JOBS_DIR / job_id

    for _attempt in range(MAX_ATTEMPTS):
        try:
            doc_summary = docx_inspect.summarize(job.input_path)
        except Exception as e:
            job.status = "stuck"
            job.last_error = f"Could not read your document: {e}"
            return

        try:
            script = gemini.generate_script(job.instruction, doc_summary, job.history)
        except Exception as e:
            job.status = "stuck"
            job.last_error = f"AI service error: {e}"
            return

        job.last_script = script
        (job_dir / "script.py").write_text(script, encoding="utf-8")

        # Clear previous output
        out_dir = job_dir / "out"
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(exist_ok=True)

        result = sandbox.run_script(job_id)

        if not result["success"]:
            job.history.append((script, f"Script crashed: {result.get('error', 'unknown')}"))
            continue

        output_path = str(out_dir / "out.docx")
        if not Path(output_path).exists():
            job.history.append((script, "Script completed but produced no output file"))
            continue

        try:
            diff = docx_inspect.compute_diff(job.input_path, output_path)
        except Exception as e:
            job.history.append((script, f"Output file unreadable: {e}"))
            continue

        if diff["changed"] == 0:
            job.history.append((script, "Script ran but made no changes to the document"))
            continue

        job.output_path = output_path
        job.diff = diff
        job.status = "needs_review"
        return

    job.status = "stuck"
    if job.history:
        job.last_error = job.history[-1][1]
