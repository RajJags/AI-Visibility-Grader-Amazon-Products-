"""
GenerationClient — smart free-tier LLM with circuit breaker.

Provider order per request:
  1. Build provider list ordered by health (healthy → degraded → failed).
  2. Try each provider in order; skip instantly if it raised a non-transient
     error recently (circuit breaker via _health module).
  3. A shared semaphore caps total in-flight LLM calls so we don't burst
     through Groq's TPM limit across parallel parse/recommend/generate calls.

Providers: Groq → OpenRouter → Gemini (default order when all healthy).
"""

from __future__ import annotations
import asyncio
from .groq_client import GroqClient
from .openrouter_client import OpenRouterClient
from .gemini_client import GeminiClient
from .base import BaseLLMClient
from . import _health as health

# Provider-level health keys (separate from model-level keys inside each client)
_GROQ_KEY = "provider:groq"
_OR_KEY   = "provider:openrouter"
_GEM_KEY  = "provider:gemini"

# Cap total concurrent LLM calls to avoid TPM bursts
_SEM = asyncio.Semaphore(4)


def _ordered_providers(
    groq: GroqClient,
    openrouter: OpenRouterClient,
    gemini: GeminiClient,
) -> list[tuple[str, object]]:
    """Return providers sorted: healthy first, recently-failed last."""
    all_providers = [
        (_GROQ_KEY, groq),
        (_OR_KEY,   openrouter),
        (_GEM_KEY,  gemini),
    ]
    healthy  = [(k, p) for k, p in all_providers if health.is_healthy(k)]
    degraded = [(k, p) for k, p in all_providers if not health.is_healthy(k)]
    return healthy + degraded


class GenerationClient(BaseLLMClient):
    """
    Single LLM client for non-scoring work (query generation, parsing,
    recommendations). Tries providers in health-aware order and marks
    each one healthy/failed for future calls.
    """

    def __init__(self) -> None:
        self._groq: GroqClient | None = None
        self._openrouter: OpenRouterClient | None = None
        self._gemini: GeminiClient | None = None

    def _ensure_clients(self) -> tuple[GroqClient, OpenRouterClient, GeminiClient]:
        if self._groq is None:
            try:
                self._groq = GroqClient()
            except RuntimeError:
                pass
        if self._openrouter is None:
            try:
                self._openrouter = OpenRouterClient()
            except RuntimeError:
                pass
        if self._gemini is None:
            try:
                self._gemini = GeminiClient()
            except RuntimeError:
                pass
        return self._groq, self._openrouter, self._gemini  # type: ignore[return-value]

    async def query(self, prompt: str, system: str = "") -> str:
        async with _SEM:
            return await self._query_inner(prompt, system)

    async def _query_inner(self, prompt: str, system: str) -> str:
        groq, openrouter, gemini = self._ensure_clients()

        available = []
        if groq:
            available.append((_GROQ_KEY, groq))
        if openrouter:
            available.append((_OR_KEY, openrouter))
        if gemini:
            available.append((_GEM_KEY, gemini))

        if not available:
            raise RuntimeError("No LLM providers configured (check API keys in .env)")

        # Sort: healthy providers first
        ordered = (
            [(k, p) for k, p in available if health.is_healthy(k)] +
            [(k, p) for k, p in available if not health.is_healthy(k)]
        )

        errors: list[str] = []
        for key, provider in ordered:
            try:
                result = await provider.query(prompt, system=system)
                health.mark_ok(key)
                return result
            except Exception as exc:
                health.mark_failed(key)
                errors.append(f"{key}: {exc}")
                continue

        raise RuntimeError("All LLM providers exhausted:\n" + "\n".join(errors))
