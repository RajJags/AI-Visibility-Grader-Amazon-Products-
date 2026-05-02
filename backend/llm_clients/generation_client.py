"""
GenerationClient — exhaustive free-tier fallback chain with concurrency cap.

A module-level semaphore (shared with llm_runner) caps total concurrent LLM
calls at 4 so we don't burst through Groq's 6,000 TPM free-tier limit.

Order: Groq → OpenRouter → Gemini
"""

from __future__ import annotations
import asyncio
from .groq_client import GroqClient
from .openrouter_client import OpenRouterClient
from .gemini_client import GeminiClient
from .base import BaseLLMClient

# Shared cap: no more than 4 LLM calls in flight at once across the whole app
_SEM = asyncio.Semaphore(4)


class GenerationClient(BaseLLMClient):
    def __init__(self) -> None:
        self._groq: GroqClient | None = None
        self._openrouter: OpenRouterClient | None = None
        self._gemini: GeminiClient | None = None

    async def query(self, prompt: str, system: str = "") -> str:
        async with _SEM:
            return await self._query_inner(prompt, system)

    async def _query_inner(self, prompt: str, system: str) -> str:
        errors: list[str] = []

        try:
            if self._groq is None:
                self._groq = GroqClient()
            return await self._groq.query(prompt, system=system)
        except Exception as e:
            errors.append(f"Groq: {e}")

        try:
            if self._openrouter is None:
                self._openrouter = OpenRouterClient()
            return await self._openrouter.query(prompt, system=system)
        except Exception as e:
            errors.append(f"OpenRouter: {e}")

        try:
            if self._gemini is None:
                self._gemini = GeminiClient()
            return await self._gemini.query(prompt, system=system)
        except Exception as e:
            errors.append(f"Gemini: {e}")

        raise RuntimeError("All free LLM providers exhausted:\n" + "\n".join(errors))
