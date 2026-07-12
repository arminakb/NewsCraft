from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content_production.dispatch import TelegramDispatchService
from app.content_production.events import WorkflowEventType
from app.content_production.idempotency import artifact_id
from app.content_production.orchestration import WorkflowEventWorker, build_core_event_dispatcher
from app.content_production.packages import TelegramPackageService
from app.content_production.sufficiency import ContentSufficiencyService
from app.content_production.telegram_drafts import TelegramDraftService
from app.db.models import (
    AgentStepRun,
    ContentItem,
    ContentProductionRun,
    ContentSufficiencyReport,
    DraftQualityReport,
    EditorialBrief,
    TelegramDispatchRequest,
    TelegramDraft,
    TelegramPostPackage,
    WorkflowEvent,
)


async def test_meaningful_workflow_step_records_a_completed_agent_step_run():
    session = ArtifactSession()
    item = _content_item()
    run = _run(item.id, state="shortlist_approved")

    event = WorkflowEvent(
        event_id=uuid4(),
        event_type=WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED.value,
        aggregate_type="content_production_run",
        aggregate_id=run.id,
        correlation_id=run.request_id,
        payload={"production_run_id": str(run.id), "stage": "original"},
        status="pending",
        attempt_count=0,
        available_at=datetime.now(UTC),
    )
    session.add(item)
    session.add(run)
    session.add(event)

    await WorkflowEventWorker(ArtifactOutboxStore(session.added), build_core_event_dispatcher(session)).run_once()

    steps = [row for row in session.added if isinstance(row, AgentStepRun)]
    assert len(steps) == 1
    assert steps[0].production_run_id == run.id
    assert steps[0].step_name == "content_sufficiency"
    assert steps[0].agent_name
    assert steps[0].input_snapshot_json
    assert steps[0].output_snapshot_json
    assert steps[0].status == "completed"
    assert steps[0].started_at is not None
    assert steps[0].finished_at is not None


async def test_duplicate_draft_event_does_not_create_duplicate_drafts():
    session = ArtifactSession()
    run = _run(uuid4(), state="brief_ready")
    brief = _brief(run.id)
    service = TelegramDraftService(session)

    first = await service.create_draft(run=run, brief=brief)
    duplicate = await service.create_draft(run=run, brief=brief)

    drafts = [row for row in session.added if isinstance(row, TelegramDraft)]
    assert duplicate.id == first.id
    assert drafts == [first]


async def test_duplicate_package_event_does_not_create_duplicate_packages():
    session = ArtifactSession()
    run = _run(uuid4(), state="media_ready")
    draft = _draft(run.id)
    quality = _quality(run.id, draft.id)
    service = TelegramPackageService(session)

    first = await service.build_package(run=run, draft=draft, quality_report=quality)
    duplicate = await service.build_package(run=run, draft=draft, quality_report=quality)

    packages = [row for row in session.added if isinstance(row, TelegramPostPackage)]
    assert duplicate.id == first.id
    assert packages == [first]


async def test_duplicate_final_approval_does_not_create_duplicate_dispatch_requests():
    session = ArtifactSession()
    run = _run(uuid4(), state="final_approved")
    package = _package(run.id, approval_status="approved")
    service = TelegramDispatchService(session, bot_token="configured", channel_id="@channel")

    first = await service.create_dispatch_request(run=run, package=package)
    duplicate = await service.create_dispatch_request(run=run, package=package)

    dispatches = [row for row in session.added if isinstance(row, TelegramDispatchRequest)]
    assert duplicate.id == first.id
    assert dispatches == [first]


def test_artifact_identity_is_stable_per_command_and_distinct_across_commands():
    command_id = uuid4()

    assert artifact_id(command_id, "telegram_draft", "brief-1") == artifact_id(
        command_id,
        "telegram_draft",
        "brief-1",
    )
    assert artifact_id(command_id, "telegram_draft", "brief-1") != artifact_id(
        uuid4(),
        "telegram_draft",
        "brief-1",
    )


