import importlib.util
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

spec = importlib.util.spec_from_file_location("executor_main", Path(__file__).resolve().parents[2] / "executor/main.py")
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)


@pytest.mark.parametrize("script", [
    "def transform(inp, out): pass", "def edit(doc): pass", "def edit(doc, tools):\n  broken(",
    "import os\ndef edit(doc, tools): pass", "def edit(doc, tools):\n    open('file')",
])
def test_contract_rejects_invalid_scripts(script):
    assert executor._static_check(script)


def test_contract_accepts_safe_imports_and_text_that_mentions_forbidden_words():
    assert executor._static_check("import re\nfrom docx.shared import Pt\ndef edit(doc, tools):\n    tools.replace_text(doc, 'open(', 'socket')") is None


@pytest.mark.parametrize("script", [
    "import docx\ndef edit(doc, tools):\n    return getattr(docx, '__builtins__')['__import__']('os')",
    "import docx\ndef edit(doc, tools):\n    return docx.__builtins__",
    "def edit(doc, tools):\n    return globals()",
])
def test_contract_rejects_indirect_builtin_access(script):
    assert executor._static_check(script)


def test_job_id_cannot_escape_job_directory():
    with pytest.raises(ValidationError):
        executor.RunRequest(job_id="../../etc")


@pytest.mark.parametrize("failure,stage,expected", [
    ("oom", "loading_document", "oom"), ("timeout", "editing_document", "timeout"),
    ("script", "editing_document", "script_error"),
    ("script", "loading_document", "document_error"),
    ("killed", "editing_document", "executor_error"),
    ("startup", "starting_container", "executor_error"),
])
def test_executor_reports_phase_and_kind_and_removes_container(tmp_path, monkeypatch, failure, stage, expected):
    job_id = str(uuid4())
    folder = tmp_path / job_id
    folder.mkdir()
    (folder / "in.docx").write_bytes(b"fixture")
    (folder / "script.py").write_text("def edit(doc, tools): pass")
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
