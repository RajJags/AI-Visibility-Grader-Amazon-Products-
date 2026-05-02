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


async def generate_queries(product: Product) -> list[str]:
    client = GenerationClient()
    bullets_text = " | ".join(product.bullets[:5]) if product.bullets else "N/A"
    prompt = _PROMPT.format(title=product.title, brand=product.brand,
                            category=product.category, bullets=bullets_text)
    raw = await client.query(prompt, system=_SYSTEM)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        adapter: TypeAdapter[list[str]] = TypeAdapter(list[str])
        return adapter.validate_json(raw)[:10]
    except (json.JSONDecodeError, ValidationError):
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())[:10]
            except json.JSONDecodeError:
                pass
        lines = [l.strip().strip('"').strip("'") for l in raw.splitlines() if l.strip()]
        return [l for l in lines if l][