import importlib.util
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

spec = importlib.util.spec_from_file_location("executor_main", Path(__file__).resolve().parents[2] / "executor/main.py")
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)


def test_job_id_cannot_escape_job_directory():
    with pytest.raises(ValidationError):
        executor.RunRequest(job_id="../../etc")


def test_rust_mode_mounts_only_the_generated_rhai_script(tmp_path, monkeypatch):
    job_id = str(uuid4())
    folder = tmp_path / job_id
    folder.mkdir()
    (folder / "in.docx").write_bytes(b"fixture")
    (folder / "script.rhai").write_text('replace_text("TODO", "Done", "body");')
    monkeypatch.setattr(executor, "JOBS_DIR", str(tmp_path))
    monkeypatch.setattr(executor, "HOST_JOBS_DIR", str(tmp_path))
    monkeypatch.setattr(executor, "RUST_SANDBOX_IMAGE", "docx-sandbox-rust-test")
    client = MagicMock()
    container = client.containers.create.return_value
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b""
    monkeypatch.setattr(executor.docker, "from_env", lambda: client)

    result = executor.run_job(executor.RunRequest(job_id=job_id))

    assert result["success"] is True
    assert result["engine"] == "rust"
    kwargs = client.containers.create.call_args.kwargs
    assert client.containers.create.call_args.args[0] == "docx-sandbox-rust-test"
    assert "/work/script.rhai" in {mount["bind"] for mount in kwargs["volumes"].values()}
    assert "/work/plan.json" not in {mount["bind"] for mount in kwargs["volumes"].values()}
    assert "/work/script.py" not in {mount["bind"] for mount in kwargs["volumes"].values()}
    assert kwargs["command"][:1] == ["/usr/local/bin/docx-engineer-rust"]
    assert "--script" in kwargs["command"]


@pytest.mark.parametrize("failure,stage,expected", [
    ("oom", "loading_document", "oom"), ("timeout", "editing_document", "timeout"),
    ("script", "editing_document", "rust_error"),
    ("script", "loading_document", "rust_error"),
    ("killed", "editing_document", "rust_error"),
    ("startup", "starting_container", "executor_error"),
])
def test_executor_reports_phase_and_kind_and_removes_container(tmp_path, monkeypatch, failure, stage, expected):
    job_id = str(uuid4())
    folder = tmp_path / job_id
    folder.mkdir()
    (folder / "in.docx").write_bytes(b"fixture")
    (folder / "script.rhai").write_text('replace_text("TODO", "Done", "body");')
    (folder / "out").mkdir()
    (folder / "out/stage.txt").write_text(stage)
    monkeypatch.setattr(executor, "JOBS_DIR", str(tmp_path))
    monkeypatch.setattr(executor, "HOST_JOBS_DIR", str(tmp_path))
    client = MagicMock()
    container = client.containers.create.return_value
    container.attrs = {"State": {"OOMKilled": failure == "oom"}}
    container.logs.return_value = b""
    container.wait.return_value = {"StatusCode": 137 if failure in {"oom", "killed"} else 1}
    if failure == "timeout": container.wait.side_effect = TimeoutError("timed out")
    monkeypatch.setattr(executor.docker, "from_env", lambda: client)
    if failure == "startup": client.networks.get.side_effect = RuntimeError("Docker unavailable")
    result = executor.run_job(executor.RunRequest(job_id=job_id))
    assert result["error_kind"] == expected
    assert result["stage"] == stage
    client.close.assert_called_once()
    if failure != "startup":
        container.remove.assert_called_once_with(force=True)
        assert client.containers.create.call_args.kwargs["read_only"] is True
