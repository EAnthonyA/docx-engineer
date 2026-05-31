import os

import httpx

_EXECUTOR_URL = os.environ.get("EXECUTOR_URL", "http://executor:8001")
_SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "60"))


def run_script(job_id: str) -> dict:
    """Ask the executor to run the sandbox for the given job. Returns {success, error}."""
    try:
        with httpx.Client(timeout=_SANDBOX_TIMEOUT + 15) as client:
            resp = client.post(f"{_EXECUTOR_URL}/run", json={"job_id": job_id})
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException:
        return {"success": False, "error": "Sandbox timed out"}
    except Exception as e:
        return {"success": False, "error": f"Executor unreachable: {e}"}
