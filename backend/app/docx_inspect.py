import hashlib
import json
import re
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
_STRUCTURAL_TAGS = (_P, f"{{{_W}}}tbl", f"{{{_W}}}tr", f"{{{_W}}}tc")


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
                for _, style in _xml_events(
                    styles_file, events=("end",), tag=f"{{{_W}}}style"
                ):
                    _add_paragraph_style_name(names, style)
                    _release_element(style)
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


MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


class DocumentTooLarge(ValueError):
    pass


def validate_package(path: str) -> dict:
    """Bound decompression before inspecting or loading an uploaded document."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        total = sum(info.file_size for info in entries)
        if len(entries) > 10_000 or total > MAX_UNCOMPRESSED_BYTES:
            raise DocumentTooLarge("Document exceeds the 512 MiB expanded-size limit")
        if "word/document.xml" not in archive.namelist():
            raise ValueError("Missing Word document content")
        return {"expanded_bytes": total, "document_xml_bytes": archive.getinfo("word/document.xml").file_size}


def _content_parts(archive):
    names = archive.namelist()
    return ["word/document.xml"] + sorted(
        name for name in names
        if re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)
    )


def _xml_events(source, events=("end",), tag=None):
    return etree.iterparse(source, events=events, tag=tag,
                           resolve_entities=False, no_network=True)


def summarize(path: str, instruction: str = "") -> str:
    """Scan structure in bounded memory; send only a bounded, labelled sample."""
    sizes = validate_package(path)
    styles = _paragraph_style_names(path)
    terms = list(dict.fromkeys(re.findall(r"\w{4,}", instruction.casefold())))[:32]
    samples, relevant, headings, tables, headers = [], [], [], [], []
    body_count = non_empty = table_count = 0
    with zipfile.ZipFile(path) as archive:
        for part in _content_parts(archive):
            is_body = part == "word/document.xml"
            table_stack = []
            part_count = 0
            with archive.open(part) as source:
                for event, element in _xml_events(source, ("start", "end"), tag=_STRUCTURAL_TAGS):
                    tag = element.tag
                    if event == "start":
                        if tag == f"{{{_W}}}tbl":
                            table_count += int(is_body)
                            table_stack.append({
                                "index": table_count - 1 if is_body else None,
                                "part": part, "rows": 0, "cells": 0, "samples": [],
                            })
                        elif table_stack and tag == f"{{{_W}}}tr":
                            table_stack[-1]["rows"] += 1
                        elif table_stack and tag == f"{{{_W}}}tc":
                            table_stack[-1]["cells"] += 1
                        continue
                    if tag == _P:
                        text = _paragraph_text(element)
                        part_count += 1
                        location = "tables" if table_stack else ("body" if is_body else "headers_footers")
                        sample = {
                            "index": body_count if is_body and not table_stack else part_count - 1,
                            "part": part, "location": location,
                            "style": _style_name(element, styles),
                            "text_preview": text[:300], "text_truncated": len(text) > 300,
                        }
                        if table_stack:
                            sample["table_index"] = table_stack[-1]["index"]
                            if text.strip() and len(table_stack[-1]["samples"]) < 2:
                                table_stack[-1]["samples"].append(sample)
                        elif is_body:
                            body_count += 1
                            non_empty += bool(text.strip())
                            if text.strip() and len(samples) < 30:
                                samples.append(sample)
                            if sample["style"].lower().startswith(("heading", "title")) and len(headings) < 30:
                                headings.append(sample)
                        elif text.strip() and len(headers) < 12:
                            headers.append(sample)
                        folded = text.casefold()
                        hits = [folded.find(term) for term in terms] if len(relevant) < 20 else []
                        hits = [position for position in hits if position >= 0]
                        if hits and len(relevant) < 20:
                            offset = max(0, min(hits) - 80)
                            relevant.append({**sample, "text_preview": text[offset:offset + 500],
                                             "excerpt_offset": offset, "text_truncated": len(text) > 500})
                        _release_element(element)
                    elif tag == f"{{{_W}}}tbl":
                        table = table_stack.pop()
                        if len(tables) < 20:
                            tables.append(table)
                        _release_element(element)
                    elif tag in {f"{{{_W}}}tr", f"{{{_W}}}tc"}:
                        _release_element(element)
    return json.dumps({
        **sizes, "scan_complete": True, "content_is_partial": True,
        "sampling_note": "Counts cover the document; text excerpts are partial. Omitted text is unknown, not absent. Scripts operate on the complete document.",
        "total_paragraphs": body_count, "non_empty_paragraphs": non_empty,
        "total_tables": table_count, "sample_paragraphs": samples,
        "headings": headings, "tables": tables, "headers_footers": headers,
        "instruction_matches": relevant,
    }, ensure_ascii=False)



def _run_details(run) -> dict | None:
    properties = run.find(_RUN_PROPERTIES)
    text = "".join(
        (child.text or "") if child.tag == _TEXT else
        "\t" if child.tag == f"{{{_W}}}tab" else
        "\n" if child.tag in {f"{{{_W}}}br", f"{{{_W}}}cr"} else ""
        for child in run
    )
    if not text:
        return None

    return {
        "text": text,
        "bold": _on_off(properties, "b"),
        "italic": _on_off(properties, "i"),
        "underline": _on_off(properties, "u"),
        "color": _property_value(properties, "color"),
        "size_pt": float(_property_value(properties, "sz")) / 2 if _property_value(properties, "sz") else None,
        "properties": _properties(properties),
    }


def _property_value(properties, name):
    child = properties.find(f"{{{_W}}}{name}") if properties is not None else None
    return child.get(f"{{{_W}}}val") if child is not None else None


def _on_off(properties, name):
    child = properties.find(f"{{{_W}}}{name}") if properties is not None else None
    return child is not None and child.get(f"{{{_W}}}val", "true") not in {"0", "false", "off", "none"}


def _properties(element):
    if element is None:
        return None
    properties = [(node.tag, sorted(node.attrib.items()), node.text) for node in element.iter()]
    return hashlib.sha256(json.dumps(properties).encode()).hexdigest()


def _paragraph_details(paragraph, style_names=None) -> dict:
    runs = [details for run in paragraph.findall(f".//{_RUN}")
            if (details := _run_details(run)) is not None]
    return {"text": "".join(run["text"] for run in runs),
            "style": _style_name(paragraph, style_names or {}), "runs": runs,
            "properties": _properties(paragraph.find(_PARAGRAPH_PROPERTIES))}


def _iter_paras_fast(docx_path: str):
    """Yield document paragraphs while keeping the XML parser memory-bounded."""
    styles = _paragraph_style_names(docx_path)
    with zipfile.ZipFile(docx_path) as archive:
        for part in _content_parts(archive):
            with archive.open(part) as document_file:
                for _, element in _xml_events(document_file, tag=_STRUCTURAL_TAGS):
                    if element.tag == _P:
                        yield {**_paragraph_details(element, styles), "part": part}
                    _release_element(element)


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
                _entry("unchanged" if original[i] == modified[j] else "changed", original[i], modified[j])
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
    changed_parts = _changed_parts(original_path, modified_path)
    package_details = {"package_changed": bool(changed_parts), "changed_parts": changed_parts}
    original_preview = _extract_paras_fast(original_path, _DIFF_PARA_LIMIT)
    modified_preview = _extract_paras_fast(modified_path, _DIFF_PARA_LIMIT)
    preview_entries = _preview_entries(original_preview, modified_preview)
    total, changed, stream_examples = _stream_diff(original_path, modified_path)

    preview_changed = [entry for entry in preview_entries if entry["status"] != "unchanged"]
    if preview_changed and total <= _DIFF_PARA_LIMIT:
        return {
            **package_details,
            "total": total,
            "changed": len(preview_changed),
            "entries": preview_entries,
        }
    return {**package_details, "total": total, "changed": changed, "entries": stream_examples}


def _xml_tokens(source):
    """Compare expanded XML names, attributes and meaningful text, not bytes."""
    for event, element in _xml_events(source, ("start", "end")):
        if event == "start":
            yield event, element.tag, sorted(element.attrib.items())
        else:
            text = element.text or ""
            yield event, element.tag, text if text.strip() or element.tag == _TEXT else ""
            _release_element(element)


def _parts_equal(before, after, name):
    # Most unchanged parts are byte-identical. For edited XML, stop at the first
    # structural difference instead of canonicalizing two entire large trees.
    with before.open(name) as left, after.open(name) as right:
        while True:
            a, b = left.read(1024 * 1024), right.read(1024 * 1024)
            if a != b:
                break
            if not a:
                return True
    if not name.endswith((".xml", ".rels")):
        return False
    sentinel = object()
    with before.open(name) as left, after.open(name) as right:
        return all(a == b for a, b in zip_longest(
            _xml_tokens(left), _xml_tokens(right), fillvalue=sentinel,
        ))


def _changed_parts(original_path, modified_path):
    validate_package(original_path)
    validate_package(modified_path)
    with zipfile.ZipFile(original_path) as before, zipfile.ZipFile(modified_path) as after:
        names = {name for name in before.namelist() + after.namelist() if name.startswith("word/")}
        old, new = set(before.namelist()), set(after.namelist())
        return sorted(name for name in names if name not in old or name not in new
                      or not _parts_equal(before, after, name))
