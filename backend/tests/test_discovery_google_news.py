from datetime import UTC, datetime

import httpx

from app.discovery.google_news import discover_google_news_rss


async def test_discover_google_news_rss_fetches_topics_and_filters_dates():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=_google_news_feed(), headers={"content-type": "application/rss+xml"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await discover_google_news_rss(
            client,
            datetime(2026, 7, 5, tzinfo=UTC),
            datetime(2026, 7, 6, tzinfo=UTC),
            ["AI", "economy"],
            language="en",
            region="US",
        )

    assert len(requests) == 2
    assert all(str(request.url).startswith("https://news.google.com/rss/search") for request in requests)
    first_query = requests[0].url.params["q"]
    assert "AI" in first_query
    assert "after:2026-07-05" in first_query
    assert "before:2026-07-06" in first_query
    assert [item.title for item in items] == ["Inside AI"]
    assert items[0].source_platform == "google_news"
    assert items[0].url == "https://news.google.com/articles/example"


def _google_news_feed() -> str:
    return """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <item>
      <title>Inside AI</title>
      <link>https://news.google.com/articles/example</link>
      <guid>cluster-1</guid>
      <description>AI summary</description>
      <pubDate>Sun, 05 Jul 2026 12:00:00 GMT</pubDate>
      <source url="https://example.com">Example</source>
    </item>
    <item>
      <title>Undated AI</title>
      <link>https://news.google.com/articles/undated</link>
      <guid>cluster-undated</guid>
      <description>Undated summary</description>
    </item>
    <item>
      <title>Old AI</title>
      <link>https://news.google.com/articles/old</link>
      <guid>cluster-old</guid>
      <description>Old summary</description>
      <pubDate>Sat, 04 Jul 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
