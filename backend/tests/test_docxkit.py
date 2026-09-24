"""Behavior and document-preservation regressions for the editing helpers."""

import re
import pytest

from docx import Document
from docx.shared import Pt, RGBColor

from docxkit import DocxTools


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _para_with_runs(runs):
    """Build a doc whose single body paragraph is composed of explicit runs.

    runs: list of (text, fmt_dict) where fmt_dict may set bold/italic/underline.
    Returns (doc, paragraph).
    """
    doc = Document()
    p = doc.add_paragraph()
    for text, fmt in runs:
        r = p.add_run(text)
        for k, v in fmt.items():
            setattr(r, k, v)
    return doc, p


def _runs_snapshot(para):
    """List of (text, bool(bold)) for the paragraph's current runs."""
    return [(r.text, bool(r.bold)) for r in para.runs]


# ---------------------------------------------------------------------------
# format_tagged
# ---------------------------------------------------------------------------

def test_format_tagged_single_run():
    doc, p = _para_with_runs([("Hello <B>World<D> test", {})])
    count = DocxTools().format_tagged(doc, r"<B>(.*?)<D>", bold=True)
    assert count == 1
    assert p.text == "Hello World test"
    bold_runs = [r.text for r in p.runs if r.bold]
    assert bold_runs == ["World"]


def test_format_tagged_spans_run_boundary():
    doc, p = _para_with_runs([("Hel", {}), ("lo <B>Wor", {}), ("ld<D> test", {})])
    count = DocxTools().format_tagged(doc, r"<B>(.*?)<D>", bold=True)
    assert count == 1
    assert p.text == "Hello World test"
    assert "".join(r.text for r in p.runs if r.bold) == "World"


def test_format_tagged_preserves_preexisting_bold():
    # Regression: a non-tagged word that was bold in the original must stay bold
    # after the tagged region is reformatted (the "Nuzudyta" bug).
    doc, p = _para_with_runs([
        ("<B>Tag<D> ", {}),
        ("Nuzudyta", {"bold": True}),
        (" end", {}),
    ])
    count = DocxTools().format_tagged(doc, r"<B>(.*?)<D>", bold=True)
    assert count == 1
    assert p.text == "Tag Nuzudyta end"
    snap = _runs_snapshot(p)
    # Tag is now bold; Nuzudyta keeps its original bold; surrounding stays plain.
    assert ("Nuzudyta", True) in snap
    assert any(text == "Tag" and bold for text, bold in snap)
    assert any("end" in text and not bold for text, bold in snap)


def test_format_tagged_no_match_leaves_paragraph_untouched():
    doc, p = _para_with_runs([("plain text here", {})])
    count = DocxTools().format_tagged(doc, r"<B>(.*?)<D>", bold=True)
    assert count == 0
    assert p.text == "plain text here"


def test_format_tagged_applies_color_and_size():
    doc, p = _para_with_runs([("a <B>word<D> b", {})])
    count = DocxTools().format_tagged(doc, r"<B>(.*?)<D>", color="FF0000", size_pt=20)
    assert count == 1
    word = [r for r in p.runs if r.text == "word"][0]
    assert word.font.color.rgb == RGBColor(0xFF, 0x00, 0x00)
    assert word.font.size == Pt(20)


def test_format_tagged_processes_tables_and_headers():
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).paragraphs[0].add_run("x <B>cell<D> y")
    doc.sections[0].header.paragraphs[0].add_run("h <B>head<D> z")

    count = DocxTools().format_tagged(doc, r"<B>(.*?)<D>", bold=True, locations="all")
    assert count == 2
    assert table.cell(0, 0).paragraphs[0].text == "x cell y"
    assert doc.sections[0].header.paragraphs[0].text == "h head z"


# ---------------------------------------------------------------------------
# replace_text
# ---------------------------------------------------------------------------

def test_replace_text_spans_run_boundary():
    doc, p = _para_with_runs([("foo", {}), ("bar", {})])
    count = DocxTools().replace_text(doc, "oob", "XYZ")
    assert count == 1
    assert p.text == "fXYZar"


