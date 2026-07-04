import requests

from newscraft.ingestion.rss_public import parse_rss_feed, parsed_rss_items_to_articles
from newscraft.ingestion.telegram_public import parse_public_telegram_page, parsed_telegram_items_to_articles

TIMEOUT = 15


def fetch_public_rss_sources(sources=None, limit_per_source=20, **_):
    articles = []
    for source in sources or []:
        url = _value(source, "url")
        if not url:
            continue
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        payload = parse_rss_feed(
            response.text,
            source_name=_value(source, "name") or url,
            source_url=url,
            default_timezone=(_value(source, "config") or {}).get("default_timezone", "UTC"),
        )
        articles.extend(parsed_rss_items_to_articles(payload)[:limit_per_source])
    return articles


def fetch_public_telegram_channels(channels=None, limit_per_channel=20, **_):
    articles = []
    for channel in channels or []:
        username = _value(channel, "telegram_username") or _value(channel, "name")
        if not username:
            continue
        response = requests.get(f"https://t.me/s/{username}", timeout=TIMEOUT)
        response.raise_for_status()
        payload = parse_public_telegram_page(response.text, channel=username)
        articles.extend(parsed_telegram_items_to_articles(payload)[:limit_per_channel])
    return articles


def _value(source, key):
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)
