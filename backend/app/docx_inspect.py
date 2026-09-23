import json
import zipfile
from difflib import SequenceMatcher
from itertools import zip_longest

from lxml import etree


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_P = f"{{{_W}}}p"
_BODY = f"{{{_W}}}body"


def _paragraph_style_names(docx_path: str) -> dict[str, str]:
    """Read paragraph style IDs without building a python-docx document tree."""
    names: dict[str, str] = {}
    try:
        with zipfile.ZipFile(docx_path) as z:
            with z.open("word/styles.xml") as f:
                for _, style in etree.iterparse(
                    f, events=("end",), tag=f"{{{_W}}}style"
                ):
                    if style.get(f"{{{_W}}}type") == "paragraph":
                        style_id = style.get(f"{{{_W}}}styleId")
                        name = style.find(f"{{{_W}}}name")
                        if style_id and name is not None:
                            names[style_id] = name.get(f"{{{_W}}}val", style_id)
                    style.clear()
    except KeyError:
        # styles.xml is optional in a valid DOCX.  The summary still works
        # without it and reports the standard style name below.
        pass
    return names


def summarize(path: str) -> str:
    """Return a bounded document summary without loading the whole DOCX tree.

    ``python-docx.Document(path)`` constructs a Python object for every XML
    element.  A visually ordinary, long Word document can therefore consume
    multiple gigabytes of memory before this lightweight preflight step has
    even reached the sandbox.  This parser deliberately scans only the first
    2,000 top-level body paragraphs and immediately releases parsed XML.
    """
    style_names = _paragraph_style_names(path)
    paras = []
    total = 0
    non_empty = 0
    with zipfile.ZipFile(path) as z:
        with z.open("word/document.xml") as f:
            for _, para in etree.iterparse(f, events=("end",), tag=_P):
                parent = para.getparent()
                # Match the old ``doc.element.body`` behaviour: text inside
                # tables is not counted in this compact body sample.
                if parent is not None and parent.tag == _BODY:
                    total += 1
                    text = "".join(
                        (node.text or "")
                        for node in para.iterfind(f".//{{{_W}}}t")
                    )
                    if text.strip():
                        non_empty += 1
                        if len(paras) < 50:
                            ppr = para.find(f"{{{_W}}}pPr")
                            style = (
                                ppr.find(f"{{{_W}}}pStyle")
                                if ppr is not None else None
                            )
                            style_id = (
                                style.get(f"{{{_W}}}val")
                                if style is not None else None
                            )
                            paras.append({
                                "index": total - 1,
                                "style": style_names.get(style_id, style_id or "Normal"),
                                "text_preview": text[:300],
                                "run_count": len(para.findall(f"./{{{_W}}}r")),
                            })
                    if total >= 2000:
                        break

                # ``iterparse`` otherwise retains prior siblings, eventually
                # recreating the memory profile of a full XML tree.
                para.clear()
                if parent is not None:
                    while para.getprevious() is not None:
                        del parent[0]

    return json.dumps({
        "total_paragraphs": total,
        "non_empty_paragraphs": non_empty,
        "sample_paragraphs": paras,
        # Table dimensions were never needed by script generation and
        # collecting them required retaining entire table trees.  Preserve
        # the prompt field for compatibility while keeping preflight bounded.
        "tables": [],
    }, indent=2)


_DIFF_PARA_LIMIT = 50
def _iter_paras_fast(docx_path: str):
    """Yield document paragraphs while keeping the XML parser memory-bounded."""
    with zipfile.ZipFile(docx_path) as z:
        with z.open("word/document.xml") as f:
            for _, el in etree.iterparse(f, events=("end",), tag=f"{{{_W}}}p"):
                runs = []
                for r in el.findall(f".//{{{_W}}}r"):
                    rpr = r.find(f"{{{_W}}}rPr")
                    t_el = r.find(f"{{{_W}}}t")
                    t = (t_el.text or "") if t_el is not None else ""
                    if t:
                        runs.append({
                            "text": t,
                            "bold": rpr is not None and rpr.find(f"{{{_W}}}b") is not None,
                            "italic": rpr is not None and rpr.find(f"{{{_W}}}i") is not None,
                            "underline": rpr is not None and rpr.find(f"{{{_W}}}u") is not None,
                        })
                text = "".join(r["text"] for r in runs)
                yield {"text": text, "style": "Normal", "runs": runs}
                parent = el.getparent()
                el.clear()
                if parent is not None:
                    while el.getprevious() is not None:
                        del parent[0]


