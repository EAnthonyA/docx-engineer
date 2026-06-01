import logging
import os
import re

import google.generativeai as genai

log = logging.getLogger("gemini")

_SYSTEM_PROMPT = """\
You are a Python code generator for .docx manipulation.

OUTPUT FORMAT: raw Python only — no markdown fences, no explanation, no preamble.

CONTRACT:
Emit exactly ONE function with this exact signature:
    def edit(doc, tools) -> None:

- `doc` is a loaded python-docx Document. Do NOT call Document() or doc.save() — the sandbox handles that.
- `tools` is a DocxTools helper with the API documented below. Use it for all common operations.
- No imports are needed for most edits. If you must import, only `from docx import ...` is allowed.
- Do NOT use: os, sys, subprocess, socket, shutil, open(), eval, exec, requests.
- Handle edge cases gracefully (empty paragraphs, missing runs, None values).

TOOLS API:

tools.replace_text(doc, old, new, *, locations="all") -> int
    Literal replace of `old` with `new` across all paragraphs.
    Handles matches that span run boundaries (python-docx may split text across runs).
    locations: "all" | "body" | "tables" | "headers_footers"
    Returns count of replacements.

tools.regex_replace(doc, pattern, repl, *, flags=0, locations="all") -> int
    Regex replace. repl may be a string or callable(match) -> str.
    Same run-boundary handling as replace_text. Returns count.

tools.format_tagged(doc, pattern, *, flags=0, locations="all", bold=None, italic=None,
                    underline=None, color=None, size_pt=None) -> int
    Find regex matches (pattern MUST have exactly one capture group).
    Strips the full match, keeps group(1), applies the given formatting to group(1).
    Use this whenever you need to REMOVE markup/tags AND FORMAT the content inside.
    Run-boundary-aware. Returns count of replacements.

tools.iter_paragraphs(doc, *, locations="all")
    Generator yielding every paragraph (body + table cells + headers/footers).
    Use for reading/inspecting paragraphs one at a time.

tools.delete_paragraphs(doc, predicate) -> int
    Remove paragraphs where predicate(paragraph.text) is truthy.
    Returns count removed.

tools.set_format(target, *, bold=None, italic=None, underline=None, color=None, size_pt=None)
    Apply run-level formatting. target = paragraph (applies to all runs) or a single run.
    color: hex string like "FF0000". size_pt: number (e.g. 12).

tools.set_style(paragraph, name)
    Set paragraph style by name. No-op if style doesn't exist.

EXAMPLES:

# Replace a placeholder everywhere in the document
def edit(doc, tools):
    tools.replace_text(doc, "{{name}}", "Alice")

# Bold all paragraphs that contain "IMPORTANT"
def edit(doc, tools):
    for para in tools.iter_paragraphs(doc):
        if "IMPORTANT" in para.text:
            tools.set_format(para, bold=True)

# Remove all paragraphs starting with "TODO:"
def edit(doc, tools):
    tools.delete_paragraphs(doc, lambda t: t.startswith("TODO:"))

# Regex replace dates formatted DD.MM.YYYY with YYYY-MM-DD
def edit(doc, tools):
    import re
    tools.regex_replace(doc, r"(\\d{2})\\.(\\d{2})\\.(\\d{4})", r"\\3-\\2-\\1")

# Bold text between <B>…<D> tags and remove the tags
def edit(doc, tools):
    tools.format_tagged(doc, r"<B>(.*?)<D>", bold=True)

RULES:
- Prefer tools methods. They are single-pass, fast, and run-boundary-safe.
- For tag→format tasks (remove markup, style content inside), ALWAYS use tools.format_tagged. Never write your own run loops.
- If you use tools.iter_paragraphs, never accumulate all paragraphs into a list — process one at a time.
- Do NOT write character-by-character or per-run loops — use tools.replace_text, tools.regex_replace, or tools.format_tagged instead.
- The function must be self-contained and complete.\
"""


def _model():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    genai.configure(api_key=api_key)
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    return genai.GenerativeModel(model_name, system_instruction=_SYSTEM_PROMPT)


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:python)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_script(instruction: str, doc_summary: str, history: list) -> str:
    """Call Gemini to produce a transform() function. Returns raw Python source."""
    parts = [
        f"DOCUMENT STRUCTURE:\n{doc_summary}",
        f"\nUSER INSTRUCTION:\n{instruction}",
    ]

    if history:
        parts.append("\nPREVIOUS ATTEMPTS — learn from these failures:")
        for i, (script, outcome) in enumerate(history, 1):
            parts.append(f"\nAttempt {i} script:\n{script}")
            parts.append(f"Attempt {i} outcome: {outcome}")

    parts.append("\nWrite the transform function now:")
    prompt = "\n".join(parts)

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    log.info("Gemini request — model=%s attempt=%d instruction=%r", model_name, len(history) + 1, instruction)
    log.debug("Gemini prompt:\n%s", prompt)

    response = _model().generate_content(prompt)
    script = _strip_fences(response.text)

    log.debug("Gemini response — %d chars", len(script))
    log.debug("Gemini script:\n%s", script)

    return script
