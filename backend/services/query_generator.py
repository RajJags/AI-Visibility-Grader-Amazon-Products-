"""QueryGenerator -- structured two-step query generation. Always returns exactly 6."""

from __future__ import annotations
import json, os, re
from pydantic import TypeAdapter, ValidationError
from llm_clients import GenerationClient
from models import Product

_SYSTEM = "You are a search query strategist. Output only valid JSON."

# ---------------------------------------------------------------------------
# Query cache  (keyed by ASIN, 6-hour TTL matching product cache)
# Same product = same specs = same queries every time.
# ---------------------------------------------------------------------------
import time as _time
_QUERY_CACHE: dict[str, tuple[list[str], float]] = {}
_QUERY_CACHE_TTL = 6 * 3600


def _query_cache_get(asin: str) -> list[str] | None:
    entry = _QUERY_CACHE.get(asin)
    if entry and (_time.time() - entry[1]) < _QUERY_CACHE_TTL:
        return entry[0]
    return None


def _query_cache_set(asin: str, queries: list[str]) -> None:
    _QUERY_CACHE[asin] = (queries, _time.time())

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
  - If using price, include the currency (e.g. "under $20", "under 1500 INR")
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
  - "best budget [form_factor] for [use_case]"
  - "[form_factor] with [top_spec] for [use_case]"
  - "[form_factor] good for [use_case] and [use_case]"
  - "most [attribute] [form_factor] in [price_tier]"
  - "[form_factor] that [solves a specific problem implied by use_case]"
  - "[form_factor] with [spec1] and [spec2]"

Rules:
  - Use actual spec numbers, not vague words like "long" or "good"
  - Only use price amounts when a real amount and currency are present in the listing
  - 4-12 words, conversational natural language
  - NO brand names, model numbers, or proprietary feature names
  - Vary the patterns -- do not repeat the same structure 8 times