def _extract_paras_fast(docx_path: str, limit: int) -> list:
    """Return at most `limit` streamed paragraphs for small preview diffs."""
    paras = []
    for para in _iter_paras_fast(docx_path):
        paras.append(para)
        if len(paras) >= limit:
            break
    return paras


def _entry(status: str, before, after) -> dict:
    return {"status": status, "before": before, "after": after}


def _replace_entries(befores: list, afters: list) -> list:
    """Pair up replaced paragraphs; the longer side's tail becomes added/removed."""
    out = []
    for k in range(max(len(befores), len(afters))):
        before = befores[k] if k < len(befores) else None
        after = afters[k] if k < len(afters) else None
        if before is not None and after is not None:
            status = "unchanged" if before == after else "changed"
        else:
            status = "removed" if before is not None else "added"
        out.append(_entry(status, before, after))
    return out


def compute_diff(original_path: str, modified_path: str) -> dict:
    """Compare the entire document in a bounded-memory streaming pass.

    The old implementation compared only the first 50 paragraphs.  Valid
    edits later in a long document were then treated as "no changes" and
    retried until failure.  Keep only 50 changed examples for the browser,
    while counting every changed paragraph so result validation is global.
    """
    # Preserve a properly aligned preview for the common small-document case.
    # SequenceMatcher is deliberately limited to 50 entries; the full scan
    # below never accumulates document content.
    orig_preview = _extract_paras_fast(original_path, _DIFF_PARA_LIMIT)
    mod_preview = _extract_paras_fast(modified_path, _DIFF_PARA_LIMIT)
    preview_entries = []
    matcher = SequenceMatcher(None, [p["text"] for p in orig_preview],
                              [p["text"] for p in mod_preview], autojunk=True)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            preview_entries += [_entry("unchanged", orig_preview[i], mod_preview[j])
                                for i, j in zip(range(i1, i2), range(j1, j2))]
        elif tag == "delete":
            preview_entries += [_entry("removed", orig_preview[i], None) for i in range(i1, i2)]
        elif tag == "insert":
            preview_entries += [_entry("added", None, mod_preview[j]) for j in range(j1, j2)]
        else:
            preview_entries += _replace_entries(orig_preview[i1:i2], mod_preview[j1:j2])

    late_change_examples = []
    total = 0
    changed = 0
    sentinel = object()
    for before, after in zip_longest(
        _iter_paras_fast(original_path), _iter_paras_fast(modified_path),
        fillvalue=sentinel,
    ):
        total += 1
        if before is sentinel:
            status, before, after = "added", None, after
        elif after is sentinel:
            status, before, after = "removed", before, None
        else:
            status = "unchanged" if before == after else "changed"

        if status != "unchanged":
            changed += 1
            if len(late_change_examples) < _DIFF_PARA_LIMIT:
                late_change_examples.append(_entry(status, before, after))

    preview_changed = any(entry["status"] != "unchanged" for entry in preview_entries)
    # For a small document the bounded SequenceMatcher is fully aligned and
    # therefore gives precise add/remove counts. Long documents use the
    # whole-file scan so a change beyond the first preview window is never
    # misclassified as a no-op.
    if preview_changed and total <= _DIFF_PARA_LIMIT:
        preview_changed_count = sum(
            entry["status"] != "unchanged" for entry in preview_entries
        )
        return {"total": total, "changed": preview_changed_count, "entries": preview_entries}
    return {"total": total, "changed": changed, "entries": late_change_examples}
