"""Recommender -- generates 5 specific listing improvements via the best available LLM.

Uses Gemini first (it has fresh quota -- scoring/parse burned through Groq TPM).
Falls back to GenerationClient (Groq/OpenRouter) if Gemini is unavailable.
"""

from __future__ import annotations
import json, re
from collections import Counter
from llm_clients import GenerationClient
from llm_clients.gemini_client import GeminiClient
from models import ParsedQueryResult, Product, Recommendation, Score

_SYSTEM = (
    "You are an expert Amazon listing consultant specialising in AI search visibility. "
    "Your recommendations are specific, data-driven, and immediately actionable."
)

_PROMPT = """Product: {title} | Brand: {brand} | Category: {category}
Bullets: {bullets}
AI Visibility Score: {overall}/100 (Llama70B={gpt4}, Llama8B={claude}, Gemini={gemini})
Lost queries (brand not mentioned): {lost_queries}
Won queries: {won_queries}
Competitor attributes seen in winning responses: {competitor_attributes}
Top competitors: {top_competitors}

Generate exactly 5 specific prioritized recommendations to improve AI visibility.
Return ONLY a JSON array, no markdown, no explanation:
[{{"title":"<8 words imperative>","description":"2 sentences with specific data","priority":"high|medium|low"}}]
"""


def _fmt_queries(results: list[ParsedQueryResult], won: bool) -> str:
    filtered = [r for r in results
                if won == (r.mentions.gpt4 or r.mentions.claude or r.mentions.gemini)]
    lines = [r.query for r in filtered[:5]]
    return "; ".join(lines) if lines else "none"


def _fmt_attrs(results: list[ParsedQueryResult]) -> str:
    counter: Counter[str] = Counter()
    for r in results:
        for attrs in r.attributes.values():
            for a in attrs:
                counter[a] += 1
    top = counter.most_common(10)
    return ", ".join(f"{a}({n}x)" for a, n in top) if top else "none"


async def generate_recommendations(
    product: Product,
    results: list[ParsedQueryResult],
    score: Score,
) -> list[Recommendation]:
    bullets_text = "; ".join(product.bullets[:5]) or "(none)"
    top_comp = ", ".join(
        f"{c.brand}({c.mention_count})" for c in score.top_competitors
    ) or "none"

    prompt = _PROMPT.format(
        title=product.title[:120],
        brand=product.brand,
        category=product.category,
        bullets=bullets_text[:400],
        overall=score.overall,
        gpt4=score.gpt4,
        claude=score.claude,
        gemini=score.gemini,
        lost_queries=_fmt_queries(results, won=False),
        won_queries=_fmt_queries(results, won=True),
        competitor_attributes=_fmt_attrs(results),
        top_competitors=top_comp,
    )

    # Gemini first: it has fresh quota since scoring/parse used Groq.
    # Fall back to GenerationClient (Groq -> OpenRouter) if Gemini is down.
    raw = ""
    try:
        gem = GeminiClient()
        raw = await gem.query(prompt, system=_SYSTEM, max_tokens=1200)
    except Exception:
        pass
    if not raw:
        client = GenerationClient()
        raw = await client.query(prompt, system=_SYSTEM, max_tokens=1200)

    raw = raw.strip()

    # Strip thinking-tag blocks
    raw = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", raw, flags=re.DOTALL).strip()

    # Strip markdown fences
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("["):
                raw = part
                break

    data: list = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                pass

    recs: list[Recommendation] = []
    for item in data[:5]:
        if isinstance(item, dict):
            recs.append(Recommendation(
                title=str(item.get("title", "Improve listing")),
                description=str(item.get("description", "")),
                priority=str(item.get("priority", "medium")).lower(),
            ))

    while len(recs) < 5:
        recs.append(Recommendation(
            title="Review and update your listing",
            description=(
                "Ensure your title, bullets, and A+ content include key attributes "
                "that AI shopping assistants look for."
            ),
            priority="medium",
        ))
    return recs
