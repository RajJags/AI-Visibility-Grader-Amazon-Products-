"""Recommender -- four-signal gap analysis feeding a narrative LLM prompt.

Signals (all from existing parsed data, no extra LLM calls):
  1. Our attributes from WON queries  -- what AI already praises us for
  2. Competitor attributes from ALL queries, weighted by context:
       lost query = weight 2 (absent entirely)
       won query  = weight 1 (present but competitor also praised for something we lack)
     This ensures gaps don't dry up as score improves.
  3. Query-type win/loss breakdown -- where the gap is (use-case vs spec vs comparison)
  4. Position when mentioned -- visibility problem vs differentiation problem
"""

from __future__ import annotations
import json, re
from collections import Counter, defaultdict
from llm_clients import GenerationClient
from llm_clients.gemini_client import GeminiClient
from models import ParsedQueryResult, Product, Recommendation, Score

_SYSTEM = (
    "You are an expert Amazon listing consultant specialising in AI search visibility. "
    "Write specific, actionable listing improvements grounded only in the data provided."
)

_PROMPT = """Product: {title}
Brand: {brand} | Category: {category}
Current listing:
{listing_text}

--- DIAGNOSTIC DATA ---

Overall AI visibility score: {overall}/100
  Llama 3.3 (70B): {gpt4}/100 | Llama 3.1 (8B): {claude}/100 | Gemini: {gemini}/100

Win rate by query type:
{query_type_breakdown}

When mentioned, average recommendation position: {position_summary}

What AI models already praise this product for (strengths to reinforce):
{our_attributes}

Confirmed gaps -- attributes AI praised competitors for, absent from our listing
(weight 2 = from lost queries, weight 1 = from won queries where competitor also appeared):
{gaps}

--- TASK ---

Write exactly 3 recommendations to improve AI visibility.
Each must:
- Address a confirmed gap or a weak query-type win rate
- Name the exact listing element to change (title, product bullet 1-5, enhanced brand content section, search terms)
- Reference the specific data point that justifies it
- NOT suggest adding anything already in the listing text above

Return ONLY a JSON array of 3 objects, no markdown:
[{{"title":"<8 words imperative>","description":"2 sentences with specific data-backed advice","priority":"high|medium|low"}}]
"""

_FALLBACK_PROMPT = """Product: {title} | Brand: {brand} | Category: {category}
Score: {overall}/100. Lost queries: {lost_queries}. Won queries: {won_queries}.
Current listing: {listing_text}

Write 3 recommendations to improve AI search visibility.
Do not suggest anything already in the listing text.
Each must name the listing element to change and why it helps AI visibility.

Return ONLY a JSON array of 3 objects, no markdown:
[{{"title":"<8 words imperative>","description":"2 sentences","priority":"high|medium|low"}}]
"""


def _classify_query(query: str) -> str:
    q = query.lower()
    if re.search(r'\d+\s*(?:hz|gb|tb|mah|hr|hour|watt|inch|mm|k\b)', q):
        return "attribute-specific"
    if any(w in q for w in ["best", "top", "vs", "compare", "recommended", "which", "under", "worth"]):
        return "comparison"
    if any(w in q for w in ["for ", "to ", "while", "during", "when", "how to", "what "]):
        return "problem-first"
    return "general"


def _query_type_breakdown(results: list[ParsedQueryResult]) -> str:
    buckets: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        won = bool(r.mentions.gpt4 or r.mentions.claude or r.mentions.gemini)
        buckets[_classify_query(r.query)].append(won)
    lines = []
    for bucket, outcomes in sorted(buckets.items()):
        wins = sum(outcomes)
        total = len(outcomes)
        pct = round(wins / total * 100)
        lines.append(f"  {bucket}: {wins}/{total} won ({pct}%)")
    return "\n".join(lines) if lines else "  insufficient data"


def _position_summary(results: list[ParsedQueryResult]) -> str:
    positions = []
    for r in results:
        if not (r.mentions.gpt4 or r.mentions.claude or r.mentions.gemini):
            continue
        vals = [p for p in [r.position.gpt4, r.position.claude, r.position.gemini]
                if p is not None]
        if vals:
            positions.append(min(vals))
    if not positions:
        return "never ranked (brand not recommended in any query)"
    avg = sum(positions) / len(positions)
    if avg <= 1.5:
        return f"avg {avg:.1f} -- strong (top of list)"
    if avg <= 2.5:
        return f"avg {avg:.1f} -- moderate (mid-list, needs differentiation)"
    return f"avg {avg:.1f} -- weak (bottom of list, needs stronger signals)"


def _our_attributes(results: list[ParsedQueryResult], brand: str) -> str:
    brand_lower = brand.lower()
    counter: Counter[str] = Counter()
    for r in results:
        if not (r.mentions.gpt4 or r.mentions.claude or r.mentions.gemini):
            continue
        for bk, attrs in r.attributes.items():
            if bk.lower() == brand_lower:
                for a in attrs:
                    counter[a.strip()] += 1
    if not counter:
        return "  none detected (AI did not attribute specific features to this brand)"
    return "\n".join(f"  - {a} ({n}x)" for a, n in counter.most_common(6))


