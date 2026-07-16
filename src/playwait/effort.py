"""Local heuristics: score how much thought a user reply likely took (0..1)."""

from __future__ import annotations

import math
import re

_LOW_EFFORT = frozenset(
    {
        "y",
        "n",
        "yes",
        "no",
        "ok",
        "okay",
        "k",
        "kk",
        "lgtm",
        "ship",
        "ship it",
        "go",
        "do it",
        "sure",
        "thanks",
        "thx",
        "1",
        "2",
        "3",
        "a",
        "b",
        "c",
    }
)

_EFFORT_PHRASES = (
    "because",
    "instead",
    "explain",
    "consider",
    "implement",
    "refactor",
    "redesign",
    "architecture",
    "trade-off",
    "tradeoff",
    "should we",
    "don't",
    "however",
    "alternatively",
    "make sure",
    "rather than",
    "in other words",
)


def score_effort(prompt: str) -> float:
    """Return 0.0 (trivial) .. 1.0 (high effort) from reply text alone."""
    text = (prompt or "").strip()
    if not text:
        return 0.0

    lower = text.lower().strip()
    if lower in _LOW_EFFORT:
        return 0.0
    # Single short token / option pick
    if "\n" not in text and len(text) <= 12 and " " not in text.strip():
        return 0.05
    if "\n" not in text and len(text) < 40 and not any(p in lower for p in _EFFORT_PHRASES):
        return min(0.25, 0.05 + len(text) / 200.0)

    score = 0.0
    # Length (log): ~0.4 around a few hundred chars, caps ~0.5
    score += min(0.5, math.log1p(len(text)) / math.log1p(1200.0) * 0.5)

    lines = text.count("\n") + 1
    score += min(0.2, max(0, lines - 1) * 0.035)

    if "```" in text or re.search(r"(?m)^ {4,}|\t", text):
        score += 0.15

    phrase_hits = sum(1 for p in _EFFORT_PHRASES if p in lower)
    score += min(0.2, phrase_hits * 0.045)

    if "?" in text:
        score += 0.05

    # Bullet / numbered list suggests structured thought
    if re.search(r"(?m)^\s*([-*]|\d+\.)\s+", text):
        score += 0.08

    return max(0.0, min(1.0, score))


def cooldown_seconds_for_effort(
    score: float,
    *,
    minimum: int = 30,
    maximum: int = 180,
) -> int:
    """Map effort score to inclusive cool-down seconds."""
    lo = max(1, int(minimum))
    hi = max(lo, int(maximum))
    s = max(0.0, min(1.0, float(score)))
    return int(round(lo + s * (hi - lo)))
