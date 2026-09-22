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
    assert restored.last_error == "Darbas buvo nutrauktas perkrovus sistemą. Pasirinkite dokumentą ir bandykite dar kartą."


def test_job_stage_history_is_persisted_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    jobs._jobs.clear()

    job = jobs.create_job("Make the title bold")
    for index in range(25):
        jobs.set_job_stage(job, f"stage-{index}", f"Detail {index}")
    jobs.save_job(job)
    jobs._jobs.clear()

    restored = jobs.get_job(job.id)
    assert restored is not None
    assert restored.stage == "stage-24"
    assert restored.stage_detail == "Detail 24"
    assert len(restored.activity) == 20
    assert restored.activity[0]["stage"] == "stage-5"


def test_job_conversation_and_history_listing_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    jobs._jobs.clear()

    older = jobs.create_job("Pakeiskite 2023 į 2024")
    jobs.add_conversation_message(older, "assistant", "Dokumentas paruoštas.")
    older.created_at = 1
    jobs.save_job(older)

    newer = jobs.create_job("Paryškinkite datas")
    newer.created_at = 2
    jobs.save_job(newer)
    jobs._jobs.clear()

    listed = jobs.list_jobs()
    assert [job.id for job in listed] == [newer.id, older.id]
    assert [message["text"] for message in listed[1].conversation] == [
        "Pakeiskite 2023 į 2024",
        "Dokumentas paruoštas.",
    ]


def test_finished_job_keeps_only_chat_history(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    jobs._jobs.clear()

    job = jobs.create_job("Make the title bold")
    job_dir = tmp_path / job.id
    input_file = job_dir / "in.docx"
    output_file = job_dir / "out" / "out.docx"
    script_file = job_dir / "script.py"
    input_file.write_bytes(b"input")
    output_file.write_bytes(b"output")
    script_file.write_text("print('document data')", encoding="utf-8")
    jobs.add_conversation_message(job, "assistant", "Dokumentas paruoštas.")
    job.status = "needs_review"
    job.output_path = str(output_file)
    job.diff = {"total": 1, "changed": 1, "entries": []}
    job.history = [("print('document data')", "ok")]
    job.last_script = "print('document data')"
    jobs.save_job(job)

    assert jobs.archive_finished_job_documents() == [job.id]
    assert not input_file.exists()
    assert not output_file.exists()
    assert not script_file.exists()

    jobs._jobs.clear()
    archived = jobs.get_job(job.id)
    assert archived is not None
    assert archived.status == "done"
    assert archived.input_path == ""
    assert archived.output_path is None
    assert archived.diff is None
    assert archived.history == []
    assert archived.last_script is None
    assert [message["text"] for message in archived.conversation] == [
        "Make the title bold",
        "Dokumentas paruoštas.",
    ]