def _listing_tokens(title: str, bullets: list[str], specs: dict[str, str] | None = None) -> set[str]:
    """
    Build a normalised token set from title + bullets + structured specs.
    Specs are the authoritative source for measurable values like "16GB", "144Hz".
    """
    parts = [title] + bullets
    if specs:
        # Add all spec values so gap validator knows what's confirmed in listing data
        parts += list(specs.values())
    text = " ".join(parts).lower()
    words = set(re.findall(r'\b[a-z][a-z0-9\-]{1,}\b', text))
    words |= set(re.findall(r'\b\d+[a-z]+\b', text))
    ws = list(re.findall(r'\b[a-z][a-z0-9\-]{1,}\b', text))
    bigrams = {ws[i] + " " + ws[i+1] for i in range(len(ws)-1)}
    return words | bigrams


def _attr_in_listing(attr: str, tokens: set[str]) -> bool:
    meaningful = [w for w in re.findall(r'\b[a-z][a-z0-9\-]{1,}\b', attr.lower()) if len(w) > 2]
    if not meaningful:
        return True
    return all(w in tokens or any(w in t for t in tokens) for w in meaningful)


def _find_gaps(results: list[ParsedQueryResult], brand: str,
               tokens: set[str]) -> list[tuple[str, int, list[str]]]:
    """
    Mine competitor attributes from ALL queries, weighted by context:
      lost query = weight 2 (brand absent entirely)
      won query  = weight 1 (brand present but competitor also praised for something we lack)
    Ensures gap detection stays rich even when score is high.
    """
    brand_lower = brand.lower()
    scores: Counter[str] = Counter()
    attr_queries: dict[str, list[str]] = {}
    for r in results:
        won = bool(r.mentions.gpt4 or r.mentions.claude or r.mentions.gemini)
        weight = 1 if won else 2
        for bk, attrs in r.attributes.items():
            if bk.lower() == brand_lower:
                continue
            for a in attrs:
                a = a.strip()
                if len(a) < 3 or re.match(r'^[A-Z]{2,6}$', a):
                    continue
                # Skip if it looks like a proper noun / brand name (multi-word with capitals)
                # e.g. "Bang & Olufsen Speakers", "Dolby Atmos Certification"
                words = a.split()
                if len(words) >= 2 and sum(1 for w in words if w[0].isupper()) >= 2:
                    # Allow if it contains a measurable spec token (e.g. "120Hz Display")
                    has_spec = bool(re.search(r'\d+\s*(?:hz|gb|tb|mah|w\b|mm\b|inch)', a.lower()))
                    if not has_spec:
                        continue
                if _attr_in_listing(a, tokens):
                    continue
                scores[a] += weight
                attr_queries.setdefault(a, [])
                if r.query not in attr_queries[a]:
                    attr_queries[a].append(r.query)
    return [(a, n, attr_queries[a][:2]) for a, n in scores.most_common(6)]


def _fmt_queries(results: list[ParsedQueryResult], won: bool) -> str:
    filtered = [r for r in results
                if won == bool(r.mentions.gpt4 or r.mentions.claude or r.mentions.gemini)]
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
    # Pass specs to listing tokens so confirmed spec values aren't flagged as gaps
    tokens = _listing_tokens(product.title, product.bullets, specs=product.specs)
    gaps = _find_gaps(results, product.brand, tokens)[:3]

    if gaps:
        gap_lines = "\n".join(
            f"  - \"{attr}\" (score {n}, queries: {', '.join(qs)})"
            for attr, n, qs in gaps
        )
        prompt = _PROMPT.format(
            title=product.title,
            brand=product.brand,
            category=product.category,
            listing_text=listing_text[:600],
            overall=score.overall,
            gpt4=score.gpt4,
            claude=score.claude,
            gemini=score.gemini,
            query_type_breakdown=_query_type_breakdown(results),
            position_summary=_position_summary(results),
            our_attributes=_our_attributes(results, product.brand),
            gaps=gap_lines,
        )
    else:
        prompt = _FALLBACK_PROMPT.format(
            title=product.title,
            brand=product.brand,
            category=product.category,
            listing_text=listing_text[:600],
            overall=score.overall,
            lost_queries=_fmt_queries(results, won=False),
            won_queries=_fmt_queries(results, won=True),
        )

    raw = ""
    try:
        raw = await GeminiClient().query(prompt, system=_SYSTEM, max_tokens=700)
    except Exception:
        pass
    if not raw:
        raw = await GenerationClient().query(prompt, system=_SYSTEM, max_tokens=700)

    data = _parse_recs(raw)
    recs: list[Recommendation] = [
        Recommendation(
            title=str(item.get("title", "Improve listing")),
            description=str(item.get("description", "")),
            priority=str(item.get("priority", "medium")).lower(),
        )
        for item in data[:3] if isinstance(item, dict)
    ]

    fallbacks = [
        ("Add use-case scenarios to first two bullets",
         "State specific activities in bullets 1-2. "
         "AI models match problem-first queries to listings that name the activity explicitly.",
         "high"),
        ("Include quantified performance benchmarks",
         "Add measurable claims in a dedicated bullet. "
         "AI assistants surface products with verifiable data over vague descriptions.",
         "high"),
        ("Expand A+ content with buyer-intent language",
         "Use problem-solution framing in A+ sections. "
         "AI models weight structured content mirroring how buyers phrase queries.",
         "medium"),
    ]
    for t, d, p in fallbacks:
        if len(recs) >= 3:
            break
        recs.append(Recommendation(title=t, description=d, priority=p))

    return recs
