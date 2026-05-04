"""Recommender -- data-driven gap analysis + LLM phrasing.

Architecture:
  1. Python identifies genuine gaps:
     - Which queries did we lose?
     - What attributes did competitors get praised for in those lost queries?
     - Which of those attributes are absent from our listing?
  2. LLM only writes actionable advice for the confirmed gaps.
     It does NOT decide what the gaps are.
"""

from __future__ import annotations
import json, re
from collections import Counter
from llm_clients import GenerationClient
from llm_clients.gemini_client import GeminiClient
from models import ParsedQueryResult, Product, Recommendation, Score

_SYSTEM = (
    "You are an expert Amazon listing consultant. "
    "Write specific, actionable listing improvements based on confirmed data."
)

_PROMPT = """Product: {title}
Brand: {brand} | Category: {category}
Current listing text: {listing_text}

Analysis of AI model responses across {total_queries} buyer queries:
- Score: {overall}/100
- Queries lost (brand not recommended): {lost_queries}
- Queries won: {won_queries}

CONFIRMED GAPS -- attributes AI models praised competitors for in queries we LOST,
which do NOT appear in our current listing:
{gaps}

For each gap above, write one recommendation explaining how to address it in the Amazon listing.
Be specific: name the listing section to update (title, bullet 1-2, A+ content, backend keywords)
and explain exactly what to add and why it helps AI visibility.

Return ONLY a JSON array of exactly {n_gaps} objects, no markdown:
[{{"title":"<8 words imperative>","description":"2 sentences with specific advice","priority":"high|medium|low"}}]
"""

_FALLBACK_PROMPT = """Product: {title}
Brand: {brand} | Category: {category}
Product type: {product_type}
Current listing text: {listing_text}
Score: {overall}/100. Lost queries: {lost_queries}. Won queries: {won_queries}.

No specific attribute gaps were detected from the query data.
Based on the category and lost queries, write 3 general recommendations
to improve AI search visibility for this listing.
Focus only on {product_type}: use-case language, quantified claims, and buyer-intent phrasing.
Do not suggest features already mentioned in the listing text above.
Do not mention unrelated categories, gaming, laptops, displays, frame rates, or processors.

Return ONLY a JSON array of 3 objects, no markdown:
[{{"title":"<8 words imperative>","description":"2 sentences with specific advice","priority":"high|medium|low"}}]
"""

_UNRELATED_REC_TERMS = frozenset([
    "gaming", "laptop", "laptops", "processor", "processors", "frame rate",
    "frame rates", "graphics", "display", "benchmark", "benchmarks", "titles",
    "content creation",
])

_PHONE_UNRELATED_REC_TERMS = frozenset([
    "case", "cases", "cover", "covers", "screen protector", "protectors",
    "insurance", "applecare", "protection plan", "warranty plan",
])


def _product_type(product: Product) -> str:
    text = f"{product.title} {product.category}".lower()
    if any(term in text for term in ("airwrap", "styler", "coanda", "cold shot", "hair")):
        return "hair styling tools"
    if any(term in text for term in ("iphone", "smartphone", "phone", "mobile")):
        return "smartphones"
    return product.category if product.category and product.category != "Health & Household" else "this product category"


def _has_unrelated_terms(text: str, product: Product) -> bool:
    product_type = _product_type(product)
    lower = text.lower()
    if product_type == "hair styling tools":
        return any(term in lower for term in _UNRELATED_REC_TERMS)
    if product_type == "smartphones":
        return any(term in lower for term in _PHONE_UNRELATED_REC_TERMS)
    return False


def _fallback_recommendations(product: Product) -> list[Recommendation]:
    if _product_type(product) == "hair styling tools":
        return [
            Recommendation(
                title="Add hair-type use cases",
                description=(
                    "Add bullets for curls, waves, frizz control, damaged hair, and quick styling routines. "
                    "AI assistants match problem-first searches when the listing names the exact hair need."
                ),
                priority="high",
            ),
            Recommendation(
                title="Quantify heat-protection claims",
                description=(
                    "State what the 3 heat settings, cold shot, 1300W motor, and Coanda airflow do in plain buyer language. "
                    "Specific claims make the listing easier to retrieve for heat-damage and airflow queries."
                ),
                priority="high",
            ),
            Recommendation(
                title="Expand attachment guidance",
                description=(
                    "Use A+ content or bullets to map each attachment to the style it creates and the hair type it serves. "
                    "This helps AI models connect the product to searches for curls, waves, smoothing, drying, and volume."
                ),
                priority="medium",
            ),
        ]
    if _product_type(product) == "smartphones":
        return [
            Recommendation(
                title="Clarify camera strengths",
                description=(
                    "Add bullets that name camera use cases such as low-light photos, zoom, video stabilization, and portraits. "
                    "AI assistants often match phone recommendations to the specific camera problem a shopper describes."
                ),
                priority="high",
            ),
            Recommendation(
                title="Quantify battery and performance",
                description=(
                    "State battery life, charging behavior, chipset performance, and storage benefits in direct buyer language. "
                    "Specific claims help the listing compete for premium smartphone searches."
                ),
                priority="high",
            ),
            Recommendation(
                title="Add buyer-intent keywords",
                description=(
                    "Use backend keywords and A+ copy for phrases like premium smartphone, best camera phone, long battery life, and high storage. "
                    "These terms align the listing with natural AI shopping queries without relying on brand searches."
                ),
                priority="medium",
            ),
        ]
    return [
        Recommendation(
            title="Add specific use cases",
            description=(
                "Update the first bullets with concrete buyer scenarios that fit this product category. "
                "AI assistants are more likely to recommend listings that mirror problem-first searches."
            ),
            priority="high",
        ),
        Recommendation(
            title="Quantify key claims",
            description=(
                "Replace vague benefit language with measurable specs or concrete outcomes from the listing. "
                "Specific evidence helps AI models distinguish this product from similar competitors."
            ),
            priority="high",
        ),
        Recommendation(
            title="Mirror buyer search language",
            description=(
                "Add backend keywords and A+ copy using natural phrases from the lost queries. "
                "This improves retrieval for shoppers who describe needs instead of searching by brand."
            ),
            priority="medium",
        ),
    ]


