from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.core import safe_http
from app.core.config import Settings
from app.core.outbound_proxy import OutboundProxyPolicy
from app.core.safe_http import SafeHttpClient
from app.sources.icon_discovery import (
    SourceIconDiscoveryService,
    SourceIconTarget,
    extract_feed_identity,
    validate_icon_url,
)

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\x00IEND\xaeB`\x82"
)
JPEG_1X1 = b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
SVG_24 = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M1 1h22v22H1z"/></svg>'


async def _public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


def _service(handler, config: Settings | None = None):
    def factory():
        return SafeHttpClient(
            transport=httpx.MockTransport(handler),
            resolver=_public_resolver,
            max_response_bytes=2_000_000,
        )

    return SourceIconDiscoveryService(config=config or Settings(), http_client_factory=factory)


def test_feed_identity_prioritizes_image_and_uses_publisher_metadata():
    identity = extract_feed_identity(
        """
        <rss version="2.0"><channel>
          <link>https://publisher.example/news</link>
          <image><url>/brand/logo.png</url></image>
          <item><source url="https://intermediary.example/feed" /></item>
        </channel></rss>
        """,
        "https://intermediary.example/feed.xml",
    )

    assert identity.publisher_url == "https://publisher.example/news"
    assert identity.candidates[0].source == "feed_image"
    assert identity.candidates[0].url == "https://intermediary.example/brand/logo.png"


@pytest.mark.asyncio
async def test_discovery_falls_back_to_relative_declared_website_icon():
    feed = b"""<rss version="2.0"><channel><link>https://publisher.test/</link></channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed":
            return httpx.Response(200, content=feed, headers={"content-type": "application/rss+xml"})
        if request.url.path == "/":
            return httpx.Response(
                200,
                content=b'<html><head><link rel="shortcut icon" href="/icons/logo.svg"></head></html>',
                headers={"content-type": "text/html"},
            )
        if request.url.path == "/icons/logo.svg":
            return httpx.Response(200, content=SVG_24, headers={"content-type": "image/svg+xml"})
        return httpx.Response(404, content=b"missing")

    result = await _service(handler).discover(
        SourceIconTarget(uuid4(), "atom", "https://feed.test/feed", None)
    )

    assert result.status == "resolved"
    assert result.icon_source == "website_shortcut_icon"
    assert result.original_url == "https://publisher.test/icons/logo.svg"
    assert result.width == 24
    assert result.height == 24


@pytest.mark.asyncio
async def test_discovery_uses_conventional_favicon_after_declared_candidates_fail():
    feed = b"""<rss version="2.0"><channel><link>https://publisher.test/</link></channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed":
            return httpx.Response(200, content=feed, headers={"content-type": "application/rss+xml"})
        if request.url.path == "/":
            return httpx.Response(200, content=b"<html><head></head></html>", headers={"content-type": "text/html"})
        if request.url.path == "/favicon.ico":
            return httpx.Response(200, content=PNG_1X1, headers={"content-type": "image/x-icon"})
        return httpx.Response(404, content=b"missing")

    result = await _service(handler).discover(
        SourceIconTarget(uuid4(), "rss", "https://feed.test/feed", None)
    )

    assert result.status == "resolved"
    assert result.icon_source == "conventional_favicon"
    assert result.mime_type == "image/png"


@pytest.mark.asyncio
async def test_discovery_accepts_jpg_alias_for_jpeg_bytes():
    feed = b"""<rss version=\"2.0\"><channel><link>https://publisher.test/</link><image><url>/logo.jpg</url></image></channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed":
            return httpx.Response(200, content=feed, headers={"content-type": "application/rss+xml"})
        if request.url.path == "/logo.jpg":
            return httpx.Response(200, content=JPEG_1X1, headers={"content-type": "image/jpg"})
        return httpx.Response(404, content=b"missing")

    result = await _service(handler).discover(
        SourceIconTarget(uuid4(), "rss", "https://feed.test/feed", None)
    )

    assert result.status == "resolved"
    assert result.icon_source == "feed_image"
    assert result.mime_type == "image/jpeg"
    assert result.width == 1
    assert result.height == 1


@pytest.mark.asyncio
async def test_conventional_favicon_follows_website_redirect_for_non_html():
    feed = b"""<rss version="2.0"><channel><link>https://publisher.test/</link></channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "feed.test":
            return httpx.Response(200, content=feed, headers={"content-type": "application/rss+xml"})
        if request.url.host == "publisher.test":
            return httpx.Response(301, headers={"location": "https://www.publisher.test/"})
        if request.url.host == "www.publisher.test":
            if request.url.path == "/":
                return httpx.Response(200, content=b"landing", headers={"content-type": "text/plain"})
            if request.url.path == "/favicon.ico":
                return httpx.Response(200, content=PNG_1X1, headers={"content-type": "image/x-icon"})
        return httpx.Response(404, content=b"missing")

    result = await _service(handler).discover(
        SourceIconTarget(uuid4(), "rss", "https://feed.test/feed", None)
    )

    assert result.status == "resolved"
    assert result.icon_source == "conventional_favicon"
    assert result.original_url == "https://www.publisher.test/favicon.ico"


@pytest.mark.asyncio
async def test_oversized_server_error_page_stays_retryable():
    oversized_error_page = b"x" * 20_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            content=oversized_error_page,
            headers={"content-type": "text/html"},
        )

    config = Settings(source_icon_discovery_max_bytes=16_384)
    result = await _service(handler, config).discover(
        SourceIconTarget(uuid4(), "rss", "https://feed.test/feed", None)
    )

    assert result.status == "retryable"
    assert result.error == "http_503"


def test_icon_url_policy_rejects_local_private_and_metadata_targets():
    for value in (
        "file:///tmp/logo.png",
        "http://127.0.0.1/logo.png",
        "http://169.254.169.254/latest/meta-data/",
        "https://metadata.google.internal/logo.png",
        "https://service.internal/logo.png",
    ):
        with pytest.raises(RuntimeError):
            validate_icon_url(value)


@pytest.mark.asyncio
async def test_icon_fetch_uses_news_craft_outbound_proxy_policy(monkeypatch):
    captured: dict[str, object] = {}

    class FakePolicyTransport(httpx.AsyncBaseTransport):
        def __init__(self, policy, pinned_backend):
            captured["policy"] = policy
            captured["pinned_backend"] = pinned_backend

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, content=PNG_1X1, headers={"content-type": "image/png"}, request=request)

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(safe_http, "_ProxyAwarePinnedTransport", FakePolicyTransport)
    policy = OutboundProxyPolicy.from_environment({"ALL_PROXY": "http://proxy.example:8080"})

    async with SafeHttpClient(proxy_policy=policy, resolver=_public_resolver) as client:
        response = await client.get("https://publisher.example/favicon.png")

    assert response.status_code == 200
    assert captured["policy"] is policy
    assert captured["url"] == "https://publisher.example/favicon.png"
