"""Scorer -- computes AI Visibility Score from ParsedQueryResults."""
from __future__ import annotations
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
        if pos is None:
            ws += _MENTION_W
        else:
            ws += _WEIGHTS.get(pos, _DEFAULT_W)
    return min(100, max(0, round((ws / total) * 100)))


def compute_score(results):
    gpt4   = _model_score(results, "gpt4")
    claude = _model_score(results, "claude")
    gemini = _model_score(results, "gemini")
    overall = min(100, max(0, round((gpt4 + claude + gemini) / 3)))

    counter = Counter()
    for r in results:
        for comp in r.competitors_mentioned:
            counter[comp] += 1

    top = [Competitor(brand=b, mention_count=c) for b, c in counter.most_common(5)]
    return Score(overall=overall, gpt4=gpt4, claude=claude, gemini=gemini, top_competitors=top)
