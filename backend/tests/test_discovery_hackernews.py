from datetime import UTC, datetime

import httpx

from app.discovery.hackernews import discover_hackernews


async def test_discover_hackernews_fetches_lists_and_filters_stories():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/topstories.json"):
            return httpx.Response(200, json=[1, 2, 3, 4, 5, 6])
        if url.endswith("/item/1.json"):
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "type": "story",
                    "title": "AI startup",
                    "url": "https://example.com/startup",
                    "time": 1783267200,
                    "score": 42,
                    "descendants": 7,
                },
            )
        if url.endswith("/item/2.json"):
            return httpx.Response(200, json={"id": 2, "type": "comment", "time": 1783267200})
        if url.endswith("/item/3.json"):
            return httpx.Response(200, json={"id": 3, "type": "story", "title": "Old", "time": 1783180800})
        if url.endswith("/item/4.json"):
            return httpx.Response(
                200,
                json={"id": 4, "type": "story", "title": "Ask HN", "text": "Launch advice?", "time": 1783267200},
            )
        if url.endswith("/item/5.json"):
            return httpx.Response(200, json={"id": 5, "type": "story", "title": "Title only", "time": 1783267200})
        if url.endswith("/item/6.json"):
            return httpx.Response(500)
        raise AssertionError(url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await discover_hackernews(
            client,
            datetime(2026, 7, 5, tzinfo=UTC),
            datetime(2026, 7, 6, tzinfo=UTC),
            lists=("topstories",),
            limit=10,
        )

    assert len(items) == 2
    assert items[0].source_platform == "hackernews"
    assert items[0].url == "https://example.com/startup"
    assert items[0].metadata["score"] == 42
    assert items[0].metadata["comment_count"] == 7
    assert items[1].url == "https://news.ycombinator.com/item?id=4"
    assert items[1].summary == "Launch advice?"
