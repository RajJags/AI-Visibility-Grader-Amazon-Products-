"""ResponseParser — uses the best available LLM to extract structured mention data."""

from __future__ import annotations
import asyncio, json, re
from llm_clients import GenerationClient
from models import ModelMentions, ModelPositions, ParsedQueryResult, QueryResult

_SYSTEM = "You are a structured data extraction assistant. Always respond with valid JSON only."

_PROMPT = """\
Shopping query: "{query}"

LLM response to parse:
\"\"\"
{response}
\"\"\"

Target brand: "{brand}"

Return JSON only:
{{
  "mentioned": true/false,
  "position": null or integer,
  "competitors": ["Brand A", ...],
  "attributes": {{"Brand A": ["attr1"], "{brand}": ["attr1"]}}
}}

Rules:
- position is 1-indexed rank among recommended brands (null if not mentioned)
- competitors = other proper brand names mentioned (exclude target brand)
- attributes = key specs/claims per brand (e.g. "gluten-free", "400mg", "third-party tested")
- Return ONLY the JSON object, nothing else.
"""


async def _parse_one_response(client: GenerationClient, query: str,
                               response_text: str, brand: str) -> dict:
    if response_text.startswith("[ERROR:"):
        return {"mentioned": False, "position": None, "competitors": [], "attributes": {}}
    prompt = _PROMPT.format(query=query, response=response_text[:2000], brand=brand)
    raw = await client.query(prompt, system=_SYSTEM)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {"mentioned": False, "position": None, "competitors": [], "attributes": {}}


def _safe_bool(val: object) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "yes", "1")
    return bool(val)


def _safe_int(val: object) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


async def parse_query_results(results: list[QueryResult], brand: str) -> list[ParsedQueryResult]:
    client = GenerationClient()

    async def parse_one(qr: QueryResult) -> ParsedQueryResult:
        gpt4_p, claude_p, gemini_p = await asyncio.gather(
            _parse_one_response(client, qr.query, qr.gpt4_response, brand),
            _parse_one_response(client, qr.query, qr.claude_response, brand),
            _parse_one_response(client, qr.query, qr.gemini_response, brand),
        )
        all_competitors: list[str] = []
        for p in (gpt4_p, claude_p, gemini_p):
            all_competitors.extend(p.get("competitors", []))
        unique_competitors = list(dict.fromkeys(all_competitors))

        merged_attrs: dict[str, list[str]] = {}
        for p in (gpt4_p, claude_p, gemini_p):
            for b, attrs in p.get("attributes", {}).items():
                if b not in merged_attrs:
                    merged_attrs[b] = []
                merged_attrs[b].extend(a for a in attrs if a not in merged_attrs[b])

        return ParsedQueryResult(
            query=qr.query,
            mentions=ModelMentions(
                gpt4=_safe_bool(gpt4_p.get("mentioned")),
                claude=_safe_bool(claude_p.get("mentioned")),
                gemini=_safe_bool(gemini_p.get("mentioned")),
            ),
            position=ModelPositions(
                gpt4=_safe_int(gpt4_p.get("position")),
                claude=_safe_int(claude_p.get("position")),
                gemini=_safe_int(gemini_p.get("position")),
            ),
            competitors_mentioned=unique_competitors,
            attributes=merged_attrs,
        )

    return list(await asyncio.gather(*[parse_one(qr) for qr in results]))
