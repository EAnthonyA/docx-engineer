import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

JOBS_DIR = Path(os.environ.get("JOBS_DIR", "/jobs"))


@dataclass
class Job:
    id: str
    input_path: str
    instruction: str
    history: list = field(default_factory=list)  # [(script, outcome), ...]
    status: str = "running"  # running | needs_review | done | stuck
    output_path: str | None = None
    diff: dict | None = None
    last_error: str | None = None
    last_script: str | None = None
    created_at: float = field(default_factory=time.time)


_jobs: dict[str, Job] = {}


def create_job(instruction: str) -> Job:
    job_id = str(uuid.uuid4())
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "out").mkdir(exist_ok=True)

    job = Job(
        id=job_id,
        input_path=str(job_dir / "in.docx"),
        instruction=instruction,
    )
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def cleanup_old_jobs(max_age: float = 24 * 3600) -> None:
    now = time.time()
    stale = [jid for jid, j in list(_jobs.items()) if now - j.created_at > max_age]
    for jid in stale:
        shutil.rmtree(JOBS_DIR / jid, ignore_errors=True)
        _jobs.pop(jid, None)
