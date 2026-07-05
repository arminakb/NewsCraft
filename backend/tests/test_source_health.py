from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx

from app.db.models import Source
from app.ingestion.service import IngestionService


class FakeRepository:
    def __init__(self, sources):
        self.sources = sources
        self.finished = None

    async def create_run(self, trigger: str, parser_version: str):
        return SimpleNamespace(id=uuid4())

    async def finish_run(self, run_id, status: str, stats: dict, error: str | None = None) -> None:
        self.finished = {"run_id": run_id, "status": status, "stats": stats, "error": error}

    async def get_active_sources(self, platforms=None):
        if platforms:
            return [source for source in self.sources if source.platform in platforms and source.active]
        return [source for source in self.sources if source.active]

    async def save_raw_payload(self, **kwargs):
        return SimpleNamespace(id=uuid4(), parser_warnings=kwargs["parser_warnings"])

    async def upsert_source_item(self, **kwargs):
        return SimpleNamespace(id=uuid4(), content_item_id=None)

    async def upsert_content_item(self, **kwargs):
        return SimpleNamespace(id=uuid4())

    async def attach_identities(self, **_kwargs):
        return None

    async def upsert_media_assets(self, parsed_item):
        return [
            SimpleNamespace(
                id=uuid4(),
                normalized_url=candidate.normalized_url,
                kind=candidate.kind,
                source_field=candidate.source_field,
            )
            for candidate in parsed_item.media_candidates
        ]

    async def attach_item_media(self, **_kwargs):
        return None


class FakeSession:
    def __init__(self):
        self.flushed = False

    async def flush(self):
        self.flushed = True


def test_successful_ingest_marks_source_healthy():
    source = _rss_source()
    stats = _run_service(source, _mock_client(lambda _request: httpx.Response(200, text=_rss_xml())))

    assert stats["failed"] == 0
    assert source.health_status == "healthy"
    assert source.last_http_status == 200
    assert source.last_success_at is not None
    assert source.last_failure_at is None
    assert source.failure_count == 0
    assert source.last_error_type is None
    assert source.last_parse_count == 1
    assert source.last_suitable_count == 1
    assert source.last_media_count > 0


def test_http_403_marks_source_broken():
    source = _rss_source()
    stats = _run_service(source, _mock_client(lambda _request: httpx.Response(403, text="forbidden")))

    assert stats["failed"] == 1
    assert source.health_status == "broken"
    assert source.last_http_status == 403
    assert source.last_failure_at is not None
    assert source.failure_count == 1
    assert source.last_error_type == "http_403"


def test_http_404_marks_source_broken():
    source = _rss_source()
    _run_service(source, _mock_client(lambda _request: httpx.Response(404, text="missing")))

    assert source.health_status == "broken"
    assert source.last_http_status == 404
    assert source.failure_count == 1
    assert source.last_error_type == "http_404"


def test_dns_failure_marks_source_broken():
    source = _rss_source()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("DNS lookup failed", request=request)

    stats = _run_service(source, _mock_client(handler))

    assert stats["failed"] == 1
    assert source.health_status == "broken"
    assert source.last_http_status is None
    assert source.last_failure_at is not None
    assert source.failure_count == 1
    assert source.last_error_type == "ConnectError"
    assert "DNS lookup failed" in source.last_error_message


def test_malformed_feed_marks_source_degraded():
    source = _rss_source()
    stats = _run_service(source, _mock_client(lambda _request: httpx.Response(200, text="not xml")))

    assert stats["failed"] == 0
    assert source.health_status == "degraded"
    assert source.last_http_status == 200
    assert source.last_error_type == "malformed_feed"
    assert source.last_parse_count == 0
    assert source.last_suitable_count == 0


def test_zero_parsed_items_marks_source_degraded():
    source = _rss_source()
    empty_feed = "<rss><channel><title>Empty</title></channel></rss>"

    _run_service(source, _mock_client(lambda _request: httpx.Response(200, text=empty_feed)))

    assert source.health_status == "degraded"
    assert source.last_error_type == "zero_parsed_items"
    assert source.last_parse_count == 0
    assert source.last_suitable_count == 0


def _run_service(source: Source, client: httpx.AsyncClient) -> dict:
    import asyncio

    service = IngestionService(session=FakeSession(), repository=FakeRepository([source]), http_client=client)
    return asyncio.run(service.run_once(trigger="test"))


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _rss_source() -> Source:
    return Source(
        id=uuid4(),
        platform="rss",
        name="Example RSS",
        feed_url="https://example.com/feed.xml",
        source_group="ai",
        language_hint="en",
        default_timezone="UTC",
        active=True,
        failure_count=0,
        health_status="healthy",
    )


def _rss_xml() -> str:
    return Path("tests/fixtures/rss_google_ai.xml").read_text(encoding="utf-8")
