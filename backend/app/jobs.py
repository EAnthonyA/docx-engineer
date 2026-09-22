import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

JOBS_DIR = Path(os.environ.get("JOBS_DIR", "/jobs"))


@dataclass
class Job:
    id: str
    input_path: str
    instruction: str
    history: list = field(default_factory=list)  # [(script, outcome), ...]
    status: str = "running"  # running | needs_review | needs_clarification | done | stuck
    output_path: str | None = None
    diff: dict | None = None
    last_error: str | None = None
    last_script: str | None = None
    question: str | None = None
    clarifications: list = field(default_factory=list)  # [(question, answer), ...]
    attempt: int = 0
    attempt_error: str | None = None
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
    save_job(job)
    return job


def _is_valid_job_id(job_id: str) -> bool:
    try:
        return str(uuid.UUID(job_id)) == job_id
    except ValueError:
        return False


def _metadata_path(job_id: str) -> Path:
    return JOBS_DIR / job_id / "job.json"


def save_job(job: Job) -> None:
    """Atomically persist state so a backend restart cannot erase a job."""
    metadata_path = _metadata_path(job.id)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = metadata_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(asdict(job), separators=(",", ":")), encoding="utf-8")
    temp_path.replace(metadata_path)


def _load_job(job_id: str) -> Job | None:
    if not _is_valid_job_id(job_id):
        return None

    try:
        data = json.loads(_metadata_path(job_id).read_text(encoding="utf-8"))
        if data.get("id") != job_id:
            return None
        return Job(**data)
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return None


def get_job(job_id: str) -> Job | None:
    job = _jobs.get(job_id)
    if job:
        return job

    job = _load_job(job_id)
    if job:
        _jobs[job_id] = job
    return job


def recover_interrupted_jobs() -> list[str]:
    """Make jobs interrupted by a process restart visible and retryable."""
    interrupted = []
    for metadata_path in JOBS_DIR.glob("*/job.json"):
        job = _load_job(metadata_path.parent.name)
        if not job or job.status != "running":
            continue
        job.status = "stuck"
        job.last_error = "Job interrupted by a backend restart. Please try again."
        save_job(job)
        _jobs[job.id] = job
        interrupted.append(job.id)
    return interrupted


def cleanup_old_jobs(max_age: float = 24 * 3600) -> None:
    now = time.time()
    for metadata_path in JOBS_DIR.glob("*/job.json"):
        job = _load_job(metadata_path.parent.name)
        if job and now - job.created_at > max_age:
            shutil.rmtree(metadata_path.parent, ignore_errors=True)
            _jobs.pop(job.id, None)
