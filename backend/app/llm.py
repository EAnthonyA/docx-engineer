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
from .gemini import _SYSTEM_PROMPT, _strip_fences, generate_script as _generate_gemini

log = logging.getLogger("llm")

_DEEPSEEK_BASE_URL = os.environ.get(
    "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
).rstrip("/")


def _build_user_prompt(instruction: str, doc_summary: str, history: list) -> str:
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
    return "\n".join(parts)


def generate_script(instruction: str, doc_summary: str, history: list) -> str:
    """Dispatch to the configured provider and return raw Python source."""
    provider = os.environ.get("AI_PROVIDER", "deepseek").strip().lower()

    if provider == "deepseek":
        return _generate_deepseek(instruction, doc_summary, history)
    if provider == "gemini":
        return _generate_gemini(instruction, doc_summary, history)

    raise ValueError(
        f"Unknown AI_PROVIDER: {provider!r} (expected 'deepseek' or 'gemini')"
    )


def _generate_deepseek(instruction: str, doc_summary: str, history: list) -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")

    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    prompt = _build_user_prompt(instruction, doc_summary, history)

    log.info(
        "DeepSeek request — model=%s attempt=%d instruction=%r",
        model,
        len(history) + 1,
        instruction,
    )
    log.debug("DeepSeek prompt:\n%s", prompt)

    resp = httpx.post(
        f"{_DEEPSEEK_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "stream": False,
        },
        timeout=120.0,
    )

    if resp.status_code >= 400:
        log.error("DeepSeek API error %d: %s", resp.status_code, resp.text[:1000])
        raise RuntimeError(
            f"DeepSeek API error {resp.status_code}: {resp.text[:300]}"
        )

    data = resp.json()
    script = _strip_fences(data["choices"][0]["message"]["content"])

    log.debug("DeepSeek response — %d chars", len(script))
    log.debug("DeepSeek script:\n%s", script)
    return script
