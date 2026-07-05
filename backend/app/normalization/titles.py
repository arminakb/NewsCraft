from __future__ import annotations

import re
from dataclasses import dataclass

MEANINGFUL_RE = re.compile(r"[\w\u0600-\u06ff]", re.UNICODE)
DECORATION_RE = re.compile(r"^[^\w\u0600-\u06ff]+|[^\w\u0600-\u06ff]+$", re.UNICODE)
SENTENCE_SPLIT_RE = re.compile(r"[.!؟?]\s+|\n+")
WHITESPACE_RE = re.compile(r"\s+")
MAX_TITLE_LENGTH = 100


@dataclass(frozen=True)
class TitleNormalization:
    title: str
    quality: str
    was_generated: bool
    low_signal: bool = False


def normalize_telegram_title(title: str, body: str) -> TitleNormalization:
    clean_title = _clean(title)
    if _meaningful(clean_title):
        return TitleNormalization(title=clean_title, quality="good", was_generated=False)

    generated = _title_from_body(body)
    if not generated:
        return TitleNormalization(title=clean_title, quality="low_signal", was_generated=False, low_signal=True)
    return TitleNormalization(title=generated, quality="generated", was_generated=True)


def _title_from_body(body: str) -> str:
    for part in SENTENCE_SPLIT_RE.split(body or ""):
        candidate = _trim(_clean(part))
        if _meaningful(candidate):
            return candidate
    return ""


def _clean(value: str) -> str:
    return DECORATION_RE.sub("", WHITESPACE_RE.sub(" ", value or "")).strip()


def _trim(value: str) -> str:
    if len(value) <= MAX_TITLE_LENGTH:
        return value
    return value[:MAX_TITLE_LENGTH].rsplit(" ", 1)[0].strip() or value[:MAX_TITLE_LENGTH].strip()


def _meaningful(value: str) -> bool:
    return len(MEANINGFUL_RE.findall(value)) >= 4
