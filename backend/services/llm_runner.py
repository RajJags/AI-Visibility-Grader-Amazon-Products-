"""
LLMRunner -- three scoring slots with concurrency control.

Semaphore limits to 6 simultaneous LLM calls across all slots.
Slots are staggered to spread token load over time.
"""

from __future__ import annotations
import asyncio
from llm_clients import GroqClient, GeminiClient
from llm_clients.openrouter_client import OpenRouterClient
from models import QueryResult

_SYSTEM = (
    "You are a helpful shopping assistant. "
    "Recommend 3-5 specific products by brand name with brief reasoning. "
    "Be direct and specific - name the actual brands and products."
)

_GROQ_LARGE = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.1-8b-instant",
]
_GROQ_SMALL = [
    "llama-3.1-8b-instant",
    "openai/gpt-oss-20b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
]

_SEM = asyncio.Semaphore(6)


class _SlotClient:
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
        last: Exception = RuntimeError("no providers")
        for p in providers:
            try:
                return await p.query(prompt, system=system)
            except Exception as exc:
                last = exc
        raise last


async def _query_safe(client: _SlotClient, query: str, delay: float = 0.0) -> str:
    if delay:
        await asyncio.sleep(delay)
    async with _SEM:
        try:
            return await client.query(query, system=_SYSTEM)
        except Exception as exc:
            return f"[ERROR: {exc}]"


async def run_all_queries(queries: list[str]) -> list[QueryResult]:
    slot_a = _SlotClient(_GROQ_LARGE, gemini_first=False)
    slot_b = _SlotClient(_GROQ_SMALL, gemini_first=False)
    slot_c = _SlotClient(_GROQ_SMALL, gemini_first=True)

    n = len(queries)
    tasks = (
        [_query_safe(slot_a, q, delay=0.0) for q in queries] +
        [_query_safe(slot_b, q, delay=1.0) for q in queries] +
        [_query_safe(slot_c, q, delay=2.0) for q in queries]
    )
    all_responses = await asyncio.gather(*tasks)

    return [
        QueryResult(
            query=queries[i],
            gpt4_response=all_responses[i],
            claude_response=all_responses[n + i],
            gemini_response=all_responses[2 * n + i],
        )
        for i in range(n)
    ]
