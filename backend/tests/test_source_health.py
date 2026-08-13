from types import SimpleNamespace
from uuid import uuid4

from app.db.models import Source
from app.ingestion.workflow import (
    _is_suitable_item,
    _record_source_failure,
    _record_source_not_modified,
    _record_source_success,
)
from app.sources.telegram_public import parse_public_telegram_page


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


def test_titleless_platform_item_with_a_body_counts_as_suitable() -> None:
    item = SimpleNamespace(
        title="",
        content_text="این یک پیام کامل تلگرامی است.",
    )

    assert _is_suitable_item(item) is True


def test_titleless_item_without_a_usable_body_stays_unsuitable() -> None:
    assert _is_suitable_item(SimpleNamespace(title="", content_text="   ")) is False
    assert _is_suitable_item(SimpleNamespace(title="", content_text="..!")) is False


def test_telegram_batch_does_not_report_a_healthy_source_as_degraded() -> None:
    html = """
    <div class="tgme_widget_message" data-post="channel/12">
      <div class="js-message_text">A complete telegram post body with plenty of words.</div>
      <time datetime="2026-08-13T10:00:00+00:00"></time>
    </div>
    """
    payload = parse_public_telegram_page(html, "channel")
    assert payload.items, "fixture must yield at least one parsed item"

    source = _source()
    _record_source_success(
        source,
        SimpleNamespace(status_code=200),
        parse_count=len(payload.items),
        suitable_count=sum(1 for item in payload.items if _is_suitable_item(item)),
        media_count=0,
        parser_warnings=list(payload.warnings),
    )

    assert source.health_status == "healthy"
    assert source.failure_count == 0
