"""Document editing helpers that preserve runs, relationships and embedded objects."""

import os
import re
import urllib.error
import urllib.parse
import urllib.request
from bisect import bisect_left, bisect_right
from copy import deepcopy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run

_TEXT_TAGS = {qn("w:t"), qn("w:tab"), qn("w:br"), qn("w:cr")}


def _runs(para):
    # Include hyperlinks, but do not edit runs in an embedded text box twice.
    for element in para._p.iter(qn("w:r")):
        parent = next(element.iterancestors(qn("w:p")), None)
        if parent is para._p:
            yield Run(element, para)


def _prune_empty_runs(para):
    # Tag removal leaves empty formatting shells. Release them paragraph by
    # paragraph so large documents do not retain all deleted tag XML.
    for run in list(_runs(para)):
        if all(child.tag == qn("w:rPr") for child in run._r):
            run._r.getparent().remove(run._r)


def _split_run(run, offset):
    """Keep the left half in place and return the right half, preserving XML."""
    if offset == 0:
        return run
    right = OxmlElement("w:r")
    right.attrib.update(run._r.attrib)
    if run._r.rPr is not None:
        right.append(deepcopy(run._r.rPr))
    position = 0
    for child in list(run._r):
        if child.tag == qn("w:rPr"):
            continue
        length = len(child.text or "") if child.tag == qn("w:t") else 0
        if child.tag in {qn("w:tab"), qn("w:cr")}:
            length = 1
        elif child.tag == qn("w:br"):
            length = 1 if child.get(qn("w:type"), "textWrapping") == "textWrapping" else 0
        if position >= offset:
            right.append(child)
        elif position + length > offset:
            tail = deepcopy(child)
            tail.text = (child.text or "")[offset - position:]
            child.text = (child.text or "")[:offset - position]
            child.set(qn("xml:space"), "preserve")
            tail.set(qn("xml:space"), "preserve")
            right.append(tail)
        position += length
    run._r.addnext(right)
    return Run(right, run._parent)


class _TextMap:
    """One run index per paragraph; edits proceed in descending text order."""

    def __init__(self, para):
        self.para = para
        self.runs, self.starts, self.ends = [], [], []
        texts = []
        position = 0
        for run in _runs(para):
            text = run.text
            if not text:
                continue
            self.runs.append(run)
            self.starts.append(position)
            position += len(text)
            self.ends.append(position)
            texts.append(text)
        self.text = "".join(texts)

    def select(self, start, end):
        if start == end:
            return []
        selected = []
        for index in range(bisect_right(self.ends, start), bisect_left(self.starts, end)):
            run = self.runs[index]
            lo = max(start - self.starts[index], 0)
            hi = min(end, self.ends[index]) - self.starts[index]
            if hi < len(run.text):
                _split_run(run, hi)
            selected.append(_split_run(run, lo))
        return selected

    def replace(self, start, end, text):
        if start == end:
            if not text:
                return
            if not self.runs:
                self.para.add_run(text)
                return
            index = min(bisect_right(self.ends, start), len(self.runs) - 1)
            anchor = _split_run(self.runs[index], start - self.starts[index])
            selected = []
        else:
            selected = self.select(start, end)
            anchor = selected[0]
        if text:
            element = OxmlElement("w:r")
            if anchor._r.rPr is not None:
                element.append(deepcopy(anchor._r.rPr))
            Run(element, self.para).text = text
            anchor._r.addprevious(element)
        for run in selected:
            # Keep drawings, field codes, bookmarks and relationship wrappers.
            for child in list(run._r):
                if child.tag in _TEXT_TAGS and not (
                    child.tag == qn("w:br") and child.get(qn("w:type"), "textWrapping") != "textWrapping"
                ):
                    run._r.remove(child)


