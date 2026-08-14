"""How a source is fetched and parsed, shared by ingestion and health checks.

Both callers derive the same request URL from the same platform fields and
invoke the same parser with the same arguments; keeping one copy here stops
the two paths from drifting apart.
"""

from __future__ import annotations

from app.sources.base import ParsedSourcePayload, SourceFetchTarget
from app.sources.registry import parser_for_source


class MissingFetchTarget(ValueError):
    """A source carries no usable fetch URL for its platform."""


def source_request_url(source: SourceFetchTarget) -> str:
    if source.platform in {"rss", "atom"} and source.feed_url:
        return source.feed_url
    if source.platform == "telegram_public" and source.telegram_username:
        return f"https://t.me/s/{source.telegram_username}"
    raise MissingFetchTarget(f"Source {source.name} is missing fetch URL data")


def parse_source_payload(source: SourceFetchTarget, raw_text: str, request_url: str) -> ParsedSourcePayload:
    return parser_for_source(source)(raw_text, source, request_url)