Return ONLY a JSON array of 8 query strings. No other text.
"""

_SPEC_UNITS = frozenset(["gb", "mb", "tb", "mp", "mah", "hz", "ghz", "mhz",
                          "mm", "cm", "nm", "w", "mw", "db", "fps", "ms"])

_CATEGORY_FALLBACKS = {
    "electronics": [
        "best value electronics for everyday use",
        "reliable device with long lasting performance",
        "top rated option with useful smart features",
        "best device with dependable battery life",
        "popular choice with good warranty support",
        "easy to use device for daily tasks",
    ],
    "beauty": [
        "best beauty tool for everyday styling",
        "gentle option for daily personal care",
        "top rated product for easy routines",
        "beauty tool for salon like results",
        "reliable product for sensitive users",
        "popular choice for quick daily use",
    ],
    "health": [
        "best health product for daily wellness",
        "reliable option for everyday home use",
        "top rated product for family care",
        "easy to use health product at home",
        "popular wellness product with good reviews",
        "safe option for regular personal care",
    ],
    "home": [
        "best home product for everyday use",
        "reliable option for small spaces",
        "top rated product for home organization",
        "easy to use product for busy households",
        "durable product for daily home needs",
        "popular choice for practical home use",
    ],
    "fashion": [
        "best comfortable option for daily wear",
        "top rated style for everyday outfits",
        "durable option for regular use",
        "popular choice with good fit",
        "versatile style for casual wear",
        "reliable option with comfortable material",
    ],
    "default": [
        "best value option with good reviews",
        "reliable pick with long lasting build quality",
        "top rated product for everyday use",
        "easy to use option for daily needs",
        "popular choice with dependable quality",
        "well reviewed product for regular use",
    ],
}

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


def _fallback_bucket(product: Product) -> str:
    text = " ".join(
        [
            product.title,
            product.category,
            " ".join(product.bullets[:5]),
            " ".join(product.specs.keys()),
            " ".join(product.specs.values()),
        ]
    ).lower()
    if any(term in text for term in (
        "phone", "smartphone", "laptop", "computer", "tablet", "earbud",
        "headphone", "speaker", "camera", "monitor", "keyboard", "mouse",
        "charger", "battery", "bluetooth", "wireless", "electronics",
    )):
        return "electronics"
    if any(term in text for term in (
        "beauty", "hair", "skin", "makeup", "styler", "shampoo", "serum",
        "conditioner", "grooming", "cosmetic", "personal care",
    )):
        return "beauty"
    if any(term in text for term in (
        "health", "wellness", "supplement", "vitamin", "medical", "fitness",
        "nutrition", "hygiene", "household", "baby care",
    )):
        return "health"
    if any(term in text for term in (
        "home", "kitchen", "furniture", "decor", "storage", "cleaning",
        "appliance", "bedding", "bath", "garden",
    )):
        return "home"
    if any(term in text for term in (
        "shirt", "shoe", "jeans", "dress", "fashion", "apparel", "clothing",
        "wear", "watch", "bag", "wallet",
    )):
        return "fashion"
    return "default"


def _fallbacks_for(product: Product) -> list[str]:
    return _CATEGORY_FALLBACKS[_fallback_bucket(product)]


def _currency_hint(product: Product | None) -> str:
    text = ""
    if product:
        text = " ".join(
            [product.title, product.category]
            + list(product.specs.keys())
            + list(product.specs.values())
        ).lower()
    if any(token in text for token in ("₹", "inr", "rs.", "rs ", "rupee", "rupees")):
        return "INR"
    if any(token in text for token in ("$", "usd", "dollar", "dollars")):
        return "dollars"
    if any(token in text for token in ("£", "gbp", "pound", "pounds")):
        return "GBP"
    if any(token in text for token in ("€", "eur", "euro", "euros")):
        return "EUR"

    marketplace = os.environ.get("AMAZON_MARKETPLACE", "IN").upper()
    return {
        "IN": "INR",
        "US": "dollars",
        "CA": "CAD",
        "UK": "GBP",
        "DE": "EUR",
        "FR": "EUR",
        "IT": "EUR",
        "ES": "EUR",
        "AU": "AUD",
        "JP": "JPY",
    }.get(marketplace, "dollars")


def _format_under_price(amount: str, currency: str) -> str:
    if currency == "dollars":
        return f"under {amount} dollars"
    return f"under {currency} {amount}"


def _add_missing_under_currency(query: str, currency: str) -> str:
    currencies = r"(?:dollars?|usd|inr|rupees?|rs\.?|₹|\$|gbp|pounds?|eur|euros?|cad|aud|jpy)"

    def repl(match: re.Match[str]) -> str:
        return _format_under_price(match.group("amount"), currency)

    return re.sub(
        rf"\bunder\s+(?P<amount>\d+(?:,\d{{3}})*(?:\.\d+)?)\b(?!\s*{currencies})",
        repl,
        query,
        flags=re.IGNORECASE,
    )


def _clean_query_text(query: str, product: Product | None = None) -> str:
    q = re.sub(r"\s+", " ", query.strip().lower())
    q = q.strip(" .?!,;:")

    q = re.sub(r"\bunder\s+budget\s+(\d+)\b", r"under \1", q)
    q = re.sub(r"\bin\s+budget\b", "", q)
    q = re.sub(r"\bbudget\s+friendly\b", "budget-friendly", q)
    q = re.sub(r"\bgood\s+for\b", "for", q)
    q = re.sub(r"\b(\d+)\s*hours?\s+playtime\b", r"\1-hour playtime", q)
    q = re.sub(r"\b(\d+)\s*hours?\s+battery\b", r"\1-hour battery", q)
    q = re.sub(r"\b(\d+)\s*hours?\s+of\s+playtime\b", r"\1-hour playtime", q)
    q = re.sub(r"\b(\d+)\s*hr\s+playtime\b", r"\1-hour playtime", q)
    q = re.sub(r"\b(\d+)\s*hrs\s+playtime\b", r"\1-hour playtime", q)
    q = _add_missing_under_currency(q, _currency_hint(product))

    q = re.sub(r"\s+", " ", q).strip()
    q = re.sub(r"\binr\b", "INR", q)
    q = re.sub(r"\busd\b", "USD", q)
    q = re.sub(r"\bgbp\b", "GBP", q)
    q = re.sub(r"\beur\b", "EUR", q)
    q = re.sub(r"\bcad\b", "CAD", q)
    q = re.sub(r"\baud\b", "AUD", q)
    q = re.sub(r"\bjpy\b", "JPY", q)
    return q


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


def _clean_queries(queries: list[str], product: Product) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for query in queries:
        q = _clean_query_text(query, product)
        if len(q) <= 5 or q in seen:
            continue
        cleaned.append(q)
        seen.add(q)
    return cleaned


async def generate_queries(product: Product) -> list[str]:
    cached = _query_cache_get(product.asin)
    if cached:
        return cached

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
        parsed = _clean_queries(_parse_queries(raw), product)
        candidates = [q for q in parsed if not _is_branded(q, product.brand, product.title)]
        if len(candidates) >= 6:
            result = candidates[:6]
            _query_cache_set(product.asin, result)
            return result
        if attempt == 0:
            prompt += "\n\nMust return exactly 8 queries. No brand names. Use real numbers from the specs."

    seen = {q.lower() for q in candidates}
    for fb in _fallbacks_for(product):
        if len(candidates) >= 6:
            break
        fb = _clean_query_text(fb, product)
        if fb.lower() not in seen:
            candidates.append(fb)
            seen.add(fb.lower())
    _query_cache_set(product.asin, candidates[:6])
    return candidates[:6]
