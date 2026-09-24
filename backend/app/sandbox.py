import os
import time

import httpx

_EXECUTOR_URL = os.environ.get("EXECUTOR_URL", "http://executor:8001")
_SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "180"))


def run_script(job_id: str) -> dict:
    """Ask the executor to run the sandbox for the given job. Returns {success, error}."""
    try:
        with httpx.Client(timeout=_SANDBOX_TIMEOUT + 15) as client:
            for attempt in range(3):
                try:
                    resp = client.post(f"{_EXECUTOR_URL}/run", json={"job_id": job_id})
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            resp.raise_for_status()
            result = resp.json()
            if not isinstance(result, dict) or not isinstance(result.get("success"), bool):
                raise ValueError("Executor returned an invalid response")
            return result
    except httpx.TimeoutException:
        # The executor might still be running. Never send a duplicate run or
        # rewrite its script while the outcome is unknown.
        return {"success": False, "error": "Executor response timed out", "error_kind": "executor_timeout"}
    except Exception as e:
        return {"success": False, "error": f"Executor unreachable: {e}", "error_kind": "executor_error"}
