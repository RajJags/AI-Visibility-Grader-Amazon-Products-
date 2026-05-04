"""GroqClient -- circuit breaker + rate-limit retry."""
from __future__ import annotations
import asyncio, os, re
from openai import AsyncOpenAI, RateLimitError
from .base import BaseLLMClient
from . import _health as health

GROQ_MODELS = [
    "llama-3.1-8b-instant",
    "openai/gpt-oss-20b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
]
_RETRY_RE = re.compile(r"try again in ([\d.]+)s", re.IGNORECASE)

def _parse_retry_wait(err):
    m = _RETRY_RE.search(str(err))
    return min(float(m.group(1)) + 0.5, 8.0) if m else 3.0

class GroqClient(BaseLLMClient):
    def __init__(self, models=None):
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set")
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        self._models = models or GROQ_MODELS

    async def query(self, prompt, system="", max_tokens=1024):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        ordered = health.best_first(self._models)
        last_error = None
        for model in ordered:
            for attempt in range(2):
                try:
                    resp = await self._client.chat.completions.create(
                        model=model, messages=messages, max_tokens=max_tokens,
                    )
                    health.mark_ok(model)
                    return resp.choices[0].message.content or ""
                except RateLimitError as exc:
                    last_error = exc
                    health.mark_failed(model)
                    if attempt == 0:
                        await asyncio.sleep(_parse_retry_wait(exc))
                        continue
                    break
                except Exception as exc:
                    last_error = exc
                    msg = str(exc).lower()
                    if "invalid_api_key" in msg or "401" in msg:
                        raise
                    health.mark_failed(model)
                    break
        raise RuntimeError(f"All Groq models exhausted. Last: {last_error}")
