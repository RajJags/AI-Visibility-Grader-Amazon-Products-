"""
OpenRouterClient — free models via openrouter.ai (OpenAI-compatible).

Free models have a `:free` suffix and never expire — they just rate-limit.
No credit card required. Sign up at https://openrouter.ai and create an API key.
"""

from __future__ import annotations
import os
from openai import AsyncOpenAI
from .base import BaseLLMClient

# All permanently free on OpenRouter (`:free` suffix = no credits needed).
OPENROUTER_FREE_MODELS = [
    "meta-llama/llama-3.1-8b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "google/gemma-2-9b-it:free",
    "qwen/qwen-2-7b-instruct:free",
]


class OpenRouterClient(BaseLLMClient):
    def __init__(self, models: list[str] | None = None) -> None:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={"HTTP-Referer": "https://ai-visibility-grader.local"},
        )
        self._models = models or OPENROUTER_FREE_MODELS

    async def query(self, prompt: str, system: str = "") -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        last_error: Exception | None = None
        for model in self._models:
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=1024,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                last_error = exc
                msg = str(exc).lower()
                if "invalid_api_key" in msg or "401" in msg:
                    raise
                continue

        raise RuntimeError(f"All OpenRouter free models exhausted. Last: {last_error}")
