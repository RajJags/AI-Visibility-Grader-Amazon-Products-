"""
GenerationClient — exhaustive free-tier fallback chain.

Order: Groq (7 models) → OpenRouter (5 free models) → Gemini (4 models).
Each provider walks its own model list before handing off to the next.
"""

from __future__ import annotations
from .groq_client import GroqClient
from .openrouter_client import OpenRouterClient
from .gemini_client import GeminiClient
from .base import BaseLLMClient


class GenerationClient(BaseLLMClient):
    def __init__(self) -> None:
        self._groq: GroqClient | None = None
        self._openrouter: OpenRouterClient | None = None
        self._gemini: GeminiClient | None = None

    async def query(self, prompt: str, system: str = "") -> str:
        errors: list[str] = []

        # 1. Groq — llama-3.1-8b → gemma2-9b → mixtral → llama-70b variants
        try:
            if self._groq is None:
                self._groq = GroqClient()
            return await self._groq.query(prompt, system=system)
        except Exception as e:
            errors.append(f"Groq: {e}")

        # 2. OpenRouter — 5 permanently free models (no daily reset)
        try:
            if self._openrouter is None:
                self._openrouter = OpenRouterClient()
            return await self._openrouter.query(prompt, system=system)
        except Exception as e:
            errors.append(f"OpenRouter: {e}")

        # 3. Gemini — flash-8b → flash → 2.0-flash → 2.0-flash-lite
        try:
            if self._gemini is None:
                self._gemini = GeminiClient()
            return await self._gemini.query(prompt, system=system)
        except Exception as e:
            errors.append(f"Gemini: {e}")

        raise RuntimeError("All free LLM providers exhausted:\n" + "\n".join(errors))
