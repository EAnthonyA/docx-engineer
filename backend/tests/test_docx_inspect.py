import io
import json
import tempfile
from pathlib import Path

import pytest
from docx import Document

from app.docx_inspect import compute_diff, summarize


def _make_docx(paragraphs: list[str]) -> str:
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    doc.save(tmp.name)
    return tmp.name


def test_summarize_returns_valid_json():
    path = _make_docx(["Hello world", "Second paragraph", "Third paragraph"])
    result = summarize(path)
    data = json.loads(result)
    assert data["total_paragraphs"] >= 3
    assert data["non_empty_paragraphs"] >= 3


def test_compute_diff_unchanged():
    path = _make_docx(["Same text"])
    diff = compute_diff(path, path)
    assert diff["changed"] == 0
    assert all(e["status"] == "unchanged" for e in diff["entries"])


def test_compute_diff_detects_change():
    orig = _make_docx(["Original text", "Unchanged paragraph"])

    doc = Document(orig)
    for para in doc.paragraphs:
        if para.text == "Original text":
            para.clear()
            run = para.add_run("Modified text")
            run.bold = True
    import tempfile
    modified = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    doc.save(modified.name)

    diff = compute_diff(orig, modified.name)
    assert diff["changed"] > 0
    changed = [e for e in diff["entries"] if e["status"] == "changed"]
    assert len(changed) >= 1
