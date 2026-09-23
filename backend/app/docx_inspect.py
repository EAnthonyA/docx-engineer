import json
import zipfile
from difflib import SequenceMatcher
from itertools import islice, zip_longest

from lxml import etree


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_P = f"{{{_W}}}p"
_BODY = f"{{{_W}}}body"
_TEXT = f"{{{_W}}}t"
_RUN = f"{{{_W}}}r"
_PARAGRAPH_PROPERTIES = f"{{{_W}}}pPr"
_PARAGRAPH_STYLE = f"{{{_W}}}pStyle"
_RUN_PROPERTIES = f"{{{_W}}}rPr"
_DIFF_PARA_LIMIT = 50


def _release_element(element) -> None:
    """Discard a streamed element and its processed siblings."""
    parent = element.getparent()
    element.clear()
    if parent is None:
        return

    while element.getprevious() is not None:
        del parent[0]


def _paragraph_style_names(docx_path: str) -> dict[str, str]:
    """Read paragraph style IDs without building a python-docx document tree."""
    names: dict[str, str] = {}
    try:
        with zipfile.ZipFile(docx_path) as archive:
            with archive.open("word/styles.xml") as styles_file:
                for _, style in etree.iterparse(
                    styles_file, events=("end",), tag=f"{{{_W}}}style"
                ):
                    _add_paragraph_style_name(names, style)
                    style.clear()
    except KeyError:
        # styles.xml is optional in a valid DOCX. The summary still works
        # without it and reports the standard style name below.
        pass
    return names


def _add_paragraph_style_name(names: dict[str, str], style) -> None:
    if style.get(f"{{{_W}}}type") != "paragraph":
        return

    style_id = style.get(f"{{{_W}}}styleId")
    name = style.find(f"{{{_W}}}name")
    if style_id and name is not None:
        names[style_id] = name.get(f"{{{_W}}}val", style_id)


def _paragraph_text(paragraph) -> str:
    return "".join((node.text or "") for node in paragraph.iterfind(f".//{_TEXT}"))


def _style_name(paragraph, style_names: dict[str, str]) -> str:
    properties = paragraph.find(_PARAGRAPH_PROPERTIES)
    style = properties.find(_PARAGRAPH_STYLE) if properties is not None else None
    style_id = style.get(f"{{{_W}}}val") if style is not None else None
    return style_names.get(style_id, style_id or "Normal")


def _append_sample_paragraph(
    samples: list[dict], paragraph, text: str, index: int, style_names: dict[str, str]
) -> None:
    if not text.strip() or len(samples) >= _DIFF_PARA_LIMIT:
        return

    samples.append({
        "index": index,
        "style": _style_name(paragraph, style_names),
        "text_preview": text[:300],
        "run_count": len(paragraph.findall(f"./{_RUN}")),
    })


def summarize(path: str) -> str:
    """Return a bounded summary without loading the whole DOCX tree.

    ``python-docx.Document(path)`` constructs a Python object for every XML
    element. A visually ordinary, long Word document can therefore consume
    multiple gigabytes of memory before this lightweight preflight step has
    even reached the sandbox. This parser scans only the first 2,000 top-level
    body paragraphs and releases parsed XML immediately.
    """
    style_names = _paragraph_style_names(path)
    samples: list[dict] = []
    total = 0
    non_empty = 0

    with zipfile.ZipFile(path) as archive:
        with archive.open("word/document.xml") as document_file:
            for _, paragraph in etree.iterparse(document_file, events=("end",), tag=_P):
                parent = paragraph.getparent()
                if parent is None or parent.tag != _BODY:
                    _release_element(paragraph)
                    continue

                total += 1
                text = _paragraph_text(paragraph)
                if text.strip():
                    non_empty += 1
                _append_sample_paragraph(samples, paragraph, text, total - 1, style_names)

                if total >= 2_000:
                    break
                _release_element(paragraph)

    return json.dumps({
        "total_paragraphs": total,
        "non_empty_paragraphs": non_empty,
        "sample_paragraphs": samples,
        # Table dimensions were never needed by script generation and
        # collecting them required retaining entire table trees. Preserve
        # the prompt field for compatibility while keeping preflight bounded.
        "tables": [],
    }, indent=2)


