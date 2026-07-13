from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx

from app.db.models import Source
from app.ingestion.service import IngestionService


class FakeRepository:
    def __init__(self, sources):
        self.sources = sources
        self.events = []
        self.finished = None
        self.media_candidate_count = 0
        self.raw_payload = None

    async def create_run(self, trigger: str, parser_version: str):
        self.events.append(("create_run", trigger, parser_version))
        return SimpleNamespace(id=uuid4())

    async def finish_run(self, run_id, status: str, stats: dict, error: str | None = None) -> None:
        self.finished = {"run_id": run_id, "status": status, "stats": stats, "error": error}
        self.events.append(("finish_run", status))

    async def get_active_sources(self, platforms=None):
        if platforms:
            return [source for source in self.sources if source.platform in platforms]
        return self.sources

    async def save_raw_payload(self, **kwargs):
        self.events.append(("raw_payload", kwargs["request_url"]))
        self.raw_payload = SimpleNamespace(
            id=uuid4(),
            parser_warnings=kwargs["parser_warnings"],
        )
        return self.raw_payload

    async def upsert_source_item(self, **kwargs):
        self.events.append(("source_item", kwargs["parsed_item"].external_id_norm))
        return SimpleNamespace(id=uuid4(), content_item_id=None)

    async def upsert_content_item(self, **kwargs):
        self.events.append(("content_item", kwargs["parsed_item"].title))
        return SimpleNamespace(id=uuid4())

    async def attach_identities(self, **kwargs):
        self.events.append(("identities", len(kwargs["identities"])))

    async def upsert_media_assets(self, parsed_item):
        self.media_candidate_count += len(parsed_item.media_candidates)
        self.events.append(("media_assets", len(parsed_item.media_candidates)))
        return [
            SimpleNamespace(
                id=uuid4(),
                normalized_url=candidate.normalized_url,
                kind=candidate.kind,
                source_field=candidate.source_field,
            )
            for candidate in parsed_item.media_candidates
        ]

    async def attach_item_media(self, **kwargs):
        self.events.append(("item_media", len(kwargs["media_assets"])))


def test_rss_source_fetch_stores_raw_payload_before_parsing():
    source = _rss_source()
    repository = FakeRepository([source])
    client = _mock_client({"https://example.com/feed.xml": _rss_xml()})

    stats = _run_service(repository, client)

    event_names = [event[0] for event in repository.events]
    assert event_names.index("raw_payload") < event_names.index("source_item")
    assert stats["items"] == 1


def test_telegram_public_source_uses_tme_s_channel():
    source = _telegram_source()
    repository = FakeRepository([source])
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, text=_telegram_html(), headers={"content-type": "text/html"})

    _run_service(repository, httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    assert requested_urls == ["https://t.me/s/iran_jahan_darlahze"]


def test_http_304_marks_source_skipped_without_parser_failure():
    source = _rss_source()
    source.health_status = "healthy"
    source.failure_count = 0
    source.last_parse_count = 12
    source.last_suitable_count = 10
    source.last_media_count = 4
    repository = FakeRepository([source])
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(304, text="")))

    stats = _run_service(repository, client)

    assert stats["skipped"] == 1
    assert repository.finished["status"] == "succeeded"
    assert "source_item" not in [event[0] for event in repository.events]
    assert source.health_status == "healthy"
    assert source.failure_count == 0
    assert source.last_error_type is None
    assert source.last_parse_count == 12
    assert source.last_suitable_count == 10
    assert source.last_media_count == 4


def test_source_fetch_error_produces_partial_run_status():
    source = _rss_source()
    repository = FakeRepository([source])

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    stats = _run_service(repository, httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    assert stats["failed"] == 1
    assert repository.finished["status"] == "partial"


def test_source_failure_stats_are_sanitized_for_repository_and_return_without_mutating_source():
    source = _rss_source()
    source.name = "Source api_key=ingestion-source-name-canary"
    repository = FakeRepository([source])

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            'network {"authorization":"Bearer ingestion-return-canary"}',
            request=request,
        )

    stats = _run_service(
        repository,
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    assert "ingestion-source-name-canary" in source.name
    assert "ingestion-source-name-canary" not in str(stats)
    assert "ingestion-return-canary" not in str(stats)
    assert "[REDACTED]" in str(stats)
    assert repository.finished["stats"] == stats
    assert "ingestion-source-name-canary" not in str(repository.finished)
    assert "ingestion-return-canary" not in str(repository.finished)


def test_post_parse_warning_assignment_is_sanitized(monkeypatch):
    source = _rss_source()
    repository = FakeRepository([source])

    monkeypatch.setattr(
        "app.ingestion.service._parse_source_payload",
        lambda *_args, **_kwargs: SimpleNamespace(
            warnings=['bozo_feed: {"api_key":"service-warning-canary"}'],
            items=[],
        ),
    )
    _run_service(
        repository,
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200, text="malformed"))),
    )

    assert "service-warning-canary" not in str(repository.raw_payload.parser_warnings)
    assert "[REDACTED]" in str(repository.raw_payload.parser_warnings)


def test_media_candidates_are_sent_to_repository():
    source = _rss_source()
    repository = FakeRepository([source])
    client = _mock_client({"https://example.com/feed.xml": _rss_xml()})

    _run_service(repository, client)

    assert repository.media_candidate_count > 0


def _run_service(repository: FakeRepository, client: httpx.AsyncClient) -> dict:
    import asyncio

    service = IngestionService(session=None, repository=repository, http_client=client)
    return asyncio.run(service.run_once(trigger="test"))


def _mock_client(routes: dict[str, str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=routes[str(request.url)], headers={"content-type": "application/rss+xml"})

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
    )


def _telegram_source() -> Source:
    return Source(
        id=uuid4(),
        platform="telegram_public",
        name="Telegram",
        telegram_username="iran_jahan_darlahze",
        source_group="farsi_news",
        language_hint="fa",
        default_timezone="UTC",
        active=True,
    )


def _rss_xml() -> str:
    return Path("tests/fixtures/rss_google_ai.xml").read_text(encoding="utf-8")


def _telegram_html() -> str:
    return Path("tests/fixtures/telegram_public_sample.html").read_text(encoding="utf-8")
