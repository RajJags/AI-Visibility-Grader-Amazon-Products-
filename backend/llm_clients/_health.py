"""
Circuit breaker for LLM providers and models.

Module-level state persists for the lifetime of the server process, so a
model that rate-limited on request N is automatically skipped on request N+1
(for COOLDOWN seconds) instead of burning 3-15 s re-discovering the failure.
"""

from __future__ import annotations
import time

_failures: dict[str, float] = {}   # key -> unix timestamp of last failure
_COOLDOWN = 35.0                    # seconds before retrying a failed model


def is_healthy(key: str) -> bool:
    t = _failures.get(key)
    return t is None or (time.time() - t) > _COOLDOWN


def mark_failed(key: str) -> None:
    _failures[key] = time.time()


def mark_ok(key: str) -> None:
    _failures.pop(key, None)


def filter_healthy(models: list[str]) -> list[str]:
    """Return the subset of models not currently in cooldown."""
    return [m for m in models if is_healthy(m)]


def best_first(models: list[str]) -> list[str]:
    """Return models sorted: healthy first (preserving original order), failed last."""
    healthy = [m for m in models if is_healthy(m)]
    failed  = [m for m in models if not is_healthy(m)]
    return healthy + failed
