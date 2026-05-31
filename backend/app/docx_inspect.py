import json
from difflib import SequenceMatcher

from docx import Document


def _run_dict(run) -> dict:
    return {
        "text": run.text,
        "bold": bool(run.bold),
        "italic": bool(run.italic),
        "underline": bool(run.underline),
    }


def _para_dict(para) -> dict:
    runs = [_run_dict(r) for r in para.runs if r.text]
    return {
        "text": para.text,
        "style": para.style.name if para.style else "Normal",
        "runs": runs,
    }


def summarize(path: str) -> str:
    """Return a JSON string describing the document structure for the LLM prompt."""
    doc = Document(path)
    paras = []
    for i, p in enumerate(doc.paragraphs):
        if p.text.strip():
            paras.append({
                "index": i,
                "style": p.style.name if p.style else "Normal",
                "text_preview": p.text[:300],
                "run_count": len(p.runs),
            })
        if len(paras) >= 50:
            break

    tables = [
        {"index": i, "rows": len(t.rows), "cols": len(t.columns)}
        for i, t in enumerate(doc.tables[:10])
    ]

    return json.dumps({
        "total_paragraphs": len(doc.paragraphs),
        "non_empty_paragraphs": sum(1 for p in doc.paragraphs if p.text.strip()),
        "sample_paragraphs": paras,
        "tables": tables,
    }, indent=2)


def compute_diff(original_path: str, modified_path: str) -> dict:
    """Compare two docx files paragraph by paragraph. Returns diff suitable for JSON serialization."""
    orig_paras = [_para_dict(p) for p in Document(original_path).paragraphs]
    mod_paras = [_para_dict(p) for p in Document(modified_path).paragraphs]

    orig_texts = [p["text"] for p in orig_paras]
    mod_texts = [p["text"] for p in mod_paras]

    matcher = SequenceMatcher(None, orig_texts, mod_texts, autojunk=False)
    entries = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                entries.append({"status": "unchanged", "before": orig_paras[i], "after": mod_paras[j]})

        elif tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                bi = i1 + k if i1 + k < i2 else None
                aj = j1 + k if j1 + k < j2 else None
                before = orig_paras[bi] if bi is not None else None
                after = mod_paras[aj] if aj is not None else None

                if before is not None and after is not None:
                    status = "unchanged" if before == after else "changed"
                elif before is not None:
                    status = "removed"
                else:
                    status = "added"
                entries.append({"status": status, "before": before, "after": after})

        elif tag == "delete":
            for i in range(i1, i2):
                entries.append({"status": "removed", "before": orig_paras[i], "after": None})

        elif tag == "insert":
            for j in range(j1, j2):
                entries.append({"status": "added", "before": None, "after": mod_paras[j]})

    changed_count = sum(1 for e in entries if e["status"] != "unchanged")
    return {
        "total": len(entries),
        "changed": changed_count,
        "entries": entries,
    }
