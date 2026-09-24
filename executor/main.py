import os
import ast
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

SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "docx-sandbox")
JOBS_DIR = os.environ.get("JOBS_DIR", "/jobs")
HOST_JOBS_DIR = os.environ.get("HOST_JOBS_DIR", JOBS_DIR)
SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "30"))
SANDBOX_MEMORY = os.environ.get("SANDBOX_MEMORY", "1g")
SANDBOX_NETWORK = os.environ.get("SANDBOX_NETWORK", "docx-engineer-sandbox-net")

# Syntax and contract validation supplement the container isolation boundary.


class RunRequest(BaseModel):
    job_id: UUID


def _static_check(script: str) -> str | None:
    try:
        tree = ast.parse(script)
    except SyntaxError as exc:
        return f"Invalid Python: {exc.msg} (line {exc.lineno})"
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != "edit":
        return "Define exactly one top-level function: def edit(doc, tools)"
    args = functions[0].args
    if [arg.arg for arg in args.posonlyargs + args.args] != ["doc", "tools"] or args.kwonlyargs or args.vararg or args.kwarg:
        return "Required signature: def edit(doc, tools)"
    allowed_imports = {"docx", "re", "html", "math", "datetime", "decimal", "collections"}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.Import, ast.ImportFrom)):
            return "Only imports and the edit function are allowed at module level"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(name.split(".")[0] not in allowed_imports for name in names):
                return "Unsupported import; use the documented tools API"
        if isinstance(node, ast.Name) and node.id in {"eval", "exec", "open", "compile", "__import__", "__builtins__"}:
            return f"Forbidden operation: {node.id}"
    return None


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
        return "Sandbox exited before it could save a Python traceback (" + "; ".join(details) + ")"
    except Exception as exc:
        return f"Sandbox exited before it could save a Python traceback (exit={exit_code}; could not inspect container: {exc})"


@app.post("/run")
def run_job(req: RunRequest):
    job_dir = Path(JOBS_DIR) / str(req.job_id)
    host_job_dir = Path(HOST_JOBS_DIR) / str(req.job_id)
    script_path = job_dir / "script.py"
    in_path = job_dir / "in.docx"
    out_dir = job_dir / "out"

    if not script_path.exists():
        raise HTTPException(400, f"script.py missing for job {req.job_id}")
    if not in_path.exists():
        raise HTTPException(400, f"in.docx missing for job {req.job_id}")

    violation = _static_check(script_path.read_text())
    if violation:
        return {"success": False, "error": f"Static check failed ({violation})", "error_kind": "script_error"}

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
        log.info(
            "Sandbox starting for job %s (memory=%s timeout=%ds)",
            req.job_id, SANDBOX_MEMORY, SANDBOX_TIMEOUT,
        )
        container = client.containers.create(
            SANDBOX_IMAGE,
            network=SANDBOX_NETWORK,
            read_only=True,
            tmpfs={"/tmp": "size=64m"},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            mem_limit=SANDBOX_MEMORY,
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
            # Avoid placing arbitrary user-script output in normal production
            # logs. Failed containers include their last output in the
            # diagnostic below, where it is actionable.
            log.debug("Sandbox container output for job %s:\n%s", req.job_id, container_logs[-2000:])

        if exit_code == 0:
            duration_ms = round((time.monotonic() - started_at) * 1000)
            log.info("Sandbox succeeded for job %s in %dms", req.job_id, duration_ms)
            return {"success": True, "error": None, "duration_ms": duration_ms}

        container.reload()
        if container.attrs.get("State", {}).get("OOMKilled"):
            error = "OOM: sandbox killed (out of memory). Script must be more memory-efficient: avoid storing large intermediate lists, process paragraphs one at a time without accumulating data."
            log.warning("Sandbox OOM for job %s", req.job_id)
            return failure(error, "oom")

        error_file = out_dir / "error.txt"
        error = _failure_diagnostics(container, exit_code, error_file)
        log.warning("Sandbox failed for job %s (exit %d): %s", req.job_id, exit_code, error)
        result = failure(error, "script_error")
        if result["stage"] in {"loading_document", "saving_document"}:
            result["error_kind"] = "document_error"
        elif result["stage"] == "starting_container" or exit_code == 137:
            result["error_kind"] = "executor_error"
        return result

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
