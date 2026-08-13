from uuid import uuid4

import httpx

from app.db.models import Source
from app.sources.health import check_source_health


async def test_rss_health_check_validates_real_response_content() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "application/rss+xml"},
            text="""<?xml version="1.0"?>
            <rss version="2.0"><channel><title>Example</title><item>
              <guid>item-1</guid><title>Working feed</title>
              <link>https://example.com/items/1</link>
              <description>Valid source content</description>
            </item></channel></rss>""",
        )

    source = Source(
        id=uuid4(),
        platform="rss",
        name="Example RSS",
        feed_url="https://example.com/feed.xml",
        source_group="test",
        language_hint="en",
        default_timezone="UTC",
        active=True,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await check_source_health(source, http_client=client)

    assert result.status == "healthy"
    assert result.http_status == 200
    assert result.failure_reason is None
    assert result.checked_at.tzinfo is not None


async def test_health_check_marks_invalid_source_response_broken() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            text="<html><body>not a feed</body></html>",
        )

    source = Source(
        id=uuid4(),
        platform="rss",
        name="Invalid RSS",
        feed_url="https://example.com/feed.xml",
        source_group="test",
        language_hint="en",
        default_timezone="UTC",
        active=True,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await check_source_health(source, http_client=client)

    assert result.status == "broken"
    assert result.http_status == 200
    assert result.failure_reason == "Response contained no valid source items."
