import json
from datetime import UTC, datetime

import httpx

from app.discovery.article_extractor import extract_article
from app.discovery.models import DiscoveryItem


async def test_extract_article_uses_html_metadata_and_body_text():
    html = """
<html>
  <head>
    <meta property="og:title" content="Open Graph Title">
    <meta property="og:image" content="https://example.com/main.jpg">
    <meta property="article:published_time" content="2026-07-05T12:00:00Z">
  </head>
  <body>
    <article>
      <p>This is the first paragraph of the extracted article.</p>
      <p>This is the second paragraph with enough useful detail.</p>
    </article>
  </body>
</html>
"""

    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    async with httpx.AsyncClient(transport=transport) as client:
        article = await extract_article(client, _discovery_item(summary="Short summary"))

    assert article.extraction_status == "ok"
    assert article.final_url == "https://example.com/story"
    assert article.title == "Open Graph Title"
    assert "first paragraph" in article.content_text
    assert article.image_url == "https://example.com/main.jpg"
    assert article.published_at == datetime(2026, 7, 5, 12, tzinfo=UTC)


async def test_extract_article_warns_when_extracted_text_is_shorter_than_discovery_summary():
    html = "<html><body><main><p>Short.</p></main></body></html>"

    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    async with httpx.AsyncClient(transport=transport) as client:
        article = await extract_article(client, _discovery_item(summary="A much longer discovery summary."))

    assert article.extraction_status == "ok"
    assert article.content_text == "Short."
    assert "short_extraction" in article.extraction_warnings


async def test_extract_article_returns_failed_result_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        article = await extract_article(client, _discovery_item(summary="Fallback summary"))

    assert article.extraction_status == "failed"
    assert article.title == "Discovery title"
    assert article.summary == "Fallback summary"
    assert article.content_text == "Fallback summary"


async def test_google_news_wrapper_falls_back_to_discovery_fields():
    html = """
<html>
  <head>
    <title>Google News</title>
    <meta
      name="description"
      content="Comprehensive up-to-date news coverage, aggregated from sources all over the world by Google News."
    >
  </head>
  <body>
    <main>
      <a href="https://news.google.com/rss/articles/example?oc=5">Generic wrapper snippet</a>
    </main>
  </body>
</html>
"""
    item = DiscoveryItem(
        source_platform="google_news",
        source_name="Google News RSS",
        external_id="https://news.google.com/rss/articles/example",
        title="Publisher headline about AI",
        url="https://news.google.com/rss/articles/example",
        summary="<a href='https://publisher.test/story'>Publisher summary with useful detail</a>",
        published_at=None,
        image_url="https://publisher.test/image.jpg",
        author=None,
        categories=["AI"],
        metadata={},
    )

    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    async with httpx.AsyncClient(transport=transport) as client:
        article = await extract_article(client, item)

    assert article.extraction_status == "fallback"
    assert article.title == "Publisher headline about AI"
    assert article.summary == "Publisher summary with useful detail"
    assert article.content_text == "Publisher summary with useful detail"
    assert article.image_url == "https://publisher.test/image.jpg"
    assert "weak_extraction" in article.extraction_warnings


async def test_google_news_wrapper_uses_summary_anchor_when_discovery_title_is_generic():
    html = "<html><head><title>Google News</title></head><body>Google News</body></html>"
    item = DiscoveryItem(
        source_platform="google_news",
        source_name="Google News RSS",
        external_id="https://news.google.com/rss/articles/example",
        title="Google News",
        url="https://news.google.com/rss/articles/example",
        summary="<a href='https://publisher.test/story'>Publisher headline</a>&nbsp;&nbsp;Publisher",
        published_at=None,
        image_url=None,
        author=None,
        categories=["AI"],
        metadata={},
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html))

    async with httpx.AsyncClient(transport=transport) as client:
        article = await extract_article(client, item)

    assert article.title == "Publisher headline"
    assert article.content_text == "Publisher headline Publisher"


async def test_google_news_wrapper_resolves_publisher_url_before_scraping():
    requests: list[tuple[str, str]] = []
    wrapper_html = """
<html>
  <body>
    <c-wiz>
      <div jscontroller="abc" data-n-a-sg="signature" data-n-a-ts="1783338279"></div>
    </c-wiz>
  </body>
</html>
"""
    publisher_html = """
<html>
  <head>
    <meta property="og:title" content="Publisher Title">
    <meta property="og:image" content="https://publisher.test/image.jpg">
  </head>
  <body>
    <article><p>Publisher article body with useful detail.</p></article>
  </body>
</html>
"""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        if request.url.host == "news.google.com" and request.method == "GET":
            assert request.headers["user-agent"] == "curl/8.17.0"
            return httpx.Response(200, text=wrapper_html)
        if request.url.host == "news.google.com" and request.method == "POST":
            return httpx.Response(
                200,
                text=")]}'\n\n"
                + json.dumps(
                    [
                        [
                            "wrb.fr",
                            "Fbv4je",
                            json.dumps(["garturlres", "https://publisher.test/story", 1]),
                            None,
                            None,
                            None,
                            "",
                        ]
                    ]
                ),
            )
        if str(request.url) == "https://publisher.test/story":
            return httpx.Response(200, text=publisher_html)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    item = DiscoveryItem(
        source_platform="google_news",
        source_name="Google News RSS",
        external_id="https://news.google.com/rss/articles/encoded-id",
        title="Discovery title",
        url="https://news.google.com/rss/articles/encoded-id?ceid=US%3Aen&gl=US&hl=en-US&oc=5",
        summary="Discovery summary",
        published_at=None,
        image_url=None,
        author=None,
        categories=["AI"],
        metadata={},
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        article = await extract_article(client, item)

    assert requests == [
        ("GET", "https://news.google.com/rss/articles/encoded-id?ceid=US%3Aen&gl=US&hl=en-US&oc=5"),
        ("POST", "https://news.google.com/_/DotsSplashUi/data/batchexecute"),
        ("GET", "https://publisher.test/story"),
    ]
    assert article.extraction_status == "ok"
    assert article.final_url == "https://publisher.test/story"
    assert article.title == "Publisher Title"
    assert "Publisher article body" in article.content_text
    assert article.image_url == "https://publisher.test/image.jpg"
    assert "google_news_resolved" in article.extraction_warnings


def _discovery_item(summary: str) -> DiscoveryItem:
    return DiscoveryItem(
        source_platform="gdelt",
        source_name="GDELT",
        external_id="https://example.com/story",
        title="Discovery title",
        url="https://example.com/story",
        summary=summary,
        published_at=None,
        image_url="https://example.com/fallback.jpg",
        author=None,
        categories=["AI"],
        metadata={},
    )
