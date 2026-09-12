"""Model-agnostic LLM client.

One interface, multiple providers. Choose via the AI_PROVIDER env var:

  - ``deepseek`` (default) — OpenAI-compatible chat completions over httpx
  - ``gemini``             — Google Generative AI SDK

Provider config is read from the environment on every call, so the provider can
be swapped without a restart.
"""

import logging
import os

import httpx

# The Gemini module owns the shared system prompt and fence stripping so there is
# exactly one copy of the prompt contract across providers.
from .gemini import (
    _CLARIFY_SYSTEM,
    _SYSTEM_PROMPT,
    _strip_fences,
    ask_clarification as _ask_gemini,
    generate_script as _generate_gemini,
)

log = logging.getLogger("llm")

_DEEPSEEK_BASE_URL = os.environ.get(
    "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
).rstrip("/")


def _clarifications_block(clarifications) -> str:
    if not clarifications:
        return ""
    lines = ["\nCLARIFICATIONS (already asked and answered):"]
    for q, a in clarifications:
        lines.append(f"Q: {q}")
        lines.append(f"A: {a}")
    return "\n".join(lines)


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
    """Dispatch to the configured provider and return raw Python source."""
    provider = os.environ.get("AI_PROVIDER", "deepseek").strip().lower()

    if provider == "deepseek":
        return _generate_deepseek(instruction, doc_summary, history, clarifications)
    if provider == "gemini":
        return _generate_gemini(instruction, doc_summary, history, clarifications)

    raise ValueError(
        f"Unknown AI_PROVIDER: {provider!r} (expected 'deepseek' or 'gemini')"
    )


def ask_clarification(instruction: str, doc_summary: str, clarifications: list | None = None) -> str | None:
    """Return a clarifying question if the instruction is ambiguous, else None."""
    provider = os.environ.get("AI_PROVIDER", "deepseek").strip().lower()

    if provider == "deepseek":
        return _ask_deepseek(instruction, doc_summary, clarifications)
    if provider == "gemini":
        return _ask_gemini(instruction, doc_summary, clarifications)

    raise ValueError(
        f"Unknown AI_PROVIDER: {provider!r} (expected 'deepseek' or 'gemini')"
    )


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


def _generate_deepseek(instruction: str, doc_summary: str, history: list, clarifications: list | None) -> str:
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


def _ask_deepseek(instruction: str, doc_summary: str, clarifications: list | None) -> str | None:
    prompt = _build_clarify_prompt(instruction, doc_summary, clarifications)
    log.info("DeepSeek clarification check — instruction=%r", instruction)

    content = _chat([
        {"role": "system", "content": _CLARIFY_SYSTEM},
        {"role": "user", "content": prompt},
    ])
    return _parse_clarify(content)