def _listing_tokens(title: str, bullets: list[str]) -> set[str]:
    """Extract a set of normalised tokens from the current listing for gap detection."""
    text = (title + " " + " ".join(bullets)).lower()
    # Individual words + common bigrams
    words = set(re.findall(r'\b[a-z][a-z0-9\-]{1,}\b', text))
    bigrams = set()
    ws = list(re.findall(r'\b[a-z][a-z0-9\-]{1,}\b', text))
    for i in range(len(ws) - 1):
        bigrams.add(ws[i] + " " + ws[i+1])
    return words | bigrams


def _attr_in_listing(attr: str, tokens: set[str]) -> bool:
    """Return True if the attribute is already represented in the listing."""
    attr_words = set(re.findall(r'\b[a-z][a-z0-9\-]{1,}\b', attr.lower()))
    # Consider it present if all meaningful words of the attribute appear
    meaningful = [w for w in attr_words if len(w) > 2]
    if not meaningful:
        return True
    return all(w in tokens or any(w in t for t in tokens) for w in meaningful)


def _find_gaps(
    results: list[ParsedQueryResult],
    brand: str,
    listing_tokens: set[str],
) -> list[tuple[str, int, list[str]]]:
    """
    Returns list of (attribute, frequency, example_queries) for attributes that:
    - Appeared in competitor responses for queries we LOST
    - Are NOT present in our listing
    - Are not keyed to the target brand itself
    Sorted by frequency descending.
    """
    brand_lower = brand.lower()
    attr_counter: Counter[str] = Counter()
    attr_queries: dict[str, list[str]] = {}

    for r in results:
        lost = not (r.mentions.gpt4 or r.mentions.claude or r.mentions.gemini)
        if not lost:
            continue
        for bk, attrs in r.attributes.items():
            if bk.lower() == brand_lower:
                continue
            for a in attrs:
                a = a.strip()
                if len(a) < 3:
                    continue
                # Skip things that look like brand/model names (short all-caps, proper nouns)
                if re.match(r'^[A-Z]{2,6}$', a):
                    continue
                if _attr_in_listing(a, listing_tokens):
                    continue
                attr_counter[a] += 1
                attr_queries.setdefault(a, [])
                if r.query not in attr_queries[a]:
                    attr_queries[a].append(r.query)

    return [
        (attr, count, attr_queries[attr][:2])
        for attr, count in attr_counter.most_common(6)
    ]


def _fmt_queries(results: list[ParsedQueryResult], won: bool) -> str:
    filtered = [r for r in results
                if won == (r.mentions.gpt4 or r.mentions.claude or r.mentions.gemini)]
    return "; ".join(r.query for r in filtered[:3]) or "none"


def _parse_recs(raw: str) -> list[dict]:
    raw = raw.strip()
    raw = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", raw, flags=re.DOTALL).strip()
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("["):
                raw = part
                break
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return []


async def generate_recommendations(
    product: Product,
    results: list[ParsedQueryResult],
    score: Score,
) -> list[Recommendation]:

    listing_text = product.title + "\n" + "\n".join(f"- {b}" for b in product.bullets[:6])
    listing_tokens = _listing_tokens(product.title, product.bullets)

    gaps = _find_gaps(results, product.brand, listing_tokens)
    top_3_gaps = gaps[:3]

    lost_str = _fmt_queries(results, won=False)
    won_str  = _fmt_queries(results, won=True)

    if top_3_gaps:
        gap_lines = "\n".join(
            f"- \"{attr}\" (seen {count}x in lost queries: {', '.join(qs)})"
            for attr, count, qs in top_3_gaps
        )
        prompt = _PROMPT.format(
            title=product.title,
            brand=product.brand,
            category=product.category,
            listing_text=listing_text[:600],
            total_queries=len(results),
            overall=score.overall,
            lost_queries=lost_str,
            won_queries=won_str,
            gaps=gap_lines,
            n_gaps=len(top_3_gaps),
        )
    else:
        prompt = _FALLBACK_PROMPT.format(
            title=product.title,
            brand=product.brand,
            category=product.category,
            product_type=_product_type(product),
            listing_text=listing_text[:600],
            overall=score.overall,
            lost_queries=lost_str,
            won_queries=won_str,
        )

    raw = ""
    try:
        gem = GeminiClient()
        raw = await gem.query(prompt, system=_SYSTEM, max_tokens=700)
    except Exception:
        pass
    if not raw:
        client = GenerationClient()
        raw = await client.query(prompt, system=_SYSTEM, max_tokens=700)

    data = _parse_recs(raw)

    recs: list[Recommendation] = []
    for item in data[:3]:
        if isinstance(item, dict):
            rec = Recommendation(
                title=str(item.get("title", "Improve listing")),
                description=str(item.get("description", "")),
                priority=str(item.get("priority", "medium")).lower(),
            )
            if not _has_unrelated_terms(f"{rec.title} {rec.description}", product):
                recs.append(rec)

    for fallback in _fallback_recommendations(product):
        if len(recs) >= 3:
            break
        if not any(existing.title == fallback.title for existing in recs):
            recs.append(fallback)

    return recs
