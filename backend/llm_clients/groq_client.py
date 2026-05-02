"""
GroqClient — free-tier inference via Groq's OpenAI-compatible API.

Model list matches exactly what's available on a standard Groq free project
as of May 2026. Ordered small → large (best availability → best quality).
"""

from __future__ import annotations
import os
from openai import AsyncOpenAI
from .base import BaseLLMClient

GROQ_MODELS = [
    "llama-3.1-8b-instant",                      # 8 B  — fastest, highest quota
    "openai/gpt-oss-20b",                         # 20 B — OpenAI open-weights
    "meta-llama/llama-4-scout-17b-16e-instruct",  # 17 B — Llama 4, MoE
    "qwen/qwen3-32b",                             # 32 B — strong reasoning
    "llama-3.3-70b-versatile",                    # 70 B — best quality
    "openai/gpt-oss-120b",                        # 120 B — largest available
]


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

        raise RuntimeError(f"All Groq models exhausted. Last error: {last_error}")
