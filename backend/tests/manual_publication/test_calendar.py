from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.manual_publication.calendar import (
    CalendarEvent,
    PublicationRecord,
    decode_publication_cursor,
    encode_publication_cursor,
    list_calendar_events,
    list_publications,
    validate_calendar_window,
)

PLAN_ID = UUID("11111111-1111-4111-8111-111111111111")
TELEGRAM_JOB_ID = UUID("22222222-2222-4222-8222-222222222222")
MANUAL_REVISION_ID = UUID("31111111-1111-4111-8111-111111111111")
TELEGRAM_REVISION_ID = UUID("32222222-2222-4222-8222-222222222222")
TELEGRAM_PUBLICATION_ID = UUID("41111111-1111-4111-8111-111111111111")


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Session:
    def __init__(self, *batches):
        self._batches = list(batches)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Rows(self._batches.pop(0))


def _at(hour: int) -> datetime:
    return datetime(2026, 7, 13, hour, tzinfo=UTC)


def _revision(revision_id: UUID, content: dict):
    return SimpleNamespace(id=revision_id, content=content)


def test_calendar_value_objects_are_strict_and_require_aware_time():
    event = CalendarEvent(
        id=f"manual:{PLAN_ID}",
        kind="manual_publication",
        platform="instagram",
        revision_id=MANUAL_REVISION_ID,
        title="A verified headline",
        starts_at=_at(8),
        status="planned",
        action_url=f"/review/{MANUAL_REVISION_ID}",
    )
    assert event.starts_at == _at(8)

    with pytest.raises(ValidationError):
        CalendarEvent.model_validate({**event.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError, match="timezone-aware"):
        CalendarEvent.model_validate({**event.model_dump(), "starts_at": datetime(2026, 7, 13, 8)})
    with pytest.raises(ValidationError, match="relative application path"):
        CalendarEvent.model_validate({**event.model_dump(), "action_url": "https://evil.test/review"})


def test_publication_value_object_rejects_unsafe_or_naive_values():
    record = PublicationRecord(
        id=TELEGRAM_PUBLICATION_ID,
        kind="telegram_publication",
        platform="telegram",
        revision_id=TELEGRAM_REVISION_ID,
        occurred_at=_at(11),
        status="confirmed",
        external_url="https://t.me/news/42",
        action_url=f"/review/{TELEGRAM_REVISION_ID}",
    )
    assert record.revision_id == TELEGRAM_REVISION_ID

    with pytest.raises(ValidationError, match="userinfo"):
        PublicationRecord.model_validate({**record.model_dump(), "external_url": "https://token@example.test/post"})
    with pytest.raises(ValidationError, match="timezone-aware"):
        PublicationRecord.model_validate({**record.model_dump(), "occurred_at": datetime(2026, 7, 13, 11)})


def test_calendar_window_allows_exactly_93_days_and_normalizes_to_utc():
    start = datetime(2026, 7, 13, 3, 30, tzinfo=UTC)
    normalized_start, normalized_end, timezone = validate_calendar_window(
        start=start,
        end=start + timedelta(days=93),
        display_timezone="Asia/Tehran",
    )
    assert normalized_start == start
    assert normalized_end == start + timedelta(days=93)
    assert timezone.key == "Asia/Tehran"


@pytest.mark.parametrize(
    ("start", "end", "display_timezone", "message"),
    [
        (_at(8), _at(8), "UTC", "after start"),
        (_at(8), _at(8) + timedelta(days=93, microseconds=1), "UTC", "93 days"),
        (datetime(2026, 7, 13, 8), _at(9), "UTC", "timezone-aware"),
        (_at(8), _at(9), "Mars/Olympus_Mons", "IANA"),
        (_at(8), _at(9), "/etc/passwd", "IANA"),
        (_at(8), _at(9), "../UTC", "IANA"),
    ],
)
def test_calendar_window_rejects_invalid_boundaries(start, end, display_timezone, message):
    with pytest.raises(ValueError, match=message):
        validate_calendar_window(start=start, end=end, display_timezone=display_timezone)


@pytest.mark.asyncio
async def test_calendar_merges_manual_and_reviewed_telegram_in_stable_order():
    manual_plan = SimpleNamespace(
        id=PLAN_ID,
        platform_variant_revision_id=MANUAL_REVISION_ID,
        platform="instagram",
        scheduled_for=_at(8),
        status="ready",
    )
    telegram_job = SimpleNamespace(
        id=TELEGRAM_JOB_ID,
        platform_variant_revision_id=TELEGRAM_REVISION_ID,
        scheduled_for=_at(8),
        status="scheduled",
    )
    workflow_job = SimpleNamespace(origin="manual", job_type="telegram.publish")
    session = _Session(
        [(manual_plan, _revision(MANUAL_REVISION_ID, {"hook": "Instagram hook"}))],
        [
            (
                telegram_job,
                workflow_job,
                _revision(TELEGRAM_REVISION_ID, {"body": "<b>Telegram headline</b>"}),
            )
        ],
    )

    items = await list_calendar_events(
        session,
        start=_at(7),
        end=_at(9),
        display_timezone="Asia/Tehran",
    )

    assert [(item.kind, item.id) for item in items] == [
        ("manual_publication", f"manual:{PLAN_ID}"),
        ("telegram_publish", f"telegram:{TELEGRAM_JOB_ID}"),
    ]
    assert items[0].starts_at.isoformat() == "2026-07-13T11:30:00+03:30"
    assert items[0].revision_id == MANUAL_REVISION_ID
    assert items[1].revision_id == TELEGRAM_REVISION_ID
    assert items[0].action_url == f"/review/{MANUAL_REVISION_ID}"
    assert items[1].title == "Telegram headline"
    assert all(not item.action_url.startswith(("http://", "https://")) for item in items)

    manual_sql, telegram_sql = (str(statement) for statement in session.statements)
    assert "manual_publication_plans.scheduled_for >=" in manual_sql
    assert "manual_publication_plans.scheduled_for <" in manual_sql
    assert "workflow_jobs.origin" in telegram_sql
    assert "publish_jobs.scheduled_for >=" in telegram_sql
    assert "publish_jobs.scheduled_for <" in telegram_sql
    assert "platform_variant_revisions.approval_state =" not in telegram_sql


@pytest.mark.asyncio
async def test_calendar_orders_dst_fold_events_by_utc_instant():
    manual_plan = SimpleNamespace(
        id=PLAN_ID,
        platform_variant_revision_id=MANUAL_REVISION_ID,
        platform="instagram",
        scheduled_for=datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
        status="ready",
    )
    telegram_job = SimpleNamespace(
        id=TELEGRAM_JOB_ID,
        platform_variant_revision_id=TELEGRAM_REVISION_ID,
        scheduled_for=datetime(2026, 11, 1, 6, 15, tzinfo=UTC),
        status="scheduled",
    )
    workflow_job = SimpleNamespace(origin="manual", job_type="telegram.publish")
    session = _Session(
        [(manual_plan, _revision(MANUAL_REVISION_ID, {"hook": "Before fallback"}))],
        [
            (
                telegram_job,
                workflow_job,
                _revision(TELEGRAM_REVISION_ID, {"body": "After fallback"}),
            )
        ],
    )

    items = await list_calendar_events(
        session,
        start=datetime(2026, 11, 1, 5, tzinfo=UTC),
        end=datetime(2026, 11, 1, 7, tzinfo=UTC),
        display_timezone="America/New_York",
    )

    assert [item.id for item in items] == [
        f"manual:{PLAN_ID}",
        f"telegram:{TELEGRAM_JOB_ID}",
    ]
    assert [item.starts_at.astimezone(UTC) for item in items] == [
        manual_plan.scheduled_for,
        telegram_job.scheduled_for,
    ]


def test_publication_cursor_round_trips_full_stable_identity_and_rejects_invalid_input():
    cursor = encode_publication_cursor(
        _at(10),
        "manual_publication",
        PLAN_ID,
    )
    assert decode_publication_cursor(cursor) == (_at(10), "manual_publication", PLAN_ID)

    for invalid in ("", "not-base64", "e30", encode_publication_cursor(_at(10), "manual_publication", PLAN_ID) + "!"):
        with pytest.raises(ValueError, match="invalid publication cursor"):
            decode_publication_cursor(invalid)


@pytest.mark.asyncio
async def test_publications_merge_only_confirmed_and_completed_rows_with_limit_plus_one():
    telegram = SimpleNamespace(
        id=TELEGRAM_PUBLICATION_ID,
        platform_variant_revision_id=TELEGRAM_REVISION_ID,
        published_at=_at(10),
        reconciliation_status="confirmed",
        permalink="https://t.me/news/42",
    )
    unconfirmed = SimpleNamespace(
        id=UUID("42222222-2222-4222-8222-222222222222"),
        platform_variant_revision_id=TELEGRAM_REVISION_ID,
        published_at=_at(12),
        reconciliation_status="requeued",
        permalink="https://t.me/news/99",
    )
    completed = SimpleNamespace(
        id=PLAN_ID,
        platform_variant_revision_id=MANUAL_REVISION_ID,
        platform="blog",
        completed_at=_at(11),
        status="manual_published",
        external_url="https://news.example.test/verified",
    )
    planned = SimpleNamespace(
        id=UUID("13333333-3333-4333-8333-333333333333"),
        platform_variant_revision_id=MANUAL_REVISION_ID,
        platform="blog",
        completed_at=None,
        status="planned",
        external_url=None,
    )
    session = _Session(
        [
            (unconfirmed, _revision(TELEGRAM_REVISION_ID, {"body": "Not confirmed"})),
            (telegram, _revision(TELEGRAM_REVISION_ID, {"body": "Confirmed"})),
        ],
        [
            (completed, _revision(MANUAL_REVISION_ID, {"title": "Published blog"})),
            (planned, _revision(MANUAL_REVISION_ID, {"title": "Only planned"})),
        ],
    )

    page = await list_publications(session, cursor=None, platform=None, limit=1)

    assert [(item.kind, item.id) for item in page.items] == [
        ("manual_publication", PLAN_ID),
    ]
    assert page.items[0].revision_id == MANUAL_REVISION_ID
    assert page.next_cursor == encode_publication_cursor(_at(11), "manual_publication", PLAN_ID)
    assert all(item.id not in {unconfirmed.id, planned.id} for item in page.items)
    publication_sql, manual_sql = (str(statement) for statement in session.statements)
    assert "publications.reconciliation_status" in publication_sql
    assert "manual_publication_plans.status" in manual_sql


@pytest.mark.asyncio
async def test_publications_use_kind_and_id_as_tie_breakers_and_apply_platform_filter():
    telegram = SimpleNamespace(
        id=TELEGRAM_PUBLICATION_ID,
        platform_variant_revision_id=TELEGRAM_REVISION_ID,
        published_at=_at(10),
        reconciliation_status="confirmed",
        permalink=None,
    )
    completed = SimpleNamespace(
        id=PLAN_ID,
        platform_variant_revision_id=MANUAL_REVISION_ID,
        platform="x",
        completed_at=_at(10),
        status="manual_published",
        external_url=None,
    )
    session = _Session(
        [(telegram, _revision(TELEGRAM_REVISION_ID, {"body": "Telegram"}))],
        [(completed, _revision(MANUAL_REVISION_ID, {"posts": [{"text": "X post"}]}))],
    )

    page = await list_publications(session, cursor=None, platform="telegram", limit=50)

    assert [(item.kind, item.id) for item in page.items] == [
        ("telegram_publication", TELEGRAM_PUBLICATION_ID),
    ]
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_manual_publication_projection_keeps_completed_record_without_external_url():
    completed_without_evidence = SimpleNamespace(
        id=PLAN_ID,
        platform_variant_revision_id=MANUAL_REVISION_ID,
        platform="blog",
        completed_at=_at(11),
        status="manual_published",
        external_url=None,
    )
    session = _Session(
        [],
        [
            (
                completed_without_evidence,
                _revision(MANUAL_REVISION_ID, {"title": "Published blog"}),
            )
        ],
    )

    page = await list_publications(session, cursor=None, platform=None, limit=50)

    assert len(page.items) == 1
    assert page.items[0].id == PLAN_ID
    assert page.items[0].status == "manual_published"
    assert page.items[0].external_url is None
