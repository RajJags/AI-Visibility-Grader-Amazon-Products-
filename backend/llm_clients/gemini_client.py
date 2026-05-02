"""
GeminiClient — Google Gemini free tier.

Walks through GEMINI_MODELS in order. gemini-1.5-flash-8b has the highest
free RPD (requests per day) so it is tried first.
"""

from __future__ import annotations
import os
import google.generativeai as genai
from .base import BaseLLMClient

# Tried in order: highest free quota first.
GEMINI_MODELS = [
    "gemini-1.5-flash-8b",   # 1 500 RPD free  — smallest, most available
    "gemini-1.5-flash",      # 1 500 RPD free  — better quality
    "gemini-2.0-flash",      # 1 500 RPD free  — newest
    "gemini-2.0-flash-lite", # higher RPD      — lightweight alias
]


class GeminiClient(BaseLLMClient):
    def __init__(self) -> None:
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY not set")
        genai.configure(api_key=api_key)
        self._models = GEMINI_MODELS

    async def query(self, prompt: str, system: str = "") -> str:
        import asyncio
        full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt

        last_error: Exception | None = None
        for model_name in self._models:
            try:
                model = genai.GenerativeModel(model_name)
                response = await asyncio.to_thread(model.generate_content, full_prompt)
                return response.text or ""
            except Exception as exc:
                last_error = exc
                msg = str(exc).lower()
                # Auth errors → stop immediately
                if "api_key" in msg or "403" in msg or "permission" in msg:
                    raise
                # Quota / not-found → try next model
                continue

        raise RuntimeError(f"All Gemini models exhausted. Last error: {last_error}")
