"""Scorer -- computes AI Visibility Score from ParsedQueryResults."""
from __future__ import annotations
import re
from collections import Counter
from models import Competitor, ParsedQueryResult, Score

_WEIGHTS   = {1: 1.0, 2: 0.7, 3: 0.5}
_DEFAULT_W = 0.3   # position > 3
_MENTION_W = 0.25  # mentioned but position undetectable (prose response)


def _model_score(results, model):
    total = len(results)
    if not total:
        return 0
    ws = 0.0
    for r in results:
        if not getattr(r.mentions, model):
            continue
        pos = getattr(r.position, model)
        ws += _MENTION_W if pos is None else _WEIGHTS.get(pos, _DEFAULT_W)
    return min(100, max(0, round((ws / total) * 100)))


def _brand_words(brand: str) -> set[str]:
    """Return lowercase tokens from the brand name (len > 2) for fuzzy matching."""
    return {w.lower() for w in re.split(r"[\s\-/]+", brand) if len(w) > 2}


def _is_self(competitor: str, brand: str, brand_tokens: set[str]) -> bool:
    """Return True if the competitor string refers to the target brand itself."""
    comp_lower = competitor.lower()
    # Exact match
    if comp_lower == brand.lower():
        return True
    # Any brand token appears as a whole word in the competitor string
    for token in brand_tokens:
        if re.search(r"\b" + re.escape(token) + r"\b", comp_lower):
            return True
    return False


def compute_score(results: list[ParsedQueryResult], brand: str = "") -> Score:
    gpt4   = _model_score(results, "gpt4")
    claude = _model_score(results, "claude")
    gemini = _model_score(results, "gemini")
    overall = min(100, max(0, round((gpt4 + claude + gemini) / 3)))

    brand_tokens = _brand_words(brand) if brand else set()
    counter: Counter[str] = Counter()
    for r in results:
        for comp in r.competitors_mentioned:
            # Skip if this is just the target brand referring to itself
            if brand and _is_self(comp, brand, brand_tokens):
                continue
            counter[comp] += 1

    top = [Competitor(brand=b, mention_count=c) for b, c in counter.most_common(5)]
    return Score(overall=overall, gpt4=gpt4, claude=claude, gemini=gemini, top_competitors=top)
