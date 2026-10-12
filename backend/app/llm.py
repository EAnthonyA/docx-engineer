"""DeepSeek LLM client.

Generates raw Rust-hosted Rhai edit scripts via DeepSeek's OpenAI-compatible
chat completions. Config is read from the environment on every call.
"""

import logging
import os
import time

import httpx

# prompts.py owns the shared prompt contract (system prompts, fence stripping,
# clarifications block).
from .prompts import (
    _CLARIFY_SYSTEM,
    _RHAI_SCRIPT_SYSTEM,
    _clarifications_block,
    _strip_fences,
)

log = logging.getLogger("llm")

_DEEPSEEK_BASE_URL = os.environ.get(
    "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
).rstrip("/")


def generate_rust_script(instruction: str, doc_summary: str, clarifications: list | None = None) -> str | None:
    """Return a Rust-hosted Rhai edit script, or None when it is unsupported.

    The script can express data-dependent control flow but has no ambient I/O;
    the Rust worker exposes only a small, validated document-edit API.
    """
    parts = [f"DOCUMENT STRUCTURE:\n{doc_summary}", f"\nUSER INSTRUCTION:\n{instruction}"]
    block = _clarifications_block(clarifications)
    if block:
        parts.append(block)
    parts.append("\nReturn the Rhai program or UNSUPPORTED:")
    content = _strip_fences(_chat([
        {"role": "system", "content": _RHAI_SCRIPT_SYSTEM},
        {"role": "user", "content": "\n".join(parts)},
    ])).strip()
    return None if content == "UNSUPPORTED" else content


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

    for attempt in range(3):
        try:
            return _request_chat(api_key, model, messages, temperature)
        except (httpx.TransportError, RetryableResponseError):
            if attempt == 2:
                raise
            log.warning("Temporary LLM request failure; retry %d/2", attempt + 1)
            time.sleep(2 ** attempt)
    raise RuntimeError("LLM request attempts exhausted")


class RetryableResponseError(RuntimeError):
    pass


def _request_chat(api_key, model, messages, temperature):
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
        error_type = RetryableResponseError if resp.status_code in (408, 429) or resp.status_code >= 500 else RuntimeError
        raise error_type(
            f"DeepSeek API error {resp.status_code}: {resp.text[:300]}"
        )

    try:
        choice = resp.json()["choices"][0]
        content = choice["message"]["content"]
        if choice.get("finish_reason", "stop") != "stop":
            raise RetryableResponseError("LLM response did not finish normally; incomplete code was discarded")
        if not isinstance(content, str) or not content.strip():
            raise RetryableResponseError("LLM returned empty content")
        return content
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RetryableResponseError("LLM returned a malformed response") from exc


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
