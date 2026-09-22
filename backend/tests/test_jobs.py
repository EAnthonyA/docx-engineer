from app import jobs


def test_job_state_survives_an_empty_process_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    jobs._jobs.clear()

    job = jobs.create_job("Make the title bold")
    job.status = "needs_review"
    job.output_path = str(tmp_path / job.id / "out" / "out.docx")
    job.diff = {"total": 1, "changed": 1, "entries": []}
    jobs.save_job(job)

    # Simulate a newly started backend process with no in-memory job cache.
    jobs._jobs.clear()
    restored = jobs.get_job(job.id)

    assert restored is not None
    assert restored.instruction == "Make the title bold"
    assert restored.status == "needs_review"
    assert restored.output_path == job.output_path
    assert restored.diff == job.diff


def test_interrupted_running_job_becomes_retryable(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    jobs._jobs.clear()

    job = jobs.create_job("Replace 2023 with 2024")
    jobs.save_job(job)
    jobs._jobs.clear()

    assert jobs.recover_interrupted_jobs() == [job.id]

    jobs._jobs.clear()
    restored = jobs.get_job(job.id)
    assert restored is not None
    assert restored.status == "stuck"
    assert restored.last_error == "Job interrupted by a backend restart. Please try again."
