"""QueryGenerator -- structured two-step query generation. Always returns exactly 6."""

from __future__ import annotations
import json, re
from pydantic import TypeAdapter, ValidationError
from llm_clients import GenerationClient
from models import Product

_SYSTEM = "You are a search query strategist. Output only valid JSON."

# Prompt when structured specs are available (from Amazon product detail table / API)
_PROMPT_WITH_SPECS = """Product: {title}
Category: {category}
Structured specs (from Amazon listing):
{specs_text}
Feature bullets:
{bullets}

These are the verified specs for this product. Use them directly.

Step 1 -- identify TWO things from the context above:
  A. use_cases: up to 3 specific activities buyers purchase this product for
     (e.g. "commuting", "work calls", "travel", "gaming", "gym", "office work")
  B. form_factor: the physical product type
     (e.g. "over-ear headphones", "true wireless earbuds", "gaming laptop", "ultrabook")

Step 2 -- generate 8 search queries a real buyer would type.
Use the verified specs (with their actual numbers) and the use cases you identified.
Query patterns to use:
  - "best [form_factor] under [price from specs] for [use_case]"
  - "[form_factor] with [actual spec value] for [use_case]"
  - "[form_factor] good for [use_case] and [use_case]"
  - "[form_factor] that [solves specific problem implied by use_case]"
  - "most [attribute based on a spec] [form_factor]"
  - "[form_factor] with [spec1] and [spec2]"

Rules:
  - Use actual numbers from the specs above (e.g. "15hr battery", "16GB RAM", "144Hz display")
  - 4-12 words, conversational natural language
  - NO brand names, model numbers, or proprietary feature names
  - Vary the patterns

Return ONLY a JSON array of 8 query strings. No other text.
"""

# Prompt when no structured specs are available (fall back to LLM inference)
_PROMPT_INFER = """Product: {title}
Category: {category}
Feature bullets:
{bullets}

Step 1 -- extract these four things about the product:
  A. price_tier: one of [budget, mid-range, premium] -- infer from product type and category
  B. top_specs: up to 3 measurable standout specs with their actual numbers (e.g. "50hr battery", "active noise cancellation", "4K 144Hz")
  C. use_cases: up to 3 specific activities this product is bought for (e.g. "commuting", "work calls", "travel", "gaming", "gym")
  D. form_factor: the physical type (e.g. "over-ear headphones", "true wireless earbuds", "gaming monitor")

Step 2 -- generate 8 search queries using the extracted values above.
Use these query patterns, populated with real values from Step 1:
  - "best [form_factor] under [price_tier budget amount] for [use_case]"
  - "[form_factor] with [top_spec] for [use_case]"
  - "[form_factor] good for [use_case] and [use_case]"
  - "most [attribute] [form_factor] in [price_tier]"
  - "[form_factor] that [solves a specific problem implied by use_case]"
  - "[form_factor] with [spec1] and [spec2]"

Rules:
  - Use actual spec numbers and price amounts, not vague words like "long" or "good"
  - 4-12 words, conversational natural language
  - NO brand names, model numbers, or proprietary feature names
  - Vary the patterns -- do not repeat the same structure 8 times

Return ONLY a JSON array of 8 query strings. No other text.
"""

_SPEC_UNITS = frozenset(["gb", "mb", "tb", "mp", "mah", "hz", "ghz", "mhz",
                          "mm", "cm", "nm", "w", "mw", "db", "fps", "ms"])

_FALLBACKS = [
    "best value option with good reviews in this category",
    "reliable pick with long lasting build quality",
    "top rated product for everyday use",
    "highly rated option with fast charging support",
    "best performance per dollar in this category",
    "popular choice with good warranty and support",
]

# Spec keys that are directly useful for query generation (measurable / comparable)
_QUERY_USEFUL_SPECS = {
    "processor", "cpu", "chip", "ram", "memory", "storage", "ssd", "hard drive",
    "display size", "screen size", "display", "resolution", "refresh rate",
    "battery life", "battery", "graphics", "gpu", "weight", "operating system",
    "connectivity", "wireless", "bluetooth", "camera", "megapixels",
    "water resistance", "rating", "speakers", "audio",
    "price", "list price", "colour", "color",
}


def _format_specs_for_prompt(specs: dict[str, str], max_entries: int = 12) -> str:
    """
    Format product.specs as a clean list of key: value lines.
    Prioritises spec keys that are most useful for query generation.
    """
    if not specs:
        return "N/A"
    # Score each key by query usefulness
    def score_key(k: str) -> int:
        kl = k.lower()
        for useful in _QUERY_USEFUL_SPECS:
            if useful in kl:
                return 1
        return 0

    ordered = sorted(specs.items(), key=lambda kv: -score_key(kv[0]))
    lines = [f"  {k}: {v}" for k, v in ordered[:max_entries]]
    return "\n".join(lines)


def _is_branded(query: str, brand: str, title: str) -> bool:
    q = query.lower()
    for w in re.split(r"[\s\-/]+", brand.lower()):
        if w and len(w) > 2 and re.search(r"\b" + re.escape(w) + r"\b", q):
            return True
    for token in re.findall(r"[a-z]*[0-9]+[a-z+]*", title.lower()):
        if token.isdigit():
            continue
        if re.sub(r"\d+", "", token) in _SPEC_UNITS:
            continue
        if len(token) >= 2 and re.search(r"\d", token):
            if re.search(r"\b" + re.escape(token) + r"\b", q):
                return True
    return False


def _parse_queries(raw: str) -> list[str]:
    raw = raw.strip()
    raw = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", raw, flags=re.DOTALL).strip()
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("["):
                raw = part
                break
    try:
        return TypeAdapter(list[str]).validate_json(raw)[:8]
    except (json.JSONDecodeError, ValidationError):
        pass
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())[:8]
        except json.JSONDecodeError:
            pass
    lines = []
    for line in raw.splitlines():
        line = re.sub(r"^[\d]+[\.\)]\s*|^[-*]\s*", "", line.strip()).strip('"\'')
        if len(line) > 5:
            lines.append(line)
    return lines[:8]


async def generate_queries(product: Product) -> list[str]:
    client = GenerationClient()
    bullets_text = "\n".join(f"  - {b}" for b in product.bullets[:6]) if product.bullets else "  N/A"

    # Choose prompt: use structured specs if available, fall back to inference
    if product.specs:
        specs_text = _format_specs_for_prompt(product.specs)
        prompt = _PROMPT_WITH_SPECS.format(
            title=product.title,
            category=product.category,
            specs_text=specs_text,
            bullets=bullets_text,
        )
    else:
        prompt = _PROMPT_INFER.format(
            title=product.title,
            category=product.category,
            bullets=bullets_text,
        )

    candidates: list[str] = []
    for attempt in range(2):
        raw = await client.query(prompt, system=_SYSTEM)
        parsed = _parse_queries(raw)
        candidates = [q for q in parsed if not _is_branded(q, product.brand, product.title)]
        if len(candidates) >= 6:
            return candidates[:6]
        if attempt == 0:
            prompt += "\n\nMust return exactly 8 queries. No brand names. Use real numbers from the specs."

    seen = {q.lower() for q in candidates}
    for fb in _FALLBACKS:
        if len(candidates) >= 6:
            break
        if fb.lower() not in seen:
            candidates.append(fb)
    return candidates[:6]
