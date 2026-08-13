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
    parser = parser_for_source(source)
    if source.platform == "telegram_public":
        return parser(raw_text, channel=source.telegram_username)
    # parser_for_source has already rejected every platform except rss/atom.
    return parser(
        raw_text,
        source_name=source.name,
        source_url=source.feed_url or request_url,
        default_timezone=source.default_timezone or "UTC",
    )
