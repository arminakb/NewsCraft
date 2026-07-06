from __future__ import annotations

from datetime import UTC, datetime
from html import unescape

import httpx
from bs4 import BeautifulSoup

from app.discovery.models import DiscoveryItem

HACKER_NEWS_API_BASE = "https://hacker-news.firebaseio.com/v0"


async def discover_hackernews(
    client: httpx.AsyncClient,
    start: datetime,
    end: datetime,
    lists: tuple[str, ...] = ("topstories", "newstories", "beststories"),
    limit: int = 100,
) -> list[DiscoveryItem]:
    items: list[DiscoveryItem] = []
    seen_ids: set[int] = set()
    for list_name in lists:
        response = await client.get(f"{HACKER_NEWS_API_BASE}/{list_name}.json")
        response.raise_for_status()
        for story_id in response.json()[:limit]:
            if story_id in seen_ids:
                continue
            seen_ids.add(story_id)
            try:
                item = await _fetch_story(client, int(story_id), list_name, start, end)
            except httpx.HTTPError:
                continue
            if item is not None:
                items.append(item)
    return items


async def _fetch_story(
    client: httpx.AsyncClient,
    story_id: int,
    list_name: str,
    start: datetime,
    end: datetime,
) -> DiscoveryItem | None:
    response = await client.get(f"{HACKER_NEWS_API_BASE}/item/{story_id}.json")
    response.raise_for_status()
    story = response.json()
    if story.get("type") != "story":
        return None
    published_at = datetime.fromtimestamp(int(story.get("time", 0)), tz=UTC)
    if not (start <= published_at < end):
        return None
    text = _clean_html(story.get("text") or "")
    url = story.get("url") or (f"https://news.ycombinator.com/item?id={story_id}" if text else None)
    if not url:
        return None
    return DiscoveryItem(
        source_platform="hackernews",
        source_name="Hacker News",
        external_id=str(story_id),
        title=str(story.get("title") or "").strip(),
        url=url,
        summary=text,
        published_at=published_at,
        image_url=None,
        author=story.get("by"),
        categories=["hackernews", list_name],
        metadata={
            "score": story.get("score"),
            "comment_count": story.get("descendants", 0),
            "hn_list": list_name,
            "hn_url": f"https://news.ycombinator.com/item?id={story_id}",
        },
    )


def _clean_html(value: str) -> str:
    if not value:
        return ""
    return unescape(BeautifulSoup(value, "lxml").get_text(" ", strip=True))
