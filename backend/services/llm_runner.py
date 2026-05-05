"""
LLMRunner -- three scoring slots, fully concurrent.

All 18 calls (6 queries x 3 slots) fire simultaneously.
Responses are cached per (query, slot) for 24 hours so repeat runs
on the same product skip the LLM phase entirely.
"""

from __future__ import annotations
import asyncio, time
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

# ---------------------------------------------------------------------------
# LLM response cache  (keyed by (query_text, slot_id), 24-hour TTL)
# Same query + same slot = same LLM response within a day.
# ---------------------------------------------------------------------------
_LLM_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_LLM_CACHE_TTL = 24 * 3600


def _llm_cache_get(query: str, slot: str) -> str | None:
    entry = _LLM_CACHE.get((query, slot))
    if entry and (time.time() - entry[1]) < _LLM_CACHE_TTL:
        return entry[0]
    return None


def _llm_cache_set(query: str, slot: str, response: str) -> None:
    if not response.startswith("[ERROR:"):
        _LLM_CACHE[(query, slot)] = (response, time.time())


# ---------------------------------------------------------------------------

# One semaphore slot per in-flight call -- no artificial bottleneck.
# Each provider enforces its own rate limits.
_SEM = asyncio.Semaphore(18)


class _SlotClient:
    def __init__(self, slot_id: str, groq_models: list[str], gemini_first: bool = False):
        self.slot_id = slot_id
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


async def _query_safe(client: _SlotClient, query: str) -> str:
    cached = _llm_cache_get(query, client.slot_id)
    if cached:
        return cached
    async with _SEM:
        try:
            result = await client.query(query, system=_SYSTEM)
            _llm_cache_set(query, client.slot_id, result)
            return result
        except Exception as exc:
            return f"[ERROR: {exc}]"


async def run_all_queries(queries: list[str]) -> list[QueryResult]:
    slot_a = _SlotClient("a", _GROQ_LARGE, gemini_first=False)
    slot_b = _SlotClient("b", _GROQ_SMALL, gemini_first=False)
    slot_c = _SlotClient("c", _GROQ_SMALL, gemini_first=True)

    n = len(queries)
    # All 18 calls fire at once -- no artificial stagger.
    tasks = (
        [_query_safe(slot_a, q) for q in queries] +
        [_query_safe(slot_b, q) for q in queries] +
        [_query_safe(slot_c, q) for q in queries]
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
