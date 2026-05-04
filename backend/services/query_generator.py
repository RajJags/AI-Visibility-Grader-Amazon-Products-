"""QueryGenerator -- uses the best available LLM to produce 10 buyer queries."""

from __future__ import annotations
import json, re
from pydantic import TypeAdapter, ValidationError
from llm_clients import GenerationClient
from models import Product

_SYSTEM = (
    "You are an expert Amazon search strategist. "
    "Generate realistic search queries that shoppers use when looking for products."
)

_PROMPT = """Product: {title}
Brand: {brand}
Category: {category}
Key bullets: {bullets}

Generate exactly 10 realistic buyer search queries a shopper might ask ChatGPT, Google,
or a voice assistant when looking for a product like this.

Cover 3 buckets:
- 3-4 high-intent comparison queries  (e.g. "best flagship Android phone 2024")
- 3-4 problem-first queries            (e.g. "smartphone with longest battery life")
- 2-3 attribute-specific queries       (e.g. "phone with 50mp camera under $900")

Rules:
- 3-10 words, natural language.
- NO brand names, NO product names, NO model numbers, NO "vs [brand]" framing.
- Queries should reflect what a shopper types BEFORE they know which brand to buy.
- Return ONLY a valid JSON array of 10 strings, no explanation, no markdown.

Example for a premium Android phone:
["best flagship Android phone 2024", "smartphone with best camera under 1000",
 "phone with all day battery life", "best phone for mobile gaming",
 "Android phone with 50mp camera", "durable flagship phone with fast charging",
 "best phone for photography enthusiasts", "smartphone with best display brightness",
 "phone that works best with wireless earbuds", "fastest Android phone right now"]
"""


# Unit suffixes that appear in specs but are NOT model identifiers
_SPEC_UNITS = frozenset(["gb", "mb", "tb", "mp", "mah", "hz", "ghz", "mhz",
                          "mm", "cm", "nm", "w", "mw", "db", "fps", "ms"])

def _is_branded(query: str, brand: str, title: str) -> bool:
    """Return True if the query contains a brand name or a product-specific model number."""
    q = query.lower()
    # Check brand words
    brand_words = re.split(r"[\s\-/]+", brand.lower())
    for w in brand_words:
        if w and len(w) > 2 and re.search(r"\b" + re.escape(w) + r"\b", q):
            return True
    # Extract model tokens from title: mixed alpha+digit tokens (e.g. S25, 4090, A54)
    # Skip pure numbers and common unit suffixes (50mp, 12gb, 4000mah, etc.)
    model_tokens = re.findall(r"[a-z]*[0-9]+[a-z+]*", title.lower())
    for token in model_tokens:
        # Skip pure numbers
        if token.isdigit():
            continue
        # Skip spec units: digit(s) + unit (e.g. "50mp", "12gb", "4000mah")
        stripped = re.sub(r"\d+", "", token)
        if stripped in _SPEC_UNITS:
            continue
        # Must be at least 2 chars and contain a digit to be a model number
        if len(token) >= 2 and re.search(r"\d", token):
            if re.search(r"\b" + re.escape(token) + r"\b", q):
                return True
    return False


def _parse_queries(raw: str) -> list[str]:
    """Extract a list of query strings from raw LLM output."""
    raw = raw.strip()
    # Strip thinking tags
    raw = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", raw, flags=re.DOTALL).strip()
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
    # Greedy regex to find the full array
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())[:10]
        except json.JSONDecodeError:
            pass
    # Line-based fallback
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        line = re.sub(r"^[\d]+[\.\)]\s*", "", line)
        line = re.sub(r"^[-*\u2022]\s*", "", line)
        line = line.strip("\"\'")
        if len(line) > 5:
            lines.append(line)
    return lines[:10]


async def generate_queries(product: Product) -> list[str]:
    client = GenerationClient()
    bullets_text = " | ".join(product.bullets[:5]) if product.bullets else "N/A"
    prompt = _PROMPT.format(title=product.title, brand=product.brand,
                            category=product.category, bullets=bullets_text)

    queries: list[str] = []
    for attempt in range(2):
        raw = await client.query(prompt, system=_SYSTEM)
        candidates = _parse_queries(raw)
        # Filter out any query that slipped a brand/model name through
        queries = [q for q in candidates if not _is_branded(q, product.brand, product.title)]
        if len(queries) >= 8:
            return queries[:10]
        if attempt == 0:
            prompt = prompt + "\n\nIMPORTANT: Return exactly 10 items. No brand names or model numbers."

    return queries[:10] if queries else []
