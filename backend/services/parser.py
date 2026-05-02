"""
ResponseParser — pure text parsing, zero LLM calls.

Replaces the original LLM-based parser which was making 30 extra LLM calls
(10 queries × 3 models) and adding 20-40 s to every diagnostic run.

Brand mention:  simple case-insensitive substring search
Position:       detect numbered-list rank (1. / 1) / #1)
Competitors:    extract brand-like names from numbered list items
Attributes:     skipped (not needed for scoring; recommender uses won/lost queries)
"""

from __future__ import annotations
import re
from models import ModelMentions, ModelPositions, ParsedQueryResult, QueryResult

# Match numbered list items:  "1. ...", "1) ...", "#1 ..."
_LIST_RE = re.compile(
    r'(?:^|\n)\s*(?:#\s*)?(\d+)[.)]\s+(.+?)(?=\n\s*(?:#\s*)?\d+[.)]|\Z)',
    re.DOTALL,
)
# Leading brand name from a list item (Title Case or ALL CAPS run)
_BRAND_RE = re.compile(r'^([A-Z][A-Za-z0-9&\'\-]+(?:\s+[A-Z][A-Za-z0-9&\'\-]+){0,4})')


def _parse_response(response: str, brand: str) -> dict:
    """Parse one LLM response string. Returns the same shape as the old LLM parser."""
    if not response or response.startswith("[ERROR:"):
        return {"mentioned": False, "position": None, "competitors": [], "attributes": {}}

    brand_lower = brand.lower()
    resp_lower  = response.lower()
    mentioned   = brand_lower in resp_lower

    # Numbered list items
    items = _LIST_RE.findall(response)   # [(num_str, text), ...]

    # Brand position in numbered list
    position: int | None = None
    for num_str, text in items:
        if brand_lower in text.lower():
            try:
                position = int(num_str)
            except ValueError:
                pass
            break

    # Competitor brand names from list items
    competitors: list[str] = []
    for _, text in items:
        text = text.strip()
        m = _BRAND_RE.match(text)
        if m:
            cand = m.group(1).strip()
            if (cand.lower() != brand_lower
                    and cand not in competitors
                    and len(cand) > 2):
                competitors.append(cand)

    # Fallback: if no numbered list, pull capitalized runs (2-4 words) from text
    if not competitors:
        for m in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b', response):
            cand = m.group(1)
            if cand.lower() != brand_lower and cand not in competitors:
                competitors.append(cand)

    return {
        "mentioned": mentioned,
        "position": position,
        "competitors": competitors[:8],
        "attributes": {},
    }


def _safe_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "yes", "1")


def _safe_int(v: object) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


async def parse_query_results(
    results: list[QueryResult], brand: str
) -> list[ParsedQueryResult]:
    """Synchronous text parsing wrapped in async signature for drop-in compatibility."""
    parsed: list[ParsedQueryResult] = []
    for qr in results:
        gpt4_p   = _parse_response(qr.gpt4_response,   brand)
        claude_p = _parse_response(qr.claude_response, brand)
        gemini_p = _parse_response(qr.gemini_response, brand)

        all_comps: list[str] = []
        for p in (gpt4_p, claude_p, gemini_p):
            for c in p["competitors"]:
                if c not in all_comps:
                    all_comps.append(c)

        parsed.append(ParsedQueryResult(
            query=qr.query,
            mentions=ModelMentions(
                gpt4=_safe_bool(gpt4_p["mentioned"]),
                claude=_safe_bool(claude_p["mentioned"]),
                gemini=_safe_bool(gemini_p["mentioned"]),
            ),
            position=ModelPositions(
                gpt4=_safe_int(gpt4_p["position"]),
                claude=_safe_int(claude_p["position"]),
                gemini=_safe_int(gemini_p["position"]),
            ),
            competitors_mentioned=all_comps,
            attributes={},
        ))
    return parsed
