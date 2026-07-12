from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.normalization.urls import normalize_url


@dataclass(frozen=True, slots=True)
class GroupingInput:
    content_item_id: str
    title: str
    canonical_url: str | None
    published_at: datetime


@dataclass(frozen=True, slots=True)
class GroupingDecision:
    grouped: bool
    score: float
    reason: Literal["canonical_url", "title_similarity", "insufficient_similarity"]


def normalize_title(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    without_punctuation = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in normalized
    )
    return frozenset(token for token in without_punctuation.split() if len(token) >= 2)


def token_jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def decide_group(left: GroupingInput, right: GroupingInput) -> GroupingDecision:
    left_url = normalize_url(left.canonical_url) if left.canonical_url else None
    right_url = normalize_url(right.canonical_url) if right.canonical_url else None
    if left_url and left_url == right_url:
        return GroupingDecision(grouped=True, score=1.0, reason="canonical_url")

    score = token_jaccard(normalize_title(left.title), normalize_title(right.title))
    hours = abs((left.published_at - right.published_at).total_seconds()) / 3600
    if hours <= 72 and score >= 0.72:
        return GroupingDecision(grouped=True, score=score, reason="title_similarity")
    return GroupingDecision(grouped=False, score=score, reason="insufficient_similarity")
