import os
import re
import logging
from pathlib import Path

import docker
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=_log_level)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("docker").setLevel(logging.WARNING)
log = logging.getLogger("executor")

app = FastAPI()

SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "docx-sandbox")
JOBS_DIR = os.environ.get("JOBS_DIR", "/jobs")
HOST_JOBS_DIR = os.environ.get("HOST_JOBS_DIR", JOBS_DIR)
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
    host_job_dir = Path(HOST_JOBS_DIR) / req.job_id
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
        container = client.containers.create(
            SANDBOX_IMAGE,
            network_mode="none",
            tmpfs={"/tmp": "size=64m"},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            mem_limit="1g",
            nano_cpus=1_000_000_000,
            pids_limit=64,
            volumes={
                str(host_job_dir / "in.docx"): {"bind": "/work/in.docx", "mode": "ro"},
                str(host_job_dir / "out"): {"bind": "/work/out", "mode": "rw"},
                str(host_job_dir / "script.py"): {"bind": "/work/script.py", "mode": "ro"},
            },
        )
        container.start()

        result = container.wait(timeout=SANDBOX_TIMEOUT)
        exit_code = result["StatusCode"]
        container_logs = container.logs(stdout=True, stderr=True).decode(errors="replace").strip()
        if container_logs:
            log.debug("Sandbox container output:\n%s", container_logs)

        if exit_code == 0:
            log.info("Sandbox succeeded for job %s", req.job_id)
            return {"success": True, "error": None}

        if exit_code == 137:
            error = "OOM: sandbox killed (out of memory). Script must be more memory-efficient: avoid storing large intermediate lists, process paragraphs one at a time without accumulating data."
            log.warning("Sandbox OOM for job %s", req.job_id)
            return {"success": False, "error": error}

        error_file = out_dir / "error.txt"
        error = error_file.read_text() if error_file.exists() else "No traceback captured"
        log.warning("Sandbox failed for job %s (exit %d): %s", req.job_id, exit_code, error)
        return {"success": False, "error": error}

    except Exception as e:
        if "timed out" in str(e).lower() or "ReadTimeout" in type(e).__name__:
            log.warning("Sandbox timeout for job %s (limit %ds)", req.job_id, SANDBOX_TIMEOUT)
            return {"success": False, "error": f"Timeout: script took longer than {SANDBOX_TIMEOUT}s. Rewrite for performance: avoid nested loops, process paragraphs in a single pass, do not re-parse XML repeatedly."}
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
