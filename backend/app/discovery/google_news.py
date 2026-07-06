from __future__ import annotations

from datetime import datetime
from typing import Any

import feedparser
import httpx

from app.discovery.models import DiscoveryItem
from app.normalization.dates import parse_source_datetime

GOOGLE_NEWS_RSS_SEARCH_URL = "https://news.google.com/rss/search"


async def discover_google_news_rss(
    client: httpx.AsyncClient,
    start: datetime,
    end: datetime,
    topics: list[str],
    language: str = "en",
    region: str = "US",
) -> list[DiscoveryItem]:
    items: list[DiscoveryItem] = []
    seen_urls: set[str] = set()
    for topic in topics:
        query = f"{topic} after:{start.date().isoformat()} before:{end.date().isoformat()}"
        response = await client.get(
            GOOGLE_NEWS_RSS_SEARCH_URL,
            params={
                "q": query,
                "hl": f"{language}-{region}",
                "gl": region,
                "ceid": f"{region}:{language}",
            },
        )
        response.raise_for_status()
        feed = feedparser.parse(response.text)
        for entry in feed.entries:
            item = _entry_to_item(entry, topic, start, end)
            if item is not None:
                if item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                items.append(item)
    return items


def _entry_to_item(entry: Any, topic: str, start: datetime, end: datetime) -> DiscoveryItem | None:
    published_at = _entry_published_at(entry)
    if published_at is None or not (start <= published_at < end):
        return None
    link = entry.get("link")
    if not link:
        return None
    external_id = entry.get("id") or entry.get("guid") or link
    source = entry.get("source") or {}
    source_name = source.get("title") or "Google News RSS"
    return DiscoveryItem(
        source_platform="google_news",
        source_name=str(source_name),
        external_id=str(external_id),
        title=str(entry.get("title") or "").strip(),
        url=str(link),
        summary=str(entry.get("summary") or entry.get("description") or ""),
        published_at=published_at,
        image_url=None,
        author=entry.get("author"),
        categories=[topic],
        metadata={"google_news": True, "raw_keys": sorted(entry.keys())},
    )


def _entry_published_at(entry: Any) -> datetime | None:
    raw = entry.get("published") or entry.get("updated") or entry.get("created")
    if raw:
        try:
            return parse_source_datetime(str(raw))[0]
        except (ValueError, TypeError, OverflowError):
            return None
    parsed_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_tuple:
        from datetime import UTC

        return datetime(*parsed_tuple[:6], tzinfo=UTC)
    return None
