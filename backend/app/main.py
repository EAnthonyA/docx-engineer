import logging
import os

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
import shutil
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel

from .auth import clear_session, create_session, verify_password, verify_session
from .jobs import (
    JOBS_DIR,
    Job,
    add_conversation_message,
    archive_finished_job_documents,
    create_job,
    discard_job_documents,
    get_job,
    list_jobs,
    recover_interrupted_jobs,
    save_job,
    set_job_stage,
)
from . import docx_inspect, llm, sandbox

log = logging.getLogger("main")

MAX_ATTEMPTS = 5
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_INSTRUCTION_LEN = 2000

# Single-user app: only one job may run at a time. Each job spawns a
# memory-hungry sandbox container, so allowing concurrency risks OOM.
_job_slot = threading.Semaphore(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    interrupted = recover_interrupted_jobs()
    if interrupted:
        log.warning("Marked %d interrupted job(s) as stuck", len(interrupted))
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
        "question": job.question,
        "diff": job.diff,
        "last_error": job.last_error,
        "attempt": job.attempt,
        "attempt_error": job.attempt_error,
        "max_attempts": MAX_ATTEMPTS,
        "stage": job.stage,
        "stage_detail": job.stage_detail,
        "stage_started_at": job.stage_started_at,
        "activity": job.activity,
        "conversation": job.conversation,
    }


def _job_summary(job: Job) -> dict:
    return {
        "id": job.id,
        "instruction": job.instruction,
        "status": job.status,
        "stage_detail": job.stage_detail,
        "created_at": job.created_at,
        "has_result": bool(job.output_path and Path(job.output_path).exists()),
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

    # Histories intentionally retain messages, not Word documents.  Starting
    # another task retires files from completed or failed tasks.
    archive_finished_job_documents()
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


@app.get("/api/jobs")
def get_job_history(_: bool = Depends(verify_session)):
    return [_job_summary(job) for job in list_jobs()]


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
        # The browser has the file at this point; keep only the chat record.
        background=BackgroundTask(discard_job_documents, job),
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
    add_conversation_message(job, "user", note)

    job.status = "running"
    job.output_path = None
    job.diff = None
    job.last_error = None
    job.attempt = 0
    job.attempt_error = None
    set_job_stage(job, "queued", "Ruošiamasi pradėti naują bandymą")
    save_job(job)

    background_tasks.add_task(_run_agent_loop, job.id, False)
    return _job_resp(job)


class AnswerRequest(BaseModel):
    answer: str


@app.post("/api/jobs/{job_id}/answer")
async def answer_job(
    job_id: str,
    req: AnswerRequest,
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_session),
):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "needs_clarification":
        raise HTTPException(400, "Job is not waiting for an answer")

    answer = req.answer.strip()
    if not answer:
        raise HTTPException(400, "Answer is required")

    if job.question:
        job.clarifications.append((job.question, answer))
    add_conversation_message(job, "user", answer)
    job.question = None
    job.status = "running"
    job.attempt = 0
    job.attempt_error = None
    set_job_stage(job, "queued", "Ruošiamasi tęsti darbą pagal Jūsų atsakymą")
    save_job(job)

    background_tasks.add_task(_run_agent_loop, job.id)
    return _job_resp(job)


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Agent loop (runs in thread pool — blocking I/O is intentional here)
# ---------------------------------------------------------------------------

def _run_agent_loop(job_id: str, clarify: bool = True) -> None:
    job = get_job(job_id)
    if not job:
        return

    # Serialize jobs: wait for any in-flight job to finish before starting.
    with _job_slot:
        try:
            set_job_stage(job, "reading_document", "Skaitoma dokumento struktūra")
            save_job(job)
            log.info("Job %s stage=reading_document", job_id)
            _run_job(job_id, job, clarify)
        except Exception:
            log.exception("Job %s agent loop crashed", job_id)
            job.status = "stuck"
            job.last_error = "Darbas netikėtai sustojo. Pabandykite dar kartą su nauju dokumentu."
            set_job_stage(job, "failed", "Darbas netikėtai sustojo")
            add_conversation_message(job, "assistant", "Darbas netikėtai sustojo. Atsiprašome, bandykite dar kartą su nauju dokumentu.")
            save_job(job)


def _run_job(job_id: str, job, clarify: bool) -> None:
    try:
        doc_summary = docx_inspect.summarize(job.input_path)
    except Exception as e:
        job.status = "stuck"
        log.exception("Job %s document inspection failed", job_id)
        job.last_error = "Dokumento perskaityti nepavyko. Patikrinkite, ar pasirinktas Word dokumentas, ir bandykite dar kartą."
        set_job_stage(job, "failed", "Dokumento perskaityti nepavyko")
        add_conversation_message(job, "assistant", job.last_error)
        save_job(job)
        return

    if clarify:
        set_job_stage(job, "checking_instruction", "Tikslinamas prašymas")
        save_job(job)
        log.info("Job %s stage=checking_instruction", job_id)
        try:
            question = llm.ask_clarification(job.instruction, doc_summary, job.clarifications)
        except Exception as e:
            job.status = "stuck"
            log.exception("Job %s clarification request failed", job_id)
            job.last_error = "Šiuo metu nepavyko patikslinti prašymo. Pabandykite dar kartą po kelių minučių."
            set_job_stage(job, "failed", "Prašymo patikslinti nepavyko")
            add_conversation_message(job, "assistant", job.last_error)
            save_job(job)
            return

        if question:
            job.question = question
            job.status = "needs_clarification"
            set_job_stage(job, "waiting_for_answer", "Laukiama Jūsų atsakymo")
            add_conversation_message(job, "assistant", question)
            save_job(job)
            log.info("Job %s waiting for clarification: %s", job_id, question)
            return

    _agent_loop_inner(job_id, job, JOBS_DIR / job_id, doc_summary)


