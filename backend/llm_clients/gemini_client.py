"""
GeminiClient - Google Gemini free tier with circuit breaker.

Walks GEMINI_MODELS in order (highest free-quota first).
Failed models are deprioritised via the shared health tracker.
"""

from __future__ import annotations
import asyncio, os
import google.generativeai as genai
from .base import BaseLLMClient
from . import _health as health

GEMINI_MODELS = [
    "gemini-1.5-flash-8b",   # 1500 RPD free - smallest, most available
    "gemini-1.5-flash",      # 1500 RPD free - better quality
    "gemini-2.0-flash",      # 1500 RPD free - newest
    "gemini-2.0-flash-lite", # higher RPD    - lightweight alias
]


class GeminiClient(BaseLLMClient):
    def __init__(self) -> None:
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY not set")
        genai.configure(api_key=api_key)
        self._models = GEMINI_MODELS

    async def query(self, prompt: str, system: str = "", max_tokens: int = 1024) -> str:
        full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt
        ordered = health.best_first(self._models)

        last_error: Exception | None = None
        for model_name in ordered:
            try:
                model = genai.GenerativeModel(
                    model_name,
                    generation_config={"temperature": 0, "max_output_tokens": max_tokens},
                )
                response = await asyncio.to_thread(model.generate_content, full_prompt)
                health.mark_ok(model_name)
                return response.text or ""
            except Exception as exc:
                last_error = exc
                msg = str(exc).lower()
                if "api_key" in msg or "403" in msg or "permission" in msg:
                    raise
                health.mark_failed(model_name)
                continue

        raise RuntimeError(f"All Gemini models exhausted. Last: {last_error}")