class DocxTools:
    def replace_text(self, doc, old: str, new: str, *, locations="all") -> int:
        if not old:
            return 0
        return self.regex_replace(doc, re.escape(old), lambda _: new, locations=locations)

    def regex_replace(self, doc, pattern, repl, *, flags=0, locations="all") -> int:
        compiled = re.compile(pattern, flags)
        count = 0
        for para in self.iter_paragraphs(doc, locations=locations):
            mapped = _TextMap(para)
            matches = list(compiled.finditer(mapped.text))
            # Evaluate callables in document order, just like re.sub.
            edits = [(m.start(), m.end(), repl(m) if callable(repl) else m.expand(repl))
                     for m in matches]
            changed = False
            for start, end, replacement in reversed(edits):
                if replacement != mapped.text[start:end]:
                    mapped.replace(start, end, replacement)
                    count += 1
                    changed = True
            if changed:
                _prune_empty_runs(para)
        return count

    def format_tagged(self, doc, pattern, *, flags=0, locations="all",
                      bold=None, italic=None, underline=None, color=None, size_pt=None) -> int:
        compiled = re.compile(pattern, flags)
        if compiled.groups != 1:
            raise ValueError("format_tagged requires exactly one capture group")
        count = 0
        for para in self.iter_paragraphs(doc, locations=locations):
            mapped = _TextMap(para)
            matches = list(compiled.finditer(mapped.text))
            for match in reversed(matches):
                if match.start(1) < match.start() or match.end(1) > match.end():
                    raise ValueError("The capture group must participate inside the full match")
                mapped.replace(match.end(1), match.end(), "")
                for run in mapped.select(match.start(1), match.end(1)):
                    self.set_format(run, bold=bold, italic=italic, underline=underline,
                                    color=color, size_pt=size_pt)
                mapped.replace(match.start(), match.start(1), "")
                count += 1
            if matches:
                _prune_empty_runs(para)
        return count

    def iter_paragraphs(self, doc, *, locations="all"):
        """Visit each selected paragraph once, including nested header tables."""
        if locations not in {"all", "body", "tables", "headers_footers"}:
            raise ValueError(f"Unknown paragraph location: {locations}")
        if locations in {"all", "body", "tables"}:
            for element in doc.element.body.iter(qn("w:p")):
                in_table = next(element.iterancestors(qn("w:tbl")), None) is not None
                if locations == "body" and in_table:
                    continue
                if locations == "tables" and not in_table:
                    continue
                yield Paragraph(element, doc)
        if locations in {"all", "headers_footers"}:
            seen = set()
            # Existing related parts avoid materializing absent headers and
            # prevent linked sections from applying the same edit repeatedly.
            for rel in doc.part.rels.values():
                if rel.is_external or not rel.reltype.endswith(("/header", "/footer")):
                    continue
                part = rel.target_part
                if part.partname in seen:
                    continue
                seen.add(part.partname)
                for element in part.element.iter(qn("w:p")):
                    yield Paragraph(element, part)

    def delete_paragraphs(self, doc, predicate) -> int:
        count = 0
        paragraphs = iter(self.iter_paragraphs(doc, locations="body"))
        para = next(paragraphs, None)
        while para is not None:
            following = next(paragraphs, None)
            if predicate(para.text):
                para._p.getparent().remove(para._p)
                count += 1
            para = following
        return count

    def set_format(self, target, *, bold=None, italic=None, underline=None,
                   color=None, size_pt=None) -> None:
        runs = _runs(target) if isinstance(target, Paragraph) else [target]
        rgb = RGBColor.from_string(color.lstrip("#")) if color else None
        size = Pt(size_pt) if size_pt is not None else None
        for run in runs:
            if bold is not None:
                run.bold = bold
            if italic is not None:
                run.italic = italic
            if underline is not None:
                run.underline = underline
            if rgb is not None:
                run.font.color.rgb = rgb
            if size is not None:
                run.font.size = size

    def set_style(self, paragraph, name) -> None:
        try:
            paragraph.style = name
        except KeyError as exc:
            raise ValueError(f"Paragraph style does not exist: {name}") from exc

    def scrape(self, url, *, timeout=30) -> str:
        base = os.environ.get("SCRAPER_URL", "http://scraper:8000").rstrip("/")
        target = f"{base}/fetch?url={urllib.parse.quote(url, safe='')}"
        req = urllib.request.Request(target, headers={"User-Agent": "docx-engineer-scraper/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"Scrape failed with HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise RuntimeError(f"Scrape failed: {exc}") from exc