def test_replace_text_locations_body_skips_header():
    doc = Document()
    doc.add_paragraph("hit here")
    doc.sections[0].header.paragraphs[0].add_run("hit here")

    count = DocxTools().replace_text(doc, "hit", "X", locations="body")
    assert count == 1
    assert doc.paragraphs[0].text == "X here"
    assert doc.sections[0].header.paragraphs[0].text == "hit here"


# ---------------------------------------------------------------------------
# regex_replace
# ---------------------------------------------------------------------------

def test_regex_replace_with_backrefs():
    doc, p = _para_with_runs([("01.02.2003", {})])
    count = DocxTools().regex_replace(doc, r"(\d{2})\.(\d{2})\.(\d{4})", r"\3-\2-\1")
    assert count == 1
    assert p.text == "2003-02-01"


def test_regex_replace_with_callable():
    doc, p = _para_with_runs([("abc def", {})])
    count = DocxTools().regex_replace(doc, r"abc", lambda m: m.group(0).upper())
    assert count == 1
    assert p.text == "ABC def"


# ---------------------------------------------------------------------------
# iter_paragraphs
# ---------------------------------------------------------------------------

def test_iter_paragraphs_covers_body_table_header():
    doc = Document()
    doc.add_paragraph("body")
    doc.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0].add_run("cell")
    doc.sections[0].header.paragraphs[0].add_run("head")

    all_texts = [p.text for p in DocxTools().iter_paragraphs(doc, locations="all")]
    assert "body" in all_texts
    assert "cell" in all_texts
    assert "head" in all_texts

    body_texts = [p.text for p in DocxTools().iter_paragraphs(doc, locations="body")]
    assert "head" not in body_texts


# ---------------------------------------------------------------------------
# delete_paragraphs
# ---------------------------------------------------------------------------

def test_delete_paragraphs_removes_matching():
    doc = Document()
    doc.add_paragraph("keep")
    doc.add_paragraph("TODO: drop me")
    doc.add_paragraph("also keep")

    count = DocxTools().delete_paragraphs(doc, lambda t: t.startswith("TODO:"))
    assert count == 1
    assert [p.text for p in doc.paragraphs] == ["keep", "also keep"]


# ---------------------------------------------------------------------------
# set_format
# ---------------------------------------------------------------------------

def test_set_format_applies_to_all_runs():
    doc, p = _para_with_runs([("one ", {}), ("two", {})])
    DocxTools().set_format(p, bold=True, color="00FF00", size_pt=14)
    for r in p.runs:
        assert r.bold is True
        assert r.font.color.rgb == RGBColor(0x00, 0xFF, 0x00)
        assert r.font.size == Pt(14)


def test_replacement_preserves_formatting_on_surrounding_text():
    doc, para = _para_with_runs([("Name: Alice ", {}), ("IMPORTANT", {"bold": True})])
    DocxTools().replace_text(doc, "Alice", "Alexandria")
    assert para.text == "Name: Alexandria IMPORTANT"
    assert "".join(r.text for r in para.runs if r.bold) == "IMPORTANT"


def test_tag_formatting_preserves_links_drawings_bookmarks_and_font():
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc, para = _para_with_runs([("<B>bold<D> ", {})])
    para.runs[0].font.name = "Courier New"
    para.runs[0].font.superscript = True
    link = OxmlElement("w:hyperlink")
    link.set(qn("w:anchor"), "target")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "link"
    run.append(text)
    link.append(run)
    para._p.append(link)
    bookmark = OxmlElement("w:bookmarkStart")
    bookmark.set(qn("w:id"), "1")
    bookmark.set(qn("w:name"), "target")
    para._p.append(bookmark)
    drawing = OxmlElement("w:drawing")
    para.runs[0]._r.append(drawing)
    DocxTools().format_tagged(doc, r"<B>(.*?)<D>", bold=True)
    assert para.text == "bold link"
    assert link.getparent() is para._p
    assert bookmark.getparent() is para._p
    assert drawing.getparent() is not None
    bold = next(r for r in para.runs if r.text == "bold")
    assert bold.font.name == "Courier New"
    assert bold.font.superscript is True


