import os
import logging
import time
from pathlib import Path
from uuid import UUID

import docker
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("docker").setLevel(logging.WARNING)
log = logging.getLogger("executor")

app = FastAPI()

RUST_SANDBOX_IMAGE = os.environ.get("RUST_SANDBOX_IMAGE", "docx-sandbox-rust")
JOBS_DIR = os.environ.get("JOBS_DIR", "/jobs")
HOST_JOBS_DIR = os.environ.get("HOST_JOBS_DIR", JOBS_DIR)
SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "30"))
SANDBOX_MEMORY = os.environ.get("SANDBOX_MEMORY", "1g")
SANDBOX_NETWORK = os.environ.get("SANDBOX_NETWORK", "docx-engineer-sandbox-net")
MAX_SCRIPT_BYTES = 128 * 1024

class RunRequest(BaseModel):
    job_id: UUID


def _ensure_network(client, name: str) -> None:
    """Create the internal sandbox network if it doesn't exist yet."""
    try:
        client.networks.get(name)
    except docker.errors.NotFound:
        log.info("Creating internal sandbox network %s", name)
        client.networks.create(name, driver="bridge", internal=True)


def _failure_diagnostics(container, exit_code: int, error_file: Path) -> str:
    """Return the best available failure signal from the sandbox container."""
    if error_file.exists():
        return error_file.read_text(encoding="utf-8", errors="replace")

    try:
        container.reload()
        state = container.attrs.get("State", {})
        details = [f"exit={exit_code}"]
        if state.get("OOMKilled"):
            details.append("oom_killed=true")
        if state.get("Error"):
            details.append(f"runtime_error={state['Error']}")
        logs = container.logs(stdout=True, stderr=True).decode(errors="replace").strip()
        if logs:
            details.append(f"container_output={logs[-2000:]}")
        return "Sandbox exited before it could save a diagnostic (" + "; ".join(details) + ")"
    except Exception as exc:
        return f"Sandbox exited before it could save a diagnostic (exit={exit_code}; could not inspect container: {exc})"


@app.post("/run")
def run_job(req: RunRequest):
    job_dir = Path(JOBS_DIR) / str(req.job_id)
    host_job_dir = Path(HOST_JOBS_DIR) / str(req.job_id)
    in_path = job_dir / "in.docx"
    out_dir = job_dir / "out"

    artifact_path = job_dir / "script.rhai"
    if not in_path.exists():
        raise HTTPException(400, f"in.docx missing for job {req.job_id}")
    if not artifact_path.exists():
        raise HTTPException(400, f"{artifact_path.name} missing for job {req.job_id}")
    if artifact_path.stat().st_size > MAX_SCRIPT_BYTES:
        return {"success": False, "error": "Script exceeds the 128 KiB limit", "error_kind": "script_error"}

    out_dir.mkdir(exist_ok=True)
    os.chmod(out_dir, 0o777)

    client = None
    container = None
    started_at = time.monotonic()
    def failure(error, kind):
        stage_file = out_dir / "stage.txt"
        try:
            stage = stage_file.read_text().strip()
        except OSError:
            stage = "starting_container"
        return {"success": False, "error": error, "error_kind": kind, "stage": stage,
                "duration_ms": round((time.monotonic() - started_at) * 1000)}
    try:
        client = docker.from_env()
        _ensure_network(client, SANDBOX_NETWORK)
        log.info("Rust sandbox starting for job %s (memory=%s timeout=%ds)", req.job_id, SANDBOX_MEMORY, SANDBOX_TIMEOUT)
        volumes = {
            str(host_job_dir / "in.docx"): {"bind": "/work/in.docx", "mode": "ro"},
            str(host_job_dir / "out"): {"bind": "/work/out", "mode": "rw"},
        }
        volumes[str(host_job_dir / artifact_path.name)] = {"bind": f"/work/{artifact_path.name}", "mode": "ro"}
        command = [
            "/usr/local/bin/docx-engineer-rust", "--input", "/work/in.docx",
            "--script", "/work/script.rhai", "--output", "/work/out/out.docx",
        ]
        container = client.containers.create(
            RUST_SANDBOX_IMAGE,
            network=SANDBOX_NETWORK,
            read_only=True,
            tmpfs={"/tmp": "size=64m"},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            mem_limit=SANDBOX_MEMORY,
            nano_cpus=1_000_000_000,
            pids_limit=64,
            volumes=volumes,
            command=command,
        )
        container.start()

        result = container.wait(timeout=SANDBOX_TIMEOUT)
        exit_code = result["StatusCode"]
        container_logs = container.logs(stdout=True, stderr=True).decode(errors="replace").strip()
        if container_logs:
            # Avoid placing arbitrary user-script output in normal production
            # logs. Failed containers include their last output in the
            # diagnostic below, where it is actionable.
            log.debug("Sandbox container output for job %s:\n%s", req.job_id, container_logs[-2000:])

        if exit_code == 0:
            duration_ms = round((time.monotonic() - started_at) * 1000)
            log.info("Sandbox succeeded for job %s in %dms", req.job_id, duration_ms)
            return {"success": True, "error": None, "engine": "rust", "duration_ms": duration_ms}

        container.reload()
        if container.attrs.get("State", {}).get("OOMKilled"):
            error = "OOM: sandbox killed (out of memory). Script must be more memory-efficient: avoid storing large intermediate lists, process paragraphs one at a time without accumulating data."
            log.warning("Sandbox OOM for job %s", req.job_id)
            return failure(error, "oom")

        error_file = out_dir / "error.txt"
        error = _failure_diagnostics(container, exit_code, error_file)
        log.warning("Sandbox failed for job %s (exit %d): %s", req.job_id, exit_code, error)
        return failure(error, "rust_error")

    except Exception as e:
        if "timed out" in str(e).lower() or "ReadTimeout" in type(e).__name__:
            log.warning("Sandbox timeout for job %s (limit %ds)", req.job_id, SANDBOX_TIMEOUT)
            return failure(f"Timeout: script took longer than {SANDBOX_TIMEOUT}s. Avoid nested loops and repeated XML parsing.", "timeout")
        log.exception("Sandbox run failed for job %s", req.job_id)
        return failure(f"Executor error: {e}", "executor_error")
    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass
        if client:
            client.close()


@app.get("/health")
def health():
    return {"status": "ok"}
