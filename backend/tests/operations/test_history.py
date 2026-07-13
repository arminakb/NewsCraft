from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.operations.history import (
    HistoryService,
    decode_history_cursor,
    encode_history_cursor,
    history_statement,
)

ROUTE_ID = UUID("11111111-1111-4111-8111-111111111111")
JOB_ID = UUID("21111111-1111-4111-8111-111111111111")


def _event(
    value: int,
    *,
    occurred_at: datetime,
    event_type: str = "telegram.source.captured",
    event_data: dict[str, object] | None = None,
    workflow_job_id: UUID | None = JOB_ID,
):
    return SimpleNamespace(
        id=UUID(int=value),
        workflow_job_id=workflow_job_id,
        event_type=event_type,
        actor="automation",
        event_data=event_data or {"route_id": str(ROUTE_ID)},
        created_at=occurred_at,
    )


def _job(
    *,
    job_id: UUID = JOB_ID,
    job_type: str = "telegram.route.process",
    payload: dict[str, object] | None = None,
):
    return SimpleNamespace(id=job_id, job_type=job_type, payload=payload or {})


class _Rows:
    def __init__(self, rows: list[tuple[object, object | None]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, object | None]]:
        return self._rows


class TimelineSession:
    """Small read-only SQL executor that applies only the compound cursor."""

    def __init__(self, rows: list[tuple[object, object | None]]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    async def execute(self, statement):
        self.statements.append(statement)
        parameters = statement.compile(dialect=postgresql.dialect()).params
        cursor_times = [value for value in parameters.values() if isinstance(value, datetime)]
        cursor_ids = [value for key, value in parameters.items() if key.startswith("id_") and isinstance(value, UUID)]
        rows = sorted(
            self.rows,
            key=lambda row: (row[0].created_at, row[0].id),
            reverse=True,
        )
        if cursor_times and cursor_ids:
            cursor = (cursor_times[0], cursor_ids[0])
            rows = [row for row in rows if (row[0].created_at, row[0].id) < cursor]
        return _Rows(rows)


def test_history_cursor_round_trips_compound_identity_and_rejects_tampering():
    occurred_at = datetime(2026, 7, 11, 9, 30, tzinfo=UTC)
    event_id = UUID("31111111-1111-4111-8111-111111111111")

    cursor = encode_history_cursor(occurred_at, event_id)

    assert decode_history_cursor(cursor) == (occurred_at, event_id)
    with pytest.raises(ValueError, match="invalid history cursor"):
        decode_history_cursor(cursor + "not-valid")
    with pytest.raises(ValueError, match="timezone-aware"):
        encode_history_cursor(occurred_at.replace(tzinfo=None), event_id)


def test_history_statement_uses_descending_tie_cursor_and_persisted_filters():
    occurred_at = datetime(2026, 7, 11, 9, 30, tzinfo=UTC)
    event_id = UUID("31111111-1111-4111-8111-111111111111")
    statement = history_statement(
        cursor=(occurred_at, event_id),
        subject_type="automation_route",
        subject_id=ROUTE_ID,
        category="publish",
        status="succeeded",
        limit=25,
    )

    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    parameters = compiled.params

    assert "LEFT OUTER JOIN workflow_jobs" in sql
    assert "workflow_events.created_at <" in sql
    assert "workflow_events.created_at =" in sql
    assert "workflow_events.id <" in sql
    assert "ORDER BY workflow_events.created_at DESC, workflow_events.id DESC" in sql
    assert "automation_dispatches" in sql
    assert "workflow_events.event_data" in sql
    assert "workflow_jobs.payload" in sql
    assert str(ROUTE_ID) in parameters.values()
    assert "succeeded" in parameters.values()
    assert "UPDATE " not in sql and "DELETE " not in sql and "INSERT " not in sql


def test_history_statement_filters_job_and_story_subject_families_from_durable_ids():
    story_id = UUID("61111111-1111-4111-8111-111111111111")
    job_sql = str(
        history_statement(
            cursor=None,
            subject_type="job",
            subject_id=JOB_ID,
            category=None,
            status=None,
            limit=20,
        ).compile(dialect=postgresql.dialect())
    )
    story_statement = history_statement(
        cursor=None,
        subject_type="story",
        subject_id=story_id,
        category=None,
        status=None,
        limit=20,
    )
    story_compiled = story_statement.compile(dialect=postgresql.dialect())
    story_sql = str(story_compiled)

    assert "workflow_events.workflow_job_id =" in job_sql
    assert "workflow_events.event_data" in story_sql
    assert "workflow_jobs.payload" in story_sql
    assert str(story_id) in story_compiled.params.values()


def test_story_subject_filter_follows_dispatch_and_platform_revision_lineage():
    story_id = UUID("61111111-1111-4111-8111-111111111111")
    statement = history_statement(
        cursor=None,
        subject_type="story",
        subject_id=story_id,
        category=None,
        status=None,
        limit=20,
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "automation_dispatches" in sql
    assert "story_revisions" in sql
    assert "platform_variant_revisions" in sql
    assert "platform_variants" in sql
    assert "content_packs" in sql


@pytest.mark.asyncio
async def test_history_cursor_is_stable_when_new_events_arrive():
    occurred_at = datetime(2026, 7, 11, 10, tzinfo=UTC)
    session = TimelineSession(
        [
            (_event(4, occurred_at=occurred_at), _job()),
            (_event(3, occurred_at=occurred_at), _job()),
            (_event(2, occurred_at=occurred_at), _job()),
            (_event(1, occurred_at=occurred_at), _job()),
        ]
    )
    service = HistoryService(session)

    first = await service.list(
        subject_type="automation_route",
        subject_id=ROUTE_ID,
        limit=2,
        cursor=None,
    )
    session.rows.append((_event(5, occurred_at=occurred_at + timedelta(hours=2)), _job()))
    second = await service.list(
        subject_type="automation_route",
        subject_id=ROUTE_ID,
        limit=2,
        cursor=first.next_cursor,
    )

    assert [item.id for item in first.items] == [str(UUID(int=4)), str(UUID(int=3))]
    assert [item.id for item in second.items] == [str(UUID(int=2)), str(UUID(int=1))]
    assert {item.id for item in first.items}.isdisjoint(item.id for item in second.items)
    assert first.next_cursor is not None
    assert second.next_cursor is None


@pytest.mark.asyncio
async def test_history_projects_truthful_route_and_publish_entries_from_durable_events():
    occurred_at = datetime(2026, 7, 11, 10, tzinfo=UTC)
    revision_id = UUID("41111111-1111-4111-8111-111111111111")
    publish_job_id = UUID("51111111-1111-4111-8111-111111111111")
    collection = _event(1, occurred_at=occurred_at)
    publish = _event(
        2,
        occurred_at=occurred_at + timedelta(minutes=1),
        event_type="telegram.publish.succeeded",
        event_data={
            "publish_job_id": str(publish_job_id),
            "revision_id": str(revision_id),
            "remote_message_ids": [701],
        },
    )
    session = TimelineSession([(collection, _job()), (publish, _job(job_type="telegram.publish"))])

    page = await HistoryService(session).list(limit=10)

    assert [(item.category, item.status) for item in page.items] == [
        ("publish", "succeeded"),
        ("collection", "captured"),
    ]
    assert page.items[0].title == "Telegram publish succeeded"
    assert page.items[0].job_id == JOB_ID
    assert page.items[0].subject_url == f"/review/{revision_id}"
    assert page.items[1].subject_url == f"/automations/{ROUTE_ID}"
    assert page.items[0].occurred_at == publish.created_at


@pytest.mark.asyncio
async def test_history_subject_urls_target_real_story_and_job_frontend_routes():
    occurred_at = datetime(2026, 7, 11, 10, tzinfo=UTC)
    story_id = UUID("61111111-1111-4111-8111-111111111111")
    story_event = _event(
        1,
        occurred_at=occurred_at,
        event_type="research.succeeded",
        event_data={"story_id": str(story_id), "run_id": str(UUID(int=91))},
        workflow_job_id=None,
    )
    job_event = _event(
        2,
        occurred_at=occurred_at + timedelta(minutes=1),
        event_type="job.failed",
        event_data={"error_code": "provider_failed"},
    )
    session = TimelineSession([(story_event, None), (job_event, _job(job_type="build_export"))])

    page = await HistoryService(session).list(limit=10)

    assert page.items[0].subject_url == "/jobs"
    assert page.items[1].subject_url == f"/inbox?story_id={story_id}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_type", "expected_category"),
    [
        ("ingest.collect", "collection"),
        ("manual_intake", "collection"),
        ("story.group_pending", "collection"),
        ("telegram.route.initialize", "collection"),
        ("telegram.route.poll", "collection"),
        ("telegram.route.backfill", "collection"),
        ("telegram.route.dry_run", "collection"),
        ("research_story", "research"),
        ("telegram.route.process", "generation"),
        ("content_pack.generate", "generation"),
        ("content_pack.generate_telegram", "generation"),
        ("content_pack.regenerate", "generation"),
        ("build_export", "generation"),
        ("telegram.destination.check", "publish"),
        ("telegram.publish", "publish"),
    ],
)
async def test_history_classifies_every_current_job_family_explicitly(
    job_type: str,
    expected_category: str,
):
    occurred_at = datetime(2026, 7, 11, 10, tzinfo=UTC)
    event = _event(
        1,
        occurred_at=occurred_at,
        event_type="job.enqueued",
        event_data={"job_type": job_type},
    )
    session = TimelineSession([(event, _job(job_type=job_type))])

    entry = (await HistoryService(session).list(limit=10)).items[0]

    assert entry.category == expected_category


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "expected_category"),
    [
        ("automation.control_updated", "pause"),
        ("content_pack.revision.approved", "approval"),
        ("content_pack.revision.rejected", "approval"),
        ("manual_intake.completed", "collection"),
        ("manual_publication.plan.cancelled", "cancel"),
        ("manual_publication.plan.checklist_updated", "edit"),
        ("manual_publication.plan.created", "schedule"),
        ("manual_publication.plan.published", "publish"),
        ("research.failed", "research"),
        ("research.stale_attempt_ignored", "research"),
        ("research.succeeded", "research"),
        ("schedule.invalid", "schedule"),
        ("story.editorial_state_changed", "edit"),
        ("telegram.generation.completed", "generation"),
        ("telegram.generation.failed", "generation"),
        ("telegram.process.blocked", "generation"),
        ("telegram.process.deferred", "generation"),
        ("telegram.publish.blocked", "publish"),
        ("telegram.publish.reconciled_not_published", "reconcile"),
        ("telegram.publish.reconciled_published", "reconcile"),
        ("telegram.publish.requested", "publish"),
        ("telegram.publish.scheduled", "schedule"),
        ("telegram.publish.succeeded", "publish"),
        ("telegram.research.review_required", "research"),
        ("telegram.revision.approved", "approval"),
        ("telegram.revision.auto_approved", "approval"),
        ("telegram.revision.edited", "edit"),
        ("telegram.revision.publish_requested", "publish"),
        ("telegram.revision.rejected", "approval"),
        ("telegram.revision.review_required", "approval"),
        ("telegram.source.captured", "collection"),
        ("telegram.source_edit.revision_created", "edit"),
    ],
)
async def test_history_classifies_every_current_domain_event_explicitly(
    event_type: str,
    expected_category: str,
):
    event = _event(
        1,
        occurred_at=datetime(2026, 7, 11, 10, tzinfo=UTC),
        event_type=event_type,
        workflow_job_id=None,
    )
    session = TimelineSession([(event, None)])

    entry = (await HistoryService(session).list(limit=10)).items[0]

    assert entry.category == expected_category


