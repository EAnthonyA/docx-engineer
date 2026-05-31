import os
import re
import logging
from pathlib import Path

import docker
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("executor")

app = FastAPI()

SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "docx-sandbox")
JOBS_DIR = os.environ.get("JOBS_DIR", "/jobs")
SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "30"))

# Defense-in-depth: reject obvious escape hatches before even running the container.
# The container is the real wall; these checks are secondary.
_FORBIDDEN = [
    r"\bos\.system\b",
    r"\bos\.popen\b",
    r"\bsubprocess\b",
    r"\bsocket\b",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\b__import__\s*\(",
    r"\bopen\s*\(",
    r"\bimportlib\b",
    r"__builtins__",
    r"\bctypes\b",
    r"\bpickle\b",
    r"\bmarshal\b",
]


class RunRequest(BaseModel):
    job_id: str


def _static_check(script: str) -> str | None:
    for pattern in _FORBIDDEN:
        if re.search(pattern, script):
            return f"forbidden pattern: {pattern}"
    return None


@app.post("/run")
def run_job(req: RunRequest):
    job_dir = Path(JOBS_DIR) / req.job_id
    script_path = job_dir / "script.py"
    in_path = job_dir / "in.docx"
    out_dir = job_dir / "out"

    if not script_path.exists():
        raise HTTPException(400, f"script.py missing for job {req.job_id}")
    if not in_path.exists():
        raise HTTPException(400, f"in.docx missing for job {req.job_id}")

    violation = _static_check(script_path.read_text())
    if violation:
        return {"success": False, "error": f"Static check failed ({violation})"}

    out_dir.mkdir(exist_ok=True)
    os.chmod(out_dir, 0o777)

    client = docker.from_env()
    container = None
    try:
        container = client.containers.run(
            SANDBOX_IMAGE,
            detach=True,
            network_mode="none",
            read_only=True,
            tmpfs={"/tmp": "size=64m"},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            mem_limit="256m",
            nano_cpus=1_000_000_000,
            pids_limit=64,
            volumes={
                str(in_path.resolve()): {"bind": "/work/in.docx", "mode": "ro"},
                str(out_dir.resolve()): {"bind": "/work/out", "mode": "rw"},
                str(script_path.resolve()): {"bind": "/work/script.py", "mode": "ro"},
            },
        )

        result = container.wait(timeout=SANDBOX_TIMEOUT)
        exit_code = result["StatusCode"]

        if exit_code == 0:
            return {"success": True, "error": None}

        error_file = out_dir / "error.txt"
        error = error_file.read_text() if error_file.exists() else "No traceback captured"
        return {"success": False, "error": error}

    except Exception as e:
        log.exception("Sandbox run failed for job %s", req.job_id)
        return {"success": False, "error": f"Executor error: {e}"}
    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass


@app.get("/health")
def health():
    return {"status": "ok"}