def test_tags_spanning_hyperlink_keep_the_link_and_internal_formatting():
    from docx.oxml import OxmlElement
    from docx.text.run import Run
    doc, para = _para_with_runs([("<B>before ", {})])
    link = OxmlElement("w:hyperlink")
    element = OxmlElement("w:r")
    run = Run(element, para)
    run.text = "linked"
    run.italic = True
    link.append(element)
    para._p.append(link)
    para.add_run(" after<D>")
    DocxTools().format_tagged(doc, r"<B>(.*?)<D>", bold=True)
    assert para.text == "before linked after"
    assert run.bold is True and run.italic is True
    assert element.getparent() is link


@pytest.mark.parametrize("pattern,replacement", [
    (r"(?<=USD )\d+", "200"), (r"\d+(?= EUR)", "200"),
    (r"(?=\d)", "X"), (r"$", "!"), (r"^", "!"),
    (r"(\d+)", r"[\1]"), (r"\b", "|"), (r"\d*", "X"),
])
def test_regex_matches_python_sub_across_runs(pattern, replacement):
    text = "USD 100 and 20 EUR"
    doc, para = _para_with_runs([(text[:6], {}), (text[6:10], {"bold": True}), (text[10:], {})])
    DocxTools().regex_replace(doc, pattern, replacement, locations="body")
    assert para.text == re.sub(pattern, replacement, text)


def test_multiple_tags_in_one_run_and_empty_capture():
    doc, para = _para_with_runs([("a <B>one<D> b <B><D> c <B>two<D>", {})])
    assert DocxTools().format_tagged(doc, r"<B>(.*?)<D>", bold=True) == 3
    assert para.text == "a one b  c two"
    assert "".join(r.text for r in para.runs if r.bold) == "onetwo"


def test_locations_are_disjoint_and_shared_headers_are_visited_once():
    from docx.enum.section import WD_SECTION_START
    doc = Document()
    doc.add_paragraph("A")
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "A"
    header = doc.sections[0].header
    header.paragraphs[0].text = "A"
    header.add_table(rows=1, cols=1, width=Pt(100)).cell(0, 0).text = "A"
    doc.add_section(WD_SECTION_START.NEW_PAGE)
    tools = DocxTools()
    assert tools.replace_text(doc, "A", "AA", locations="tables") == 1
    assert doc.paragraphs[0].text == "A"
    assert table.cell(0, 0).text == "AA"
    assert tools.replace_text(doc, "A", "AA", locations="headers_footers") == 2
    assert header.paragraphs[0].text == "AA"
    assert header.tables[0].cell(0, 0).text == "AA"
    assert tools.replace_text(doc, "A", "X", locations="body") == 1
    assert table.cell(0, 0).text == "AA"


def test_no_op_does_not_materialize_headers():
    doc = Document()
    doc.add_paragraph("unchanged")
    before = list(doc.part.rels)
    assert DocxTools().replace_text(doc, "absent", "new") == 0
    assert list(doc.part.rels) == before


def test_tag_pattern_requires_one_participating_capture():
    doc = Document()
    doc.add_paragraph("<B>text<D>")
    with pytest.raises(ValueError, match="one capture"):
        DocxTools().format_tagged(doc, r"<B>.*?<D>")
    with pytest.raises(ValueError, match="participate"):
        DocxTools().format_tagged(doc, r"(absent)?<B>.*?<D>")


def test_replacement_preserves_page_breaks_and_removes_empty_tag_runs():
    from docx.enum.text import WD_BREAK
    from docx.oxml.ns import qn
    doc, para = _para_with_runs([("<B>", {}), ("keep", {}), ("<D>", {})])
    para.runs[1].add_break(WD_BREAK.PAGE)
    DocxTools().format_tagged(doc, r"<B>(.*?)<D>", bold=True)
    assert para.text == "keep"
    assert len(para.runs) == 1
    assert para.runs[0]._r.find(qn("w:br")) is not None


def test_deleting_consecutive_paragraphs_does_not_skip_any():
    doc = Document()
    for index in range(100):
        doc.add_paragraph(str(index))
    assert DocxTools().delete_paragraphs(doc, lambda text: text != "99") == 99
    assert [p.text for p in doc.paragraphs] == ["99"]
