from __future__ import annotations

import ipaddress
import re

import idna
from pydantic import HttpUrl, TypeAdapter, ValidationError

INSTAGRAM_CAPTION_MAX = 2_200
INSTAGRAM_HASHTAG_MAX = 30
INSTAGRAM_CAROUSEL_MAX = 20
INSTAGRAM_HOOK_MAX = 180
INSTAGRAM_CTA_MAX = 300
INSTAGRAM_SLIDE_HEADLINE_MAX = 120
INSTAGRAM_SLIDE_BODY_MAX = 500
X_POST_WEIGHT_MAX = 280
X_MEDIA_PER_POST_MAX = 4
X_POSTS_MAX = 25
BLOG_SEO_DESCRIPTION_MAX = 160
BLOG_TITLE_MAX = 120
BLOG_SLUG_MAX = 120
BLOG_EXCERPT_MAX = 300
BLOG_BODY_MIN = 200
BLOG_TAG_MAX = 20
MEDIA_ALT_TEXT_MAX = 1_000
MEDIA_BRIEF_MAX = 2_000
MEDIA_PROMPT_MAX = 2_000

_URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)
_TRAILING_SENTENCE_PUNCTUATION = ".,!?;:'\""


def _url_owned_candidate(raw: str) -> str:
    candidate = raw.rstrip(_TRAILING_SENTENCE_PUNCTUATION)
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        while candidate.endswith(closing) and candidate.count(closing) > candidate.count(opening):
            candidate = candidate[:-1]
    return candidate


def _valid_http_url(candidate: str) -> bool:
    try:
        normalized = _HTTP_URL_ADAPTER.validate_python(candidate)
    except ValidationError:
        return False
    if normalized.username is not None or normalized.password is not None or normalized.host is None:
        return False
    host = normalized.host.rstrip(".")
    address_host = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ipaddress.ip_address(address_host)
    except ValueError:
        try:
            idna.encode(host, uts46=True, std3_rules=True)
        except idna.IDNAError:
            return False
    return True


def x_weighted_length(text: str) -> int:
    """Return NewsCraft's deterministic approximation of X weighted length.

    Each HTTP(S) URL counts as 23 characters. Punctuation immediately after a
    URL remains ordinary text, and every other Unicode code point counts once.
    The manual-platform warning remains authoritative because X can change its
    production rules independently of this local validator.
    """

    weighted = 0
    cursor = 0
    for match in _URL_PATTERN.finditer(text):
        raw = match.group(0)
        url = _url_owned_candidate(raw)
        if not _valid_http_url(url):
            continue
        url_end = match.start() + len(url)
        weighted += len(text[cursor : match.start()])
        weighted += 23
        cursor = url_end
    return weighted + len(text[cursor:])