@pytest.mark.asyncio
async def test_history_omits_unknown_future_events_instead_of_inventing_an_edit_category():
    event = _event(
        1,
        occurred_at=datetime(2026, 7, 11, 10, tzinfo=UTC),
        event_type="future.unmapped_event",
        event_data={"future": True},
        workflow_job_id=None,
    )
    session = TimelineSession([(event, None)])

    page = await HistoryService(session).list(limit=10)

    assert page.items == []


@pytest.mark.asyncio
async def test_history_redacts_metadata_again_on_read_without_mutating_the_event():
    occurred_at = datetime(2026, 7, 11, 10, tzinfo=UTC)
    metadata = {
        "route_id": str(ROUTE_ID),
        "api_key": "top-secret",
        "nested": {"token": "also-secret"},
        "source_url": "https://example.com/item?token=url-secret&mode=full",
    }
    event = _event(1, occurred_at=occurred_at, event_data=metadata)
    session = TimelineSession([(event, _job())])

    entry = (await HistoryService(session).list(limit=10)).items[0]

    assert entry.sanitized_metadata["api_key"] == "[REDACTED]"
    assert entry.sanitized_metadata["nested"] == {"token": "[REDACTED]"}
    assert "url-secret" not in entry.sanitized_metadata["source_url"]
    assert "mode=full" in entry.sanitized_metadata["source_url"]
    assert metadata["api_key"] == "top-secret"
    assert metadata["nested"] == {"token": "also-secret"}


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 101])
async def test_history_rejects_out_of_contract_limits_before_querying(limit: int):
    session = TimelineSession([])

    with pytest.raises(ValueError, match="history limit must be between 1 and 100"):
        await HistoryService(session).list(limit=limit)

    assert session.statements == []


@pytest.mark.asyncio
async def test_history_rejects_invalid_cursor_and_subject_type_before_querying():
    session = TimelineSession([])
    service = HistoryService(session)

    with pytest.raises(ValueError, match="invalid history cursor"):
        await service.list(cursor="not-a-cursor")
    with pytest.raises(ValueError, match="unsupported history subject type"):
        await service.list(subject_type="credential", subject_id="secret")
    with pytest.raises(ValueError, match="subject_type and subject_id must be supplied together"):
        await service.list(subject_type="automation_route")
    with pytest.raises(ValueError, match="subject_type and subject_id must be supplied together"):
        await service.list(subject_id=ROUTE_ID)
    with pytest.raises(ValueError, match="history subject_id must be a UUID"):
        await service.list(subject_type="story", subject_id="not-a-uuid")

    assert session.statements == []
