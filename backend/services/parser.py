"""
ResponseParser -- batched LLM parsing.

One LLM call parses all 3 model responses per query.
10 total calls for 10 queries (vs 30 in the original).
"""

from __future__ import annotations
import asyncio, json, re
from llm_clients import GenerationClient
from models import ModelMentions, ModelPositions, ParsedQueryResult, QueryResult

_SYSTEM = "You are a structured data extraction assistant. Always respond with valid JSON only, no markdown, no explanation."

_BATCH_PROMPT = """\
Shopping query: "{query}"
Target brand: "{brand}"

Three AI shopping assistant responses are shown below. For each one, extract:
- mentioned: true if the target brand appears as a recommendation
- position: 1-indexed rank in the numbered list (null if not in a ranked list)
- competitors: list of OTHER real brand names recommended (not the target brand, not generic phrases)
- attributes: key specs or features mentioned per brand (e.g. "inverter", "5-star", "copper coil")

RESPONSE_A:
{response_a}

RESPONSE_B:
{response_b}

RESPONSE_C:
{response_c}

Return ONLY this JSON:
{{
  "a": {{"mentioned": true/false, "position": null/1/2/3, "competitors": ["Brand X", ...], "attributes": {{"Brand X": ["attr1", "attr2"]}}}},
  "b": {{"mentioned": true/false, "position": null/1/2/3, "competitors": ["Brand X", ...], "attributes": {{}}}},
  "c": {{"mentioned": true/false, "position": null/1/2/3, "competitors": ["Brand X", ...], "attributes": {{}}}}
}}
"""


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
        response_a=qr.gpt4_response[:1500]   if not is_err(qr.gpt4_response)   else "(no response)",
        response_b=qr.claude_response[:1500]  if not is_err(qr.claude_response)  else "(no response)",
        response_c=qr.gemini_response[:1500]  if not is_err(qr.gemini_response)  else "(no response)",
    )

    raw = await client.query(prompt, system=_SYSTEM)
    data = _extract_json(raw)
    a = data.get("a", _EMPTY)
    b = data.get("b", _EMPTY)
    c = data.get("c", _EMPTY)

    all_comps = []
    seen = set()
    for slot in (a, b, c):
        for comp in slot.get("competitors", []):
            if isinstance(comp, str) and comp.lower() not in seen:
                seen.add(comp.lower())
                all_comps.append(comp)

    merged_attrs = {}
    for slot in (a, b, c):
        for bk, attrs in slot.get("attributes", {}).items():
            if bk not in merged_attrs:
                merged_attrs[bk] = []
            for attr in attrs:
                if attr not in merged_attrs[bk]:
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


async def parse_query_results(results, brand):
    client = GenerationClient()
    return list(await asyncio.gather(*[_parse_one(client, qr, brand) for qr in results]))
