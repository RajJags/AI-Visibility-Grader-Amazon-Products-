"""QueryGenerator -- produces exactly 6 brand-clean buyer queries."""

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
Product type: {product_type}
Key bullets: {bullets}

Generate exactly 8 realistic buyer search queries a shopper might ask ChatGPT, Google,
or a voice assistant when looking for a product like this.

Cover 3 buckets:
- 3 high-intent comparison queries for this product type
- 3 problem-first queries for this product type
- 2 attribute-specific queries using attributes from the title/bullets

Rules:
- 3-10 words, natural language.
- NO brand names, NO product names, NO model numbers, NO "vs [brand]" framing.
- Queries should reflect what a shopper types BEFORE they know which brand to buy.
- Every query must be about {product_type}; do not use examples from other categories.
- Return ONLY a valid JSON array of 8 strings, no explanation, no markdown.
"""

_SPEC_UNITS = frozenset(["gb", "mb", "tb", "mp", "mah", "hz", "ghz", "mhz",
                          "mm", "cm", "nm", "w", "mw", "db", "fps", "ms"])

_UNRELATED_TERMS = frozenset([
    "laptop", "laptops", "gaming", "game", "games", "graphics", "processor",
    "ssd", "display", "monitor", "keyboard", "frame", "frames", "fps",
    "inverter", "ton", "ac", "refrigerator", "washing", "microwave",
])

_PHONE_UNRELATED_TERMS = frozenset([
    "case", "cover", "protector", "screen protector", "insurance", "warranty",
    "applecare", "protection plan", "charger", "cable",
])

_HAIR_FALLBACKS = [
    "best multi styler for curly hair",
    "styling tool that prevents heat damage",
    "hair styler with cold shot function",
    "air wrap styler for damaged hair",
    "hair tool with multiple heat settings",
    "best styler for waves and curls",
]

_PHONE_FALLBACKS = [
    "best smartphone for everyday use",
    "phone with best camera quality",
    "smartphone with long battery life",
    "best premium phone right now",
    "phone with fast performance",
    "smartphone with large storage capacity",
]

_DEFAULT_FALLBACKS = [
    "best products for everyday use",
    "top rated option with useful features",
    "product that solves common buyer problems",
    "best value product in this category",
    "easy to use product for beginners",
    "premium product with reliable performance",
]


def _product_type(product: Product) -> str:
    text = f"{product.title} {product.category}".lower()
    if any(term in text for term in ("airwrap", "styler", "coanda", "cold shot", "hair")):
        return "hair styling tools"
    if any(term in text for term in ("iphone", "smartphone", "phone", "mobile")):
        return "smartphones"
    return product.category if product.category and product.category != "Health & Household" else "this product category"


def _fallbacks_for(product: Product) -> list[str]:
    product_type = _product_type(product)
    if product_type == "hair styling tools":
        return _HAIR_FALLBACKS
    if product_type == "smartphones":
        return _PHONE_FALLBACKS
    return [q.replace("product", product_type) for q in _DEFAULT_FALLBACKS]


def _is_unrelated(query: str, product: Product) -> bool:
    product_type = _product_type(product)
    if product_type != "hair styling tools":
        if product_type != "smartphones":
            return False
        lower = query.lower()
        return any(term in lower for term in _PHONE_UNRELATED_TERMS)
    words = set(re.findall(r"\b[a-z]+\b", query.lower()))
    return bool(words & _UNRELATED_TERMS)


def _is_branded(query: str, brand: str, title: str) -> bool:
    q = query.lower()
    brand_words = re.split(r"[\s\-/]+", brand.lower())
    for w in brand_words:
        if w and len(w) > 2 and re.search(r"\b" + re.escape(w) + r"\b", q):
            return True
    model_tokens = re.findall(r"[a-z]*[0-9]+[a-z+]*", title.lower())
    for token in model_tokens:
        if token.isdigit():
            continue
        stripped = re.sub(r"\d+", "", token)
        if stripped in _SPEC_UNITS:
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
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                raw = part
                break
    try:
        adapter: TypeAdapter[list[str]] = TypeAdapter(list[str])
        return adapter.validate_json(raw)[:8]
    except (json.JSONDecodeError, ValidationError):
        pass
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())[:8]
        except json.JSONDecodeError:
            pass
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        line = re.sub(r"^[\d]+[\.\)]\s*", "", line)
        line = re.sub(r"^[-*]\s*", "", line)
        line = line.strip('"\'')
        if len(line) > 5:
            lines.append(line)
    return lines[:8]


async def generate_queries(product: Product) -> list[str]:
    client = GenerationClient()
    bullets_text = " | ".join(product.bullets[:5]) if product.bullets else "N/A"
    prompt = _PROMPT.format(title=product.title, brand=product.brand,
                            category=product.category, product_type=_product_type(product),
                            bullets=bullets_text)

    candidates: list[str] = []
    for attempt in range(2):
        raw = await client.query(prompt, system=_SYSTEM)
        parsed = _parse_queries(raw)
        candidates = [
            q for q in parsed
            if not _is_branded(q, product.brand, product.title)
            and not _is_unrelated(q, product)
        ]
        if len(candidates) >= 6:
            return candidates[:6]
        if attempt == 0:
            prompt = (
                prompt
                + "\n\nIMPORTANT: Return exactly 8 items. No brand names, model numbers, "
                + f"or unrelated categories. Stay about {_product_type(product)}."
            )

    # Pad to exactly 6 with fallbacks if LLM returned too few clean queries
    seen = {q.lower() for q in candidates}
    for fb in _fallbacks_for(product):
        if len(candidates) >= 6:
            break
        if fb.lower() not in seen:
            candidates.append(fb)
            seen.add(fb.lower())

    return candidates[:6]
