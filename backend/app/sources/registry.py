from collections.abc import Callable

from app.sources.base import ParsedSourcePayload, SourceFetchTarget
from app.sources.rss import parse_rss_feed
from app.sources.telegram_public import parse_public_telegram_page

SourceParser = Callable[[str, SourceFetchTarget, str], ParsedSourcePayload]


def _parse_rss(raw_text: str, source: SourceFetchTarget, request_url: str) -> ParsedSourcePayload:
    return parse_rss_feed(
        raw_text,
        source_name=source.name,
        source_url=source.feed_url or request_url,
        default_timezone=source.default_timezone or "UTC",
    )


def _parse_telegram(raw_text: str, source: SourceFetchTarget, request_url: str) -> ParsedSourcePayload:
    del request_url
    if source.telegram_username is None:
        raise ValueError(f"Source {source.name} is missing a Telegram username")
    return parse_public_telegram_page(raw_text, channel=source.telegram_username)


def parser_for_source(source: SourceFetchTarget) -> SourceParser:
    if source.platform in {"rss", "atom"}:
        return _parse_rss
    if source.platform == "telegram_public":
        return _parse_telegram
    raise ValueError(f"Unsupported source platform: {source.platform}")
