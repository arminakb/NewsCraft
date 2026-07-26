from types import SimpleNamespace
from uuid import uuid4

from app.db.models import Source
from app.ingestion.workflow import _record_source_failure, _record_source_not_modified, _record_source_success


def test_successful_source_is_healthy() -> None:
    source = _source()

    _record_source_success(
        source,
        SimpleNamespace(status_code=200),
        parse_count=2,
        suitable_count=1,
        media_count=3,
        parser_warnings=[],
    )

    assert source.health_status == "healthy"
    assert source.failure_count == 0
    assert source.last_parse_count == 2
    assert source.last_suitable_count == 1
    assert source.last_media_count == 3
    assert source.last_error_type is None


def test_http_failure_marks_source_broken() -> None:
    source = _source()

    _record_source_failure(
        source,
        RuntimeError("HTTP 403"),
        http_status=403,
        error_type="http_403",
    )

    assert source.health_status == "broken"
    assert source.last_http_status == 403
    assert source.failure_count == 1
    assert source.last_error_type == "http_403"


def test_malformed_feed_marks_source_degraded() -> None:
    source = _source()

    _record_source_success(
        source,
        SimpleNamespace(status_code=200),
        parse_count=0,
        suitable_count=0,
        media_count=0,
        parser_warnings=["bozo_feed: invalid XML"],
    )

    assert source.health_status == "degraded"
    assert source.last_error_type == "malformed_feed"
    assert source.failure_count == 1


def test_not_modified_preserves_existing_health_counts() -> None:
    source = _source()
    source.last_parse_count = 12
    source.last_suitable_count = 10
    source.last_media_count = 4

    _record_source_not_modified(source, SimpleNamespace(status_code=304))

    assert source.health_status == "healthy"
    assert source.failure_count == 0
    assert source.last_parse_count == 12
    assert source.last_suitable_count == 10
    assert source.last_media_count == 4


def _source() -> Source:
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