def _run_details(run) -> dict | None:
    properties = run.find(_RUN_PROPERTIES)
    text_element = run.find(_TEXT)
    text = (text_element.text or "") if text_element is not None else ""
    if not text:
        return None

    return {
        "text": text,
        "bold": properties is not None and properties.find(f"{{{_W}}}b") is not None,
        "italic": properties is not None and properties.find(f"{{{_W}}}i") is not None,
        "underline": properties is not None and properties.find(f"{{{_W}}}u") is not None,
    }


def _paragraph_details(paragraph) -> dict:
    runs = [details for run in paragraph.findall(f".//{_RUN}")
            if (details := _run_details(run)) is not None]
    return {"text": "".join(run["text"] for run in runs), "style": "Normal", "runs": runs}


def _iter_paras_fast(docx_path: str):
    """Yield document paragraphs while keeping the XML parser memory-bounded."""
    with zipfile.ZipFile(docx_path) as archive:
        with archive.open("word/document.xml") as document_file:
            for _, paragraph in etree.iterparse(document_file, events=("end",), tag=_P):
                yield _paragraph_details(paragraph)
                _release_element(paragraph)


def _extract_paras_fast(docx_path: str, limit: int) -> list:
    """Return at most `limit` streamed paragraphs for small preview diffs."""
    return list(islice(_iter_paras_fast(docx_path), limit))


def _entry(status: str, before, after) -> dict:
    return {"status": status, "before": before, "after": after}


def _replace_entries(befores: list, afters: list) -> list:
    """Pair replacements; the longer side's tail becomes added or removed."""
    entries = []
    for before, after in zip_longest(befores, afters):
        if before is None:
            entries.append(_entry("added", None, after))
            continue
        if after is None:
            entries.append(_entry("removed", before, None))
            continue
        status = "unchanged" if before == after else "changed"
        entries.append(_entry(status, before, after))
    return entries


def _preview_entries(original: list, modified: list) -> list:
    entries = []
    matcher = SequenceMatcher(
        None, [paragraph["text"] for paragraph in original],
        [paragraph["text"] for paragraph in modified], autojunk=True,
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            entries.extend(
                _entry("unchanged", original[i], modified[j])
                for i, j in zip(range(i1, i2), range(j1, j2))
            )
            continue
        if tag == "delete":
            entries.extend(_entry("removed", original[i], None) for i in range(i1, i2))
            continue
        if tag == "insert":
            entries.extend(_entry("added", None, modified[j]) for j in range(j1, j2))
            continue
        entries.extend(_replace_entries(original[i1:i2], modified[j1:j2]))
    return entries


def _diff_status(before, after, sentinel: object) -> tuple[str, object, object]:
    if before is sentinel:
        return "added", None, after
    if after is sentinel:
        return "removed", before, None
    return ("unchanged" if before == after else "changed"), before, after


def _stream_diff(original_path: str, modified_path: str) -> tuple[int, int, list]:
    examples = []
    total = 0
    changed = 0
    sentinel = object()

    for before, after in zip_longest(
        _iter_paras_fast(original_path),
        _iter_paras_fast(modified_path),
        fillvalue=sentinel,
    ):
        total += 1
        status, before, after = _diff_status(before, after, sentinel)
        if status == "unchanged":
            continue

        changed += 1
        if len(examples) < _DIFF_PARA_LIMIT:
            examples.append(_entry(status, before, after))
    return total, changed, examples


def compute_diff(original_path: str, modified_path: str) -> dict:
    """Compare an entire document with bounded memory use.

    Keep 50 aligned preview entries for small documents, while the streaming
    pass counts every changed paragraph in larger documents.
    """
    original_preview = _extract_paras_fast(original_path, _DIFF_PARA_LIMIT)
    modified_preview = _extract_paras_fast(modified_path, _DIFF_PARA_LIMIT)
    preview_entries = _preview_entries(original_preview, modified_preview)
    total, changed, stream_examples = _stream_diff(original_path, modified_path)

    preview_changed = [entry for entry in preview_entries if entry["status"] != "unchanged"]
    if preview_changed and total <= _DIFF_PARA_LIMIT:
        return {
            "total": total,
            "changed": len(preview_changed),
            "entries": preview_entries,
        }
    return {"total": total, "changed": changed, "entries": stream_examples}
