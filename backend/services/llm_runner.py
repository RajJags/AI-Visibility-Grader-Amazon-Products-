"""
LLMRunner — three scoring slots, each with its own Groq model list + Gemini fallback.

Slot A (gpt4)   → 70B-class models  (llama-3.3-70b, gpt-oss-120b, qwen3-32b)
Slot B (claude) → 8-20B-class       (llama-3.1-8b,  gpt-oss-20b,  llama4-scout)
Slot C (gemini) → Gemini first, then Groq fallback
"""

from __future__ import annotations
import asyncio
from llm_clients import GroqClient, GeminiClient
from llm_clients.openrouter_client import OpenRouterClient
from models import QueryResult

_SYSTEM = (
    "You are a helpful shopping assistant. "
    "Recommend 3-5 specific products by brand name with brief reasoning. "
    "Be direct and specific — name the actual brands and products."
)

_GROQ_LARGE = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.1-8b-instant",          # last-resort within slot
]
_GROQ_SMALL = [
    "llama-3.1-8b-instant",
    "openai/gpt-oss-20b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
]


async def _query_safe(client, query: str) -> str:
    try:
        return await client.query(query, system=_SYSTEM)
    except Exception as exc:
        return f"[ERROR: {exc}]"


class _SlotClient:
    """Primary provider list → OpenRouter free fallback → Gemini fallback."""

    def __init__(self, groq_models: list[str], gemini_first: bool = False):
        self._groq = GroqClient(models=groq_models)
        self._or   = OpenRouterClient()
        self._gem  = GeminiClient()
        self._gemini_first = gemini_first

    async def query(self, prompt: str, system: str = "") -> str:
        providers = (
            [self._gem, self._groq, self._or]
            if self._gemini_first
            else [self._groq, self._or, self._gem]
        )
        last: Exception = RuntimeError("no providers configured")
        for p in providers:
            try:
                return await p.query(prompt, system=system)
            except Exception as exc:
                last = exc
        raise last


async def run_all_queries(queries: list[str]) -> list[QueryResult]:
    slot_a = _SlotClient(_GROQ_LARGE, gemini_first=False)   # "gpt4" slot
    slot_b = _SlotClient(_GROQ_SMALL, gemini_first=False)   # "claude" slot
    slot_c = _SlotClient(_GROQ_SMALL, gemini_first=True)    # "gemini" slot

    n = len(queries)
    all_responses = await asyncio.gather(
        *[_query_safe(slot_a, q) for q in queries],
        *[_query_safe(slot_b, q) for q in queries],
        *[_query_safe(slot_c, q) for q in queries],
    )

    return [
        QueryResult(
            query=queries[i],
            gpt4_response=all_responses[i],
            claude_response=all_responses[n + i],
            gemini_response=all_responses[2 * n + i],
        )
        for i in range(n)
    ]