def _agent_loop_inner(job_id: str, job, job_dir: Path, doc_summary: str) -> None:
    job.attempt_error = None
    for _attempt in range(MAX_ATTEMPTS):
        job.attempt = _attempt + 1
        set_job_stage(
            job,
            "generating_script",
            f"Ruošiamas dokumento pakeitimas ({job.attempt} bandymas iš {MAX_ATTEMPTS})",
        )
        save_job(job)
        log.info("Job %s stage=generating_script attempt=%d/%d", job_id, job.attempt, MAX_ATTEMPTS)

        try:
            script = llm.generate_script(job.instruction, doc_summary, job.history, job.clarifications)
        except Exception as e:
            job.status = "stuck"
            log.exception("Job %s script generation failed", job_id)
            job.last_error = "Šiuo metu nepavyko paruošti dokumento pakeitimo. Pabandykite dar kartą po kelių minučių."
            set_job_stage(job, "failed", "Pakeitimo paruošti nepavyko")
            add_conversation_message(job, "assistant", job.last_error)
            save_job(job)
            return

        job.last_script = script
        save_job(job)
        (job_dir / "script.py").write_text(script, encoding="utf-8")

        # Clear previous output
        out_dir = job_dir / "out"
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(exist_ok=True)

        set_job_stage(job, "running_sandbox", "Saugiai atliekami pakeitimai dokumente")
        save_job(job)
        log.info("Job %s stage=running_sandbox attempt=%d/%d", job_id, job.attempt, MAX_ATTEMPTS)
        result = sandbox.run_script(job_id)
        log.info("Job %s sandbox result attempt=%d success=%s error=%r",
                  job_id, _attempt + 1, result.get("success"), result.get("error"))

        if not result["success"]:
            msg = f"Script crashed: {result.get('error', 'unknown')}"
            job.history.append((script, msg))
            job.attempt_error = msg
            set_job_stage(job, "retrying", f"{job.attempt} bandymas nepavyko; ruošiamas kitas būdas")
            add_conversation_message(job, "assistant", f"{job.attempt} bandymas nepavyko. Ieškojome kito būdo atlikti pakeitimą.")
            save_job(job)
            continue

        output_path = str(out_dir / "out.docx")
        file_exists = Path(output_path).exists()
        log.debug("Job %s attempt %d output file exists: %s", job_id, _attempt + 1, file_exists)
        if not file_exists:
            msg = "Script completed but produced no output file"
            job.history.append((script, msg))
            job.attempt_error = msg
            set_job_stage(job, "retrying", f"{job.attempt} bandymas nesukūrė dokumento; ruošiamas kitas būdas")
            add_conversation_message(job, "assistant", f"{job.attempt} bandymas neparuošė dokumento. Ieškojome kito sprendimo.")
            save_job(job)
            continue

        set_job_stage(job, "checking_result", "Tikrinami atlikti pakeitimai")
        save_job(job)
        try:
            diff = docx_inspect.compute_diff(job.input_path, output_path)
        except Exception as e:
            log.exception("Job %s attempt %d compute_diff failed", job_id, _attempt + 1)
            msg = f"Output file unreadable: {e}"
            job.history.append((script, msg))
            job.attempt_error = msg
            set_job_stage(job, "retrying", f"{job.attempt} bandymas sukūrė netinkamą dokumentą; ruošiamas kitas būdas")
            add_conversation_message(job, "assistant", f"{job.attempt} bandymas neparuošė tinkamo dokumento. Ieškojome kito sprendimo.")
            save_job(job)
            continue

        log.debug("Job %s attempt %d diff: total=%d changed=%d", job_id, _attempt + 1, diff["total"], diff["changed"])
        if diff["changed"] == 0:
            msg = "Script ran but made no changes to the document"
            job.history.append((script, msg))
            job.attempt_error = msg
            set_job_stage(job, "retrying", f"{job.attempt} bandymas nepadarė pakeitimų; ruošiamas kitas būdas")
            add_conversation_message(job, "assistant", f"{job.attempt} bandymas nepadarė pakeitimų. Ieškojome kito sprendimo.")
            save_job(job)
            continue

        job.output_path = output_path
        job.diff = diff
        job.status = "needs_review"
        set_job_stage(job, "ready_for_review", "Dokumentas paruoštas peržiūrėti")
        add_conversation_message(job, "assistant", "Dokumentas paruoštas. Jį galite atsisiųsti ir peržiūrėti.")
        save_job(job)
        log.info("Job %s ready for review after %d attempt(s): %d change(s)",
                 job_id, _attempt + 1, diff["changed"])
        return

    job.status = "stuck"
    job.last_error = "Po kelių bandymų dokumento paruošti nepavyko. Galite pradėti naują dokumentą ir prašymą aprašyti kitaip."
    set_job_stage(job, "failed", "Visi bandymai baigėsi nesėkmingai")
    add_conversation_message(job, "assistant", job.last_error)
    save_job(job)
    log.info("Job %s stuck after %d attempts: %s", job_id, MAX_ATTEMPTS, job.last_error)
