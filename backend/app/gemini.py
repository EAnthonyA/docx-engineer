import os
import re

import google.generativeai as genai

_SYSTEM_PROMPT = """\
You are a Python code generator for .docx manipulation.

OUTPUT FORMAT: raw Python only — no markdown fences, no explanation, no preamble.

RULES:
1. Emit exactly ONE function with this exact signature:
       def transform(input_path: str, output_path: str) -> None:
2. Import ONLY from the `docx` package (python-docx).
   Allowed: `from docx import Document`, `from docx.shared import ...`,
   `from docx.enum.text import ...`, `from docx.oxml.ns import qn`,
   `from docx.oxml import OxmlElement`, and other `docx.*` submodules.
3. Read the document from input_path; write the result to output_path.
4. Do NOT use: os, sys, subprocess, socket, shutil, open(), eval, exec, requests,
   or any library other than docx.
5. Handle edge cases gracefully (empty paragraphs, missing runs, None attributes).
6. The function must be self-contained and complete.\
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

    response = _model().generate_content(prompt)
    return _strip_fences(response.text)
