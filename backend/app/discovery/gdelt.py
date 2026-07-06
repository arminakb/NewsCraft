from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.discovery.models import DiscoveryItem
from app.normalization.dates import parse_source_datetime

GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


async def discover_gdelt(
    client: httpx.AsyncClient,
    start: datetime,
    end: datetime,
    topics: list[str],
    max_records: int = 100,
) -> list[DiscoveryItem]:
    response = await client.get(
        GDELT_DOC_API_URL,
        params={
            "query": _topic_query(topics),
            "mode": "ArtList",
            "format": "json",
            "startdatetime": _gdelt_datetime(start),
            "enddatetime": _gdelt_datetime(end),
            "maxrecords": str(max_records),
        },
    )
    response.raise_for_status()
    payload = response.json()
    return [_article_to_item(article, topics) for article in payload.get("articles", []) if article.get("url")]


def _topic_query(topics: list[str]) -> str:
    cleaned = [topic.strip() for topic in topics if topic.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return "(" + " OR ".join(cleaned) + ")"


def _gdelt_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def _article_to_item(article: dict[str, Any], topics: list[str]) -> DiscoveryItem:
    url = article["url"]
    published_at = _parse_gdelt_date(article.get("seendate"))
    return DiscoveryItem(
        source_platform="gdelt",
        source_name="GDELT",
        external_id=url,
        title=str(article.get("title") or "").strip(),
        url=url,
        summary=str(article.get("summary") or ""),
        published_at=published_at,
        image_url=article.get("socialimage"),
        author=None,
        categories=list(topics),
        metadata={
            "domain": article.get("domain"),
            "source_country": article.get("sourcecountry"),
            "language": article.get("language"),
            "raw": article,
        },
    )


def _parse_gdelt_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if len(value) == 14 and value.isdigit():
            return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        return parse_source_datetime(value)[0]
    except (ValueError, TypeError, OverflowError):
        return None
