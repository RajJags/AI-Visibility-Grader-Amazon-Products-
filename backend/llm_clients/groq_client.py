"""
GroqClient — free-tier Groq inference with rate-limit retry.

Walks GROQ_MODELS in order. On a 429 TPM error it waits the suggested
retry delay (capped at 10 s) and retries the same model once before
moving on. This prevents a 1-second rate limit from wasting the whole
model slot.
"""

from __future__ import annotations
import asyncio, os, re
from openai import AsyncOpenAI, RateLimitError
from .base import BaseLLMClient

GROQ_MODELS = [
    "llama-3.1-8b-instant",
    "openai/gpt-oss-20b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
]

_RETRY_RE = re.compile(r"try again in ([\d.]+)s", re.IGNORECASE)


def _parse_retry_wait(err: Exception) -> float:
    """Extract suggested wait from Groq 429 message, default 3 s."""
    m = _RETRY_RE.search(str(err))
    return min(float(m.group(1)) + 0.5, 10.0) if m else 3.0


class GroqClient(BaseLLMClient):
    def __init__(self, models: list[str] | None = None) -> None:
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set")
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        self._models = models or GROQ_MODELS

    async def query(self, prompt: str, system: str = "") -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        last_error: Exception | None = None
        for model in self._models:
            for attempt in range(2):   # 1 retry per model on rate limit
                try:
                    resp = await self._client.chat.completions.create(
                        model=model, messages=messages, max_tokens=1024,
                    )
                    return resp.choices[0].message.content or ""

                except RateLimitError as exc:
                    last_error = exc
                    if attempt == 0:
                        wait = _parse_retry_wait(exc)
                        await asyncio.sleep(wait)
                        continue      # retry same model
                    break             # give up on this model

                except Exception as exc:
                    last_error = exc
                    msg = str(exc).lower()
                    if "invalid_api_key" in msg or "401" in msg:
                        raise
                    break             # move to next model

        raise RuntimeError(f"All Groq models exhausted. Last: {last_error}")
