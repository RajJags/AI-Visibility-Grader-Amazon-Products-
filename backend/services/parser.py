"""
ResponseParser -- batched LLM parsing.

One LLM call parses all 3 model responses per query.
6 total calls for 6 queries, all run concurrently.
"""

from __future__ import annotations
import asyncio, json, re
from llm_clients import GenerationClient
from models import ModelMentions, ModelPositions, ParsedQueryResult, QueryResult

_SYSTEM = "Structured data extractor. Output valid JSON only. No prose, no markdown."

# Compact LLM-to-LLM extraction prompt.
# Humans never read this; optimised for token efficiency and extraction accuracy.
_BATCH_PROMPT = """TASK: brand mention extraction from shopping assistant responses
QUERY: {query}
TARGET_BRAND: {brand}

RESPONSES:
A: {response_a}
B: {response_b}
C: {response_c}

EXTRACT per response:
- mentioned: true if TARGET_BRAND is recommended (exact or common short-form match)
- position: 1-indexed rank in numbered list, null if unranked or not mentioned
- competitors: other brand names recommended (real brands only, not generic phrases)
- attributes: {{brand_name: [feature_strings]}} for all brands mentioned

OUTPUT (JSON only, no other text):
{{"a":{{"mentioned":bool,"position":int|null,"competitors":[],"attributes":{{}}}},"b":{{"mentioned":bool,"position":int|null,"competitors":[],"attributes":{{}}}},"c":{{"mentioned":bool,"position":int|null,"competitors":[],"attributes":{{}}}}}}"""


def _extract_json(raw):
    raw = raw.strip()
    raw = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", raw, flags=re.DOTALL).strip()
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("{"):
                raw = part
                break
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return {}


_EMPTY = {"mentioned": False, "position": None, "competitors": [], "attributes": {}}


def _safe_slot(value):
    return value if isinstance(value, dict) else _EMPTY


def _safe_bool(v):
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "yes", "1")


def _safe_int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_list(value):
    return value if isinstance(value, list) else []


def _safe_attrs(value):
    return value if isinstance(value, dict) else {}


async def _parse_one(client, qr, brand):
    is_err = lambda r: not r or r.startswith("[ERROR:")

    if all(is_err(r) for r in [qr.gpt4_response, qr.claude_response, qr.gemini_response]):
        return ParsedQueryResult(
            query=qr.query,
            mentions=ModelMentions(gpt4=False, claude=False, gemini=False),
            position=ModelPositions(gpt4=None, claude=None, gemini=None),
            competitors_mentioned=[], attributes={},
        )

    prompt = _BATCH_PROMPT.format(
        query=qr.query,
        brand=brand,
        response_a=qr.gpt4_response[:1500]  if not is_err(qr.gpt4_response)  else "(no response)",
        response_b=qr.claude_response[:1500] if not is_err(qr.claude_response) else "(no response)",
        response_c=qr.gemini_response[:1500] if not is_err(qr.gemini_response) else "(no response)",
    )

    raw = await client.query(prompt, system=_SYSTEM)
    data = _extract_json(raw)
    if not isinstance(data, dict):
        data = {}
    a = _safe_slot(data.get("a"))
    b = _safe_slot(data.get("b"))
    c = _safe_slot(data.get("c"))

    all_comps = []
    seen = set()
    for slot in (a, b, c):
        for comp in _safe_list(slot.get("competitors")):
            if isinstance(comp, str) and comp.lower() not in seen:
                seen.add(comp.lower())
                all_comps.append(comp)

    merged_attrs = {}
    for slot in (a, b, c):
        for bk, attrs in _safe_attrs(slot.get("attributes")).items():
            if not isinstance(bk, str):
                continue
            if bk not in merged_attrs:
                merged_attrs[bk] = []
            for attr in _safe_list(attrs):
                if isinstance(attr, str) and attr not in merged_attrs[bk]:
                    merged_attrs[bk].append(attr)

    return ParsedQueryResult(
        query=qr.query,
        mentions=ModelMentions(
            gpt4=_safe_bool(a.get("mentioned")),
            claude=_safe_bool(b.get("mentioned")),
            gemini=_safe_bool(c.get("mentioned")),
        ),
        position=ModelPositions(
            gpt4=_safe_int(a.get("position")),
            claude=_safe_int(b.get("position")),
            gemini=_safe_int(c.get("position")),
        ),
        competitors_mentioned=all_comps[:8],
        attributes=merged_attrs,
    )


async def parse_query_results(results: list[QueryResult], brand: str) -> list[ParsedQueryResult]:
    client = GenerationClient()
    return list(await asyncio.gather(*[_parse_one(client, qr, brand) for qr in results]))
