from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from hashlib import sha256

import httpx
import pytest

from app.discovery.models import ExtractedArticle
from app.normalization.urls import normalize_url
from app.research.safe_fetch import SafeArticleFetcher, SafeArticleFetchError
from app.stories.manual_intake import MAX_MANUAL_RESPONSE_BYTES

PUBLIC_IP = "93.184.216.34"


async def public_resolver(host: str) -> list[str]:
    return [PUBLIC_IP]


class QueueTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses: list[tuple[int, dict[str, str], bytes]]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, headers, body = self.responses.pop(0)
        return httpx.Response(status, headers=headers, content=body, request=request)


class ChunkedStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"a" * MAX_MANUAL_RESPONSE_BYTES
        yield b"b"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/report",
        "http://localhost/report",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.1/report",
        "http://172.16.0.1/report",
        "http://192.168.1.1/report",
        "http://[::1]/report",
        "file:///etc/passwd",
        "https://user:secret@news.example/report",
    ],
)
async def test_safe_fetch_rejects_non_public_or_credentialed_urls(url: str) -> None:
    fetcher = SafeArticleFetcher(resolver=public_resolver, transport=QueueTransport([]))

    with pytest.raises(SafeArticleFetchError, match="Article fetch rejected"):
        await fetcher.fetch(url)


async def test_safe_fetch_rejects_any_non_global_dns_answer() -> None:
    async def mixed_resolver(host: str) -> list[str]:
        return [PUBLIC_IP, "127.0.0.1"]

    fetcher = SafeArticleFetcher(resolver=mixed_resolver, transport=QueueTransport([]))

    with pytest.raises(SafeArticleFetchError, match="Article fetch rejected"):
        await fetcher.fetch("https://news.example/report")


