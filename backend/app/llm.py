"""DeepSeek LLM client.

Generates python-docx edit scripts via DeepSeek's OpenAI-compatible chat
completions. Config is read from the environment on every call.
"""

import logging
import os

import httpx

# prompts.py owns the shared prompt contract (system prompts, fence stripping,
# clarifications block).
from .prompts import _CLARIFY_SYSTEM, _SYSTEM_PROMPT, _clarifications_block, _strip_fences

log = logging.getLogger("llm")

_DEEPSEEK_BASE_URL = os.environ.get(
    "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
).rstrip("/")


def _build_user_prompt(instruction, doc_summary, history, clarifications=None) -> str:
    parts = [
        f"DOCUMENT STRUCTURE:\n{doc_summary}",
        f"\nUSER INSTRUCTION:\n{instruction}",
    ]
    block = _clarifications_block(clarifications)
    if block:
        parts.append(block)
    if history:
        parts.append("\nPREVIOUS ATTEMPTS — learn from these failures:")
        for i, (script, outcome) in enumerate(history, 1):
            parts.append(f"\nAttempt {i} script:\n{script}")
            parts.append(f"Attempt {i} outcome: {outcome}")
    parts.append("\nWrite the transform function now:")
    return "\n".join(parts)


def generate_script(instruction: str, doc_summary: str, history: list, clarifications: list | None = None) -> str:
    """Return raw Python source for the edit script."""
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    prompt = _build_user_prompt(instruction, doc_summary, history, clarifications)

    log.info(
        "DeepSeek request — model=%s attempt=%d instruction=%r",
        model,
        len(history) + 1,
        instruction,
    )
    log.debug("DeepSeek prompt:\n%s", prompt)

    content = _chat([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ])
    script = _strip_fences(content)

    log.debug("DeepSeek response — %d chars", len(script))
    log.debug("DeepSeek script:\n%s", script)
    return script


def ask_clarification(instruction: str, doc_summary: str, clarifications: list | None = None) -> str | None:
    """Return a clarifying question if the instruction is ambiguous, else None."""
    prompt = _build_clarify_prompt(instruction, doc_summary, clarifications)
    log.info("DeepSeek clarification check — instruction=%r", instruction)

    content = _chat([
        {"role": "system", "content": _CLARIFY_SYSTEM},
        {"role": "user", "content": prompt},
    ])
    return _parse_clarify(content)


def _chat(messages: list[dict], temperature: float = 0.0) -> str:
    """One DeepSeek chat completion; returns the assistant text content."""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")

    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")

    resp = httpx.post(
        f"{_DEEPSEEK_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        },
        timeout=120.0,
    )

    if resp.status_code >= 400:
        log.error("DeepSeek API error %d: %s", resp.status_code, resp.text[:1000])
        raise RuntimeError(
            f"DeepSeek API error {resp.status_code}: {resp.text[:300]}"
        )

    return resp.json()["choices"][0]["message"]["content"]


def _build_clarify_prompt(instruction: str, doc_summary: str, clarifications: list | None) -> str:
    parts = [
        f"DOCUMENT STRUCTURE:\n{doc_summary}",
        f"\nUSER INSTRUCTION:\n{instruction}",
    ]
    block = _clarifications_block(clarifications)
    if block:
        parts.append(block)
    parts.append("\nReply with CLEAR, or ask your question(s):")
    return "\n".join(parts)


def _parse_clarify(content: str) -> str | None:
    text = _strip_fences(content).strip()
    if text.upper().replace(".", "").strip() == "CLEAR":
        return None
    return text
