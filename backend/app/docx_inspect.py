import json
import zipfile
from difflib import SequenceMatcher

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph as _DocxParagraph
from lxml import etree


def summarize(path: str) -> str:
    """Return a JSON string describing the document structure for the LLM prompt."""
    doc = Document(path)
    paras = []
    total = 0
    non_empty = 0
    for p in doc.element.body:
        if p.tag != qn("w:p"):
            continue
        para = _DocxParagraph(p, doc)
        total += 1
        text = para.text
        if text.strip():
            non_empty += 1
            if len(paras) < 50:
                paras.append({
                    "index": total - 1,
                    "style": para.style.name if para.style else "Normal",
                    "text_preview": text[:300],
                    "run_count": len(para.runs),
                })
        if total >= 2000:
            break

    tables = [
        {"index": i, "rows": len(t.rows), "cols": len(t.columns)}
        for i, t in enumerate(doc.tables[:10])
    ]

    return json.dumps({
        "total_paragraphs": total,
        "non_empty_paragraphs": non_empty,
        "sample_paragraphs": paras,
        "tables": tables,
    }, indent=2)


_DIFF_PARA_LIMIT = 50
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _extract_paras_fast(docx_path: str, limit: int) -> list:
    """Stream first `limit` paragraphs from docx without loading the full document into memory."""
    paras = []
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
                paras.append({"text": text, "style": "Normal", "runs": runs})
                el.clear()
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
    """Compare first _DIFF_PARA_LIMIT paragraphs of two docx files using fast streaming XML parse."""
    orig = _extract_paras_fast(original_path, _DIFF_PARA_LIMIT)
    mod = _extract_paras_fast(modified_path, _DIFF_PARA_LIMIT)

    matcher = SequenceMatcher(None, [p["text"] for p in orig],
                              [p["text"] for p in mod], autojunk=True)
    entries = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            entries += [_entry("unchanged", orig[i], mod[j])
                        for i, j in zip(range(i1, i2), range(j1, j2))]
        elif tag == "delete":
            entries += [_entry("removed", orig[i], None) for i in range(i1, i2)]
        elif tag == "insert":
            entries += [_entry("added", None, mod[j]) for j in range(j1, j2)]
        else:  # replace
            entries += _replace_entries(orig[i1:i2], mod[j1:j2])

    changed = sum(1 for e in entries if e["status"] != "unchanged")
    return {"total": len(entries), "changed": changed, "entries": entries}