async def test_safe_fetch_revalidates_redirect_target() -> None:
    requested: list[str] = []

    async def send(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"}, request=request)

    fetcher = SafeArticleFetcher(resolver=public_resolver, transport=httpx.MockTransport(send))

    with pytest.raises(SafeArticleFetchError, match="Article fetch rejected"):
        await fetcher.fetch("https://news.example/start")

    assert requested == ["https://news.example/start"]


async def test_safe_fetch_allows_five_redirects_but_not_six() -> None:
    responses = [
        (302, {"Location": f"https://news.example/hop-{index}"}, b"") for index in range(1, 7)
    ]
    fetcher = SafeArticleFetcher(resolver=public_resolver, transport=QueueTransport(responses))

    with pytest.raises(SafeArticleFetchError, match="Too many article redirects"):
        await fetcher.fetch("https://news.example/start")


async def test_safe_fetch_caps_decompressed_stream_at_five_mib() -> None:
    async def send(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=ChunkedStream(), request=request)

    fetcher = SafeArticleFetcher(resolver=public_resolver, transport=httpx.MockTransport(send))

    with pytest.raises(SafeArticleFetchError, match="Article response is too large"):
        await fetcher.fetch("https://news.example/report")


async def test_safe_fetch_maps_extraction_failure_to_typed_error() -> None:
    transport = QueueTransport([(503, {}, b"unavailable")])
    fetcher = SafeArticleFetcher(resolver=public_resolver, transport=transport)

    with pytest.raises(SafeArticleFetchError, match="Article extraction failed"):
        await fetcher.fetch("https://news.example/report")


async def test_safe_fetch_returns_complete_database_free_source() -> None:
    html = b"<html><head><title>Fetched title</title></head><body><article>Fetched article body</article></body></html>"
    transport = QueueTransport([(200, {"Content-Type": "text/html"}, html)])

    source = await SafeArticleFetcher(resolver=public_resolver, transport=transport).fetch(
        "https://news.example/report"
    )

    assert str(source.url) == "https://news.example/report"
    assert source.retrieved_at.tzinfo is not None
    assert source.content_text == "Fetched article body"
    assert source.content_sha256 == sha256(source.content_text.encode()).hexdigest()
    assert source.evidence_key == f"url:{normalize_url(str(source.url))}:{source.content_sha256}"
    assert source.title == "Fetched title"
    assert source.publisher is None
    assert source.extraction_status == "ok"
    assert "evidence_snapshot_id" not in source.model_dump()


async def test_safe_fetch_uses_exact_final_accepted_url_after_public_redirect() -> None:
    transport = QueueTransport(
        [
            (302, {"Location": "https://final.example/report?b=2&a=1"}, b""),
            (200, {}, b"<article>Final article body</article>"),
        ]
    )

    source = await SafeArticleFetcher(resolver=public_resolver, transport=transport).fetch(
        "https://news.example/start"
    )

    assert str(source.url) == "https://final.example/report?b=2&a=1"
    assert [str(request.url) for request in transport.requests] == [
        "https://news.example/start",
        "https://final.example/report?b=2&a=1",
    ]


async def test_same_url_with_changed_content_creates_a_new_evidence_key() -> None:
    transport = QueueTransport(
        [
            (200, {}, b"<article>Version one article body</article>"),
            (200, {}, b"<article>Version two article body</article>"),
        ]
    )
    fetcher = SafeArticleFetcher(resolver=public_resolver, transport=transport)

    first = await fetcher.fetch("https://news.example/report")
    second = await fetcher.fetch("https://news.example/report")

    assert first.url == second.url
    assert first.content_sha256 != second.content_sha256
    assert first.evidence_key == f"url:{normalize_url(str(first.url))}:{first.content_sha256}"
    assert second.evidence_key == f"url:{normalize_url(str(second.url))}:{second.content_sha256}"
    assert first.evidence_key != second.evidence_key


async def test_safe_fetch_normalizes_extracted_whitespace_without_using_author_as_publisher() -> None:
    html = b"""
    <html><head><meta name="author" content="Named Author"></head>
    <body><article>Line one\n\n   Line two</article></body></html>
    """
    source = await SafeArticleFetcher(
        resolver=public_resolver,
        transport=QueueTransport([(200, {}, html)]),
    ).fetch("https://news.example/report")

    assert source.content_text == "Line one Line two"
    assert source.publisher is None


def extracted_article(*, final_url: str = "https://news.example/report") -> ExtractedArticle:
    return ExtractedArticle(
        url="https://news.example/report",
        final_url=final_url,
        title="Title",
        summary="",
        content_text="Article body",
        content_html=None,
        author=None,
        published_at=None,
        image_url=None,
        extraction_status="ok",
    )


async def test_safe_fetch_redacts_unexpected_extractor_error() -> None:
    async def fail_extraction(client: object, item: object) -> ExtractedArticle:
        raise ValueError("secret-token-value")

    fetcher = SafeArticleFetcher(
        resolver=public_resolver,
        transport=QueueTransport([]),
        extractor=fail_extraction,
    )

    with pytest.raises(SafeArticleFetchError, match="^Article extraction failed$") as caught:
        await fetcher.fetch("https://news.example/report")

    assert "secret-token-value" not in str(caught.value)


@pytest.mark.parametrize(
    "final_url",
    [
        "not a URL",
        "http://127.0.0.1/private",
        "http://[::1]/private",
        "https://user:secret@news.example/report",
    ],
)
async def test_safe_fetch_revalidates_extractor_final_url(final_url: str) -> None:
    async def fabricate_final_url(client: object, item: object) -> ExtractedArticle:
        return extracted_article(final_url=final_url)

    fetcher = SafeArticleFetcher(
        resolver=public_resolver,
        transport=QueueTransport([]),
        extractor=fabricate_final_url,
    )

    with pytest.raises(SafeArticleFetchError, match="^Article fetch rejected$"):
        await fetcher.fetch("https://news.example/report")


async def test_safe_fetch_wraps_materialization_validation_without_leaking_details() -> None:
    async def invalid_materialization(client: object, item: object) -> ExtractedArticle:
        article = extracted_article()
        article.title = "secret-title" * 100
        return article

    fetcher = SafeArticleFetcher(
        resolver=public_resolver,
        transport=QueueTransport([]),
        extractor=invalid_materialization,
    )

    with pytest.raises(SafeArticleFetchError, match="^Article materialization failed$") as caught:
        await fetcher.fetch("https://news.example/report")

    assert "secret-title" not in str(caught.value)


async def test_safe_fetch_wraps_malformed_extracted_content() -> None:
    async def malformed_content(client: object, item: object) -> ExtractedArticle:
        article = extracted_article()
        article.content_text = None
        return article

    fetcher = SafeArticleFetcher(
        resolver=public_resolver,
        transport=QueueTransport([]),
        extractor=malformed_content,
    )

    with pytest.raises(SafeArticleFetchError, match="^Article materialization failed$"):
        await fetcher.fetch("https://news.example/report")


@pytest.mark.parametrize("interrupt", [asyncio.CancelledError(), SystemExit(2)])
async def test_safe_fetch_preserves_process_control_exceptions(interrupt: BaseException) -> None:
    async def interrupted(client: object, item: object) -> ExtractedArticle:
        raise interrupt

    fetcher = SafeArticleFetcher(
        resolver=public_resolver,
        transport=QueueTransport([]),
        extractor=interrupted,
    )

    with pytest.raises(type(interrupt)):
        await fetcher.fetch("https://news.example/report")


def test_safe_fetch_depends_on_neutral_safe_http_boundary() -> None:
    module = __import__("app.research.safe_fetch", fromlist=["*"])
    source = inspect.getsource(module)
    assert "app.core.safe_http" in source
    assert "app.stories.manual_intake" not in source