async def test_distinct_command_identity_allows_intentional_artifact_versions():
    session = ArtifactSession()
    item = _content_item()
    run = _run(item.id, state="shortlist_approved")
    sufficiency = ContentSufficiencyService(session)
    first_report = await sufficiency.check_run(run, item, command_id=uuid4())
    run.state = "article_extracted"
    second_report = await sufficiency.check_run(run, item, command_id=uuid4())

    brief = _brief(run.id)
    run.state = "brief_ready"
    drafts = TelegramDraftService(session)
    first_draft = await drafts.create_draft(run=run, brief=brief, command_id=uuid4())
    run.state = "revision_requested"
    second_draft = await drafts.create_draft(run=run, brief=brief, command_id=uuid4())

    quality = _quality(run.id, second_draft.id)
    packages = TelegramPackageService(session)
    run.state = "media_ready"
    first_package = await packages.build_package(
        run=run,
        draft=second_draft,
        quality_report=quality,
        command_id=uuid4(),
    )
    run.state = "media_ready"
    second_package = await packages.build_package(
        run=run,
        draft=second_draft,
        quality_report=quality,
        command_id=uuid4(),
    )

    run.state = "final_approved"
    first_package.approval_status = "approved"
    dispatches = TelegramDispatchService(session, bot_token="configured", channel_id="@channel")
    first_dispatch = await dispatches.create_dispatch_request(
        run=run,
        package=first_package,
        command_id=uuid4(),
    )
    run.state = "dispatch_failed"
    second_dispatch = await dispatches.create_dispatch_request(
        run=run,
        package=first_package,
        command_id=uuid4(),
    )

    assert first_report.id != second_report.id
    assert first_draft.id != second_draft.id
    assert first_package.id != second_package.id
    assert first_dispatch.id != second_dispatch.id
    assert len([row for row in session.added if isinstance(row, ContentSufficiencyReport)]) == 2


def _run(content_item_id, *, state):
    return ContentProductionRun(
        id=uuid4(),
        request_id=uuid4(),
        content_item_id=content_item_id,
        platform="telegram",
        state=state,
    )


def _content_item():
    return ContentItem(
        id=uuid4(),
        item_type="rss",
        title="AI product update",
        summary="A short source summary.",
        content_text="A sourced AI product update with enough concrete detail for editorial use. " * 70,
        canonical_url="https://example.com/story",
        tags=["ai"],
        sort_at=datetime(2026, 7, 11, tzinfo=UTC),
        date_parse_status="parsed",
        status="new",
        score=50,
        content_type="news",
        source_tier="A",
        freshness_bucket="fresh",
        quality_status="ok",
        is_rewrite_ready=True,
    )


def _brief(production_run_id):
    return EditorialBrief(
        id=uuid4(),
        production_run_id=production_run_id,
        angle="Explain why the launch matters.",
        key_facts_json=[{"claim": "The company launched an AI product.", "source_url": "https://example.com/story"}],
        source_claims_json=[],
        unsafe_or_unverified_claims_json=[],
        do_not_say_json=[],
    )


def _draft(production_run_id):
    return TelegramDraft(
        id=uuid4(),
        production_run_id=production_run_id,
        brief_id=uuid4(),
        draft_text="تیتر: AI update\n\nنکات اصلی:\n- The company launched an AI product.",
        title="AI update",
        hashtags_json=["#خبر"],
        source_links_json=["https://example.com/story"],
        warnings_json=[],
        status="draft",
    )


def _quality(production_run_id, draft_id):
    return DraftQualityReport(
        id=uuid4(),
        production_run_id=production_run_id,
        draft_id=draft_id,
        status="passed",
        score=1,
        factuality_warnings_json=[],
        unsupported_claims_json=[],
        style_warnings_json=[],
        required_revisions_json=[],
    )


def _package(production_run_id, *, approval_status):
    return TelegramPostPackage(
        id=uuid4(),
        production_run_id=production_run_id,
        draft_id=uuid4(),
        package_json={"post_text": "AI update", "source_links": [], "media": {}},
        approval_status=approval_status,
    )


class ArtifactSession:
    def __init__(self):
        self.added = []
        self.by_key = {}

    def add(self, row):
        self.added.append(row)
        row_id = getattr(row, "event_id", None) or getattr(row, "id", None)
        if row_id is not None:
            self.by_key[(type(row), row_id)] = row

    async def get(self, model, row_id):
        return self.by_key.get((model, row_id))

    async def scalars(self, statement):
        return self._rows_for(statement)

    async def scalar(self, statement):
        rows = self._rows_for(statement)
        return rows[-1] if rows else None

    async def flush(self):
        return None

    async def commit(self):
        return None

    def _rows_for(self, statement):
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        return [row for row in self.added if entity is not None and isinstance(row, entity)]


class ArtifactOutboxStore:
    def __init__(self, rows):
        self.rows = rows

    async def claim_pending_events(self, *, limit):
        events = [
            row
            for row in self.rows
            if isinstance(row, WorkflowEvent) and row.status == "pending" and row.available_at <= datetime.now(UTC)
        ][:limit]
        for event in events:
            event.status = "processing"
        return events

    async def flush(self):
        return None

    async def commit(self):
        return None
