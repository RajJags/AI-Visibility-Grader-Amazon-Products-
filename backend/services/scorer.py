"""Scorer — computes AI Visibility Score from ParsedQueryResults."""

from __future__ import annotations
from collections import Counter
from models import Competitor, ParsedQueryResult, Score

_WEIGHTS = {1: 1.0, 2: 0.7, 3: 0.5}
_DEFAULT_W = 0.3


def _w(pos: int | None) -> float:
    return 0.0 if pos is None else _WEIGHTS.get(pos, _DEFAULT_W)


def _model_score(results: list[ParsedQueryResult], model: str) -> int:
    total = len(results)
    if not total:
        return 0
    ws = sum(_w(getattr(r.position, model)) for r in results if getattr(r.mentions, model))
    return min(100, max(0, round((ws / total) * 100)))


def compute_score(results: list[ParsedQueryResult]) -> Score:
    gpt4 = _model_score(results, "gpt4")
    claude = _model_score(results, "claude")
    gemini = _model_score(results, "gemini")
    overall = min(100, max(0, round((gpt4 + claude + gemini) / 3)))

    counter: Counter[str] = Counter()
    for r in results:
        for comp in r.competitors_mentioned:
            counter[comp] += 1

    top = [Competitor(brand=b, mention_count=c) for b, c in counter.most_common(5)]
    return Score(overall=overall, gpt4=gpt4, claude=claude, gemini=gemini, top_competitors=top)
