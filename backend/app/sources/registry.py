from collections.abc import Callable

from app.db.models import Source
from app.sources.rss import parse_rss_feed
from app.sources.telegram_public import parse_public_telegram_page


def parser_for_source(source: Source) -> Callable:
    if source.platform in {"rss", "atom"}:
        return parse_rss_feed
    if source.platform == "telegram_public":
        return parse_public_telegram_page
    raise ValueError(f"Unsupported source platform: {source.platform}")
