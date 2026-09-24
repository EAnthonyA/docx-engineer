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


def test_summarize_counts_whole_document_but_bounds_excerpts():
    path = _make_docx([f"Paragraph {index}" for index in range(2_100)])

    data = json.loads(summarize(path))

    assert data["total_paragraphs"] == 2_100
    assert data["non_empty_paragraphs"] == 2_100
    assert len(data["sample_paragraphs"]) <= 50
    assert data["content_is_partial"] is True
    assert data["sample_paragraphs"][0]["text_preview"] == "Paragraph 0"


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


def test_compute_diff_detects_a_change_after_the_preview_window():
    orig = _make_docx([f"Paragraph {index}" for index in range(75)])
    doc = Document(orig)
    doc.paragraphs[60].runs[0].bold = True
    modified = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    doc.save(modified.name)

    diff = compute_diff(orig, modified.name)

    assert diff["total"] == 75
    assert diff["changed"] == 1
    assert diff["entries"][0]["before"]["text"] == "Paragraph 60"


def test_compute_diff_detects_added_paragraphs():
    orig = _make_docx(["one", "two"])
    mod = _make_docx(["one", "two", "three"])
    diff = compute_diff(orig, mod)
    added = [e for e in diff["entries"] if e["status"] == "added"]
    assert len(added) == 1
    assert added[0]["before"] is None
    assert added[0]["after"]["text"] == "three"
    assert diff["changed"] == 1


def test_compute_diff_detects_removed_paragraphs():
    orig = _make_docx(["one", "two", "three"])
    mod = _make_docx(["one", "three"])
    diff = compute_diff(orig, mod)
    removed = [e for e in diff["entries"] if e["status"] == "removed"]
    assert len(removed) == 1
    assert removed[0]["after"] is None
    assert removed[0]["before"]["text"] == "two"


def test_compute_diff_replace_length_mismatch():
    # 1 original line replaced by 2 new lines: one paired "changed", one tail "added".
    orig = _make_docx(["alpha", "shared"])
    mod = _make_docx(["beta", "gamma", "shared"])
    diff = compute_diff(orig, mod)
    statuses = [e["status"] for e in diff["entries"]]
    assert statuses.count("changed") == 1
    assert statuses.count("added") == 1
    assert statuses.count("unchanged") == 1  # "shared"
    assert diff["total"] == 3
    assert diff["changed"] == 2


@pytest.mark.parametrize("change", ["size", "color", "style", "bold_off", "italic_off", "underline_off", "header", "footer", "tabs"])
def test_diff_recognizes_formatting_and_story_changes(tmp_path, change):
    from docx.shared import Pt, RGBColor
    doc = Document()
    run = doc.add_paragraph("Hello world").runs[0]
    run.bold = run.italic = run.underline = True
    doc.sections[0].header.paragraphs[0].text = "Old header"
    doc.sections[0].footer.paragraphs[0].text = "Old footer"
    before, after = tmp_path / "before.docx", tmp_path / "after.docx"
    doc.save(before)
    if change == "size": run.font.size = Pt(24)
    elif change == "color": run.font.color.rgb = RGBColor.from_string("FF0000")
    elif change == "style": doc.paragraphs[0].style = "Heading 1"
    elif change == "bold_off": run.bold = False
    elif change == "italic_off": run.italic = False
    elif change == "underline_off": run.underline = False
    elif change == "header": doc.sections[0].header.paragraphs[0].text = "New header"
    elif change == "footer": doc.sections[0].footer.paragraphs[0].text = "New footer"
    else: run.text = "Hello\tworld\nnext line"
    doc.save(after)
    diff = compute_diff(str(before), str(after))
    assert diff["package_changed"] is True
    assert diff["changed"] == 1
    assert any(entry["status"] == "changed" for entry in diff["entries"])


def test_layout_and_style_definition_changes_count_even_without_text_changes(tmp_path):
    from docx.shared import Inches, Pt
    doc = Document()
    doc.add_paragraph("Hello")
    before, after = tmp_path / "before.docx", tmp_path / "after.docx"
    doc.save(before)
    doc.sections[0].left_margin = Inches(2)
    doc.styles["Normal"].font.size = Pt(24)
    doc.save(after)
    diff = compute_diff(str(before), str(after))
    assert diff["package_changed"] is True
    assert "word/styles.xml" in diff["changed_parts"]
    assert diff["changed"] == 0


def test_resaving_without_an_edit_is_not_a_change(tmp_path):
    from docxkit import DocxTools
    doc = Document()
    doc.add_paragraph("unchanged")
    before, after = tmp_path / "before.docx", tmp_path / "after.docx"
    doc.save(before)
    doc = Document(before)
    DocxTools().replace_text(doc, "absent", "new")
    doc.save(after)
    assert compute_diff(str(before), str(after))["package_changed"] is False


def test_summary_includes_table_header_and_late_target_without_full_text(tmp_path):
    doc = Document()
    for index in range(70):
        doc.add_paragraph("Generic paragraph " + str(index))
    doc.add_paragraph("Conclusion", style="Heading 1")
    doc.add_paragraph("Target invoice 123")
    doc.add_table(rows=2, cols=2).cell(0, 0).text = "Table invoice 456"
    doc.sections[0].header.paragraphs[0].text = "Header invoice 789"
    path = tmp_path / "document.docx"
    doc.save(path)
    summary = json.loads(summarize(str(path), "Update invoice amounts in the conclusion"))
    assert summary["total_tables"] == 1
    assert summary["tables"][0]["rows"] == 2
    assert summary["tables"][0]["cells"] == 4
    assert summary["headers_footers"][0]["text_preview"] == "Header invoice 789"
    assert any(s["text_preview"] == "Target invoice 123" for s in summary["instruction_matches"])
    assert summary["headings"][0]["text_preview"] == "Conclusion"
    assert len(summary["sample_paragraphs"]) < summary["total_paragraphs"]


def test_table_only_document_is_not_described_as_empty(tmp_path):
    doc = Document()
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "Important information"
    path = tmp_path / "table.docx"
    doc.save(path)
    summary = json.loads(summarize(str(path)))
    assert summary["total_tables"] == 1
    assert summary["tables"][0]["samples"][0]["text_preview"] == "Important information"


def test_expanded_size_limit_is_enforced_before_parsing(tmp_path, monkeypatch):
    from app import docx_inspect
    path = tmp_path / "large.docx"
    Document().save(path)
    monkeypatch.setattr(docx_inspect, "MAX_UNCOMPRESSED_BYTES", 100)
    with pytest.raises(docx_inspect.DocumentTooLarge):
        summarize(str(path))
