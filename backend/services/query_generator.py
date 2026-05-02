"""QueryGenerator — uses the best available LLM to produce 10 buyer queries."""

from __future__ import annotations
import json, re
from pydantic import TypeAdapter, ValidationError
from llm_clients import GenerationClient
from models import Product

_SYSTEM = (
    "You are an expert Amazon search strategist. "
    "Generate realistic search queries that shoppers use when looking for products."
)

_PROMPT = """\
Product: {title}
Brand: {brand}
Category: {category}
Key bullets: {bullets}

Generate exactly 10 realistic buyer search queries a shopper might ask ChatGPT, Google, \
or a voice assistant when looking for a product like this.

Cover 3 buckets:
- 3-4 high-intent comparison queries  (e.g. "best magnesium for sleep")
- 3-4 problem-first queries            (e.g. "magnesium that doesn't cause stomach upset")
- 2-3 attribute-specific queries       (e.g. "vegan magnesium glycinate 400mg")

Rules:
- Each query is 3-10 words, natural language, NO brand names.
- Return ONLY a valid JSON array of 10 strings, no explanation, no markdown.

Example: ["best magnesium supplement for sleep", "magnesium for anxiety and stress", ...]
"""


def _parse_queries(raw: str) -> list[str]:
    """Extract a list of query strings from raw LLM output."""
    raw = raw.strip()
    # Strip thinking tags
    raw = re.sub(r"<think(?:ing)?>[^<]*?</think(?:ing)?>", "", raw, flags=re.DOTALL).strip()
    # Strip markdown fences
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                raw = part
                break
    # Try direct JSON parse
    try:
        adapter: TypeAdapter[list[str]] = TypeAdapter(list[str])
        return adapter.validate_json(raw)[:10]
    except (json.JSONDecodeError, ValidationError):
        pass
    # Greedy regex to find the full array (non-greedy \[.*?\] stops at first ])
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())[:10]
        except json.JSONDecodeError:
            pass
    # Line-based fallback — strip numbering/bullets
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        line = re.sub(r"^[\d]+[\.\)]\s*", "", line)   # "1. " or "1) "
        line = re.sub(r'^[-*•]\s*', "", line)          # "- " or "* "
        line = line.strip('"\'')
        if len(line) > 5:
            lines.append(line)
    return lines[:10]


async def generate_queries(product: Product) -> list[str]:
    client = GenerationClient()
    bullets_text = " | ".join(product.bullets[:5]) if product.bullets else "N/A"
    prompt = _PROMPT.format(title=product.title, brand=product.brand,
                            category=product.category, bullets=bullets_text)

    for attempt in range(2):
        raw = await client.query(prompt, system=_SYSTEM)
        queries = _parse_queries(raw)
        if len(queries) >= 8:
            return queries[:10]
        # LLM returned too few — retry once with a firmer nudge
        if attempt == 0:
            prompt = prompt + "\n\nIMPORTANT: You must return exactly 10 items in the JSON array."

    # Return whatever we got (even if < 10)
    return queries[:10] if queries else []
