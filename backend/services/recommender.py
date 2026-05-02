"""Recommender — generates 5 specific listing improvements via the best available LLM."""

from __future__ import annotations
import json, re
from collections import Counter
from llm_clients import GenerationClient
from models import ParsedQueryResult, Product, Recommendation, Score

_SYSTEM = (
    "You are an expert Amazon listing consultant specialising in AI search visibility. "
    "Your recommendations are specific, data-driven, and immediately actionable."
)

_PROMPT = """\
A seller ran an AI Visibility Diagnostic on their product. Here is the data:

## Product
Title: {title}
Brand: {brand}
Category: {category}
Current bullets:
{bullets}

## AI Visibility Score
Overall: {overall}/100  (GPT-4: {gpt4}, Claude: {claude}, Gemini: {gemini})

## Queries the brand LOST (not mentioned by any model)
{lost_queries}

## Queries the brand WON
{won_queries}

## Top competitor attributes that appeared in winning responses
{competitor_attributes}

## Top competitors beating this brand
{top_competitors}

---

Generate exactly 5 specific, prioritized recommendations to improve AI visibility.
Ground each one in the data above.

Return ONLY a JSON array of 5 objects:
[
  {{
    "title": "Short imperative action (< 8 words)",
    "description": "2-3 sentences referencing specific data — which queries, competitors, attributes.",
    "priority": "high" | "medium" | "low"
  }}
]

No markdown, no explanation outside the JSON.
"""


def _fmt_queries(results: list[ParsedQueryResult], won: bool) -> str:
    filtered = [r for r in results
                if won == (r.mentions.gpt4 or r.mentions.claude or r.mentions.gemini)]
    return "\n".join(f"- {r.query}" for r in filtered[:8]) if filtered else "None"


def _fmt_attrs(results: list[ParsedQueryResult]) -> str:
    counter: Counter[str] = Counter()
    for r in results:
        for attrs in r.attributes.values():
            for a in attrs:
                counter[a] += 1
    top = counter.most_common(15)
    return "\n".join(f"- '{a}' ({n}x)" for a, n in top) if top else "No attribute data"


async def generate_recommendations(product: Product, results: list[ParsedQueryResult],
                                   score: Score) -> list[Recommendation]:
    client = GenerationClient()
    bullets_text = "\n".join(f"  - {b}" for b in product.bullets[:8]) or "  (none)"
    top_comp = "\n".join(f"  - {c.brand} ({c.mention_count} mentions)"
                         for c in score.top_competitors) or "  (none identified)"

    prompt = _PROMPT.format(
        title=product.title, brand=product.brand, category=product.category,
        bullets=bullets_text, overall=score.overall, gpt4=score.gpt4,
        claude=score.claude, gemini=score.gemini,
        lost_queries=_fmt_queries(results, won=False),
        won_queries=_fmt_queries(results, won=True),
        competitor_attributes=_fmt_attrs(results),
        top_competitors=top_comp,
    )

    raw = await client.query(prompt, system=_SYSTEM)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        data = json.loads(match.group()) if match else []

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
            description="Ensure your title, bullets, and A+ content include key attributes "
                        "that AI shopping assistants look for.",
            priority="medium",
        ))
    return recs
