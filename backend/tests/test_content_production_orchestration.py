from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient, MockTransport, Response

from app.content_production.candidates import CandidateSelectionService
from app.content_production.events import WorkflowEventType
from app.content_production.idempotency import artifact_id
from app.content_production.repository import ContentProductionRepository
from app.db.models import (
    AgentStepRun,
    ArticleExtractionResult,
    CandidateShortlist,
    ContentItem,
    ContentProductionRequest,
    ContentProductionRun,
    ContentSufficiencyReport,
    DraftQualityReport,
    EditorialBrief,
    MediaAsset,
    TelegramDispatchRequest,
    TelegramDraft,
    TelegramPostPackage,
    VisualBrief,
    WorkflowEvent,
)
from app.db.session import get_session
from app.main import app


def _orchestration_api():
    """Load the Phase 2 API inside tests so every missing contract is reported."""
    return importlib.import_module("app.content_production.orchestration")


def _event(event_type: WorkflowEventType, *, payload: dict | None = None) -> WorkflowEvent:
    event_id = uuid4()
    return WorkflowEvent(
        event_id=event_id,
        event_type=event_type.value,
        aggregate_type="content_production_run",
        aggregate_id=uuid4(),
        correlation_id=uuid4(),
        causation_id=uuid4(),
        payload=payload or {},
        status="pending",
        attempt_count=0,
        available_at=datetime.now(UTC),
    )


async def test_outbox_worker_claims_processes_and_marks_successful_events():
    orchestration = _orchestration_api()
    event = _event(WorkflowEventType.CANDIDATE_SELECTION_REQUESTED)
    store = FakeOutboxStore([event])
    dispatcher = orchestration.EventDispatcher()
    handled = []

    async def handler(received):
        handled.append(received)

    dispatcher.register(WorkflowEventType.CANDIDATE_SELECTION_REQUESTED, handler)
    processed = await orchestration.WorkflowEventWorker(store, dispatcher).run_once(limit=10)

    assert processed == 1
    assert store.claimed == [event]
    assert handled == [event]
    assert event.status == "processed"
    assert event.attempt_count == 1
    assert event.processed_at is not None
    assert event.last_error is None


async def test_outbox_worker_retries_then_marks_a_poison_event_failed():
    orchestration = _orchestration_api()
    event = _event(WorkflowEventType.DRAFT_GENERATION_REQUESTED)
    store = FakeOutboxStore([event])
    dispatcher = orchestration.EventDispatcher()

    async def failing_handler(_event):
        raise RuntimeError("temporary model failure")

    dispatcher.register(WorkflowEventType.DRAFT_GENERATION_REQUESTED, failing_handler)
    worker = orchestration.WorkflowEventWorker(
        store,
        dispatcher,
        max_attempts=2,
        retry_delay=timedelta(seconds=30),
    )

    await worker.run_once()
    assert event.status == "pending"
    assert event.attempt_count == 1
    assert event.last_error == "temporary model failure"
    assert event.available_at > datetime.now(UTC)

    event.available_at = datetime.now(UTC)
    await worker.run_once()
    assert event.status == "failed"
    assert event.attempt_count == 2
    assert event.last_error == "temporary model failure"


async def test_outbox_worker_skips_already_processed_events():
    orchestration = _orchestration_api()
    event = _event(WorkflowEventType.MEDIA_RESOLUTION_REQUESTED)
    event.status = "processed"
    store = FakeOutboxStore([event])
    dispatcher = orchestration.EventDispatcher()
    calls = []

    async def handler(received):
        calls.append(received)

    dispatcher.register(WorkflowEventType.MEDIA_RESOLUTION_REQUESTED, handler)
    processed = await orchestration.WorkflowEventWorker(store, dispatcher).run_once()

    assert processed == 0
    assert calls == []
    assert store.claimed == []


async def test_dispatch_registry_routes_handlers_by_event_type():
    orchestration = _orchestration_api()
    dispatcher = orchestration.EventDispatcher()
    calls = []

    async def candidate_handler(event):
        calls.append(("candidate", event.event_id))

    async def draft_handler(event):
        calls.append(("draft", event.event_id))

    dispatcher.register(WorkflowEventType.CANDIDATE_SELECTION_REQUESTED, candidate_handler)
    dispatcher.register(WorkflowEventType.DRAFT_GENERATION_REQUESTED, draft_handler)
    draft_event = _event(WorkflowEventType.DRAFT_GENERATION_REQUESTED)

    await dispatcher.dispatch(draft_event)

    assert calls == [("draft", draft_event.event_id)]


async def test_candidate_selection_is_performed_when_the_worker_processes_its_event():
    orchestration = _orchestration_api()
    request = ContentProductionRequest(
        id=uuid4(),
        topic="AI",
        platform="telegram",
        language="fa",
        max_candidates=1,
        require_rewrite_ready=True,
        require_media=False,
        constraints_json={},
        status="created",
    )
    item = _content_item()
    session = WorkflowSession(scalars_results=[[item]])
    event = _event(
        WorkflowEventType.CANDIDATE_SELECTION_REQUESTED,
        payload={"request_id": str(request.id)},
    )
    store = FakeOutboxStore([event])
    dispatcher = orchestration.EventDispatcher()

    async def select_candidates(_event):
        await CandidateSelectionService(session).prepare_shortlist(request)

    dispatcher.register(WorkflowEventType.CANDIDATE_SELECTION_REQUESTED, select_candidates)
    await orchestration.WorkflowEventWorker(store, dispatcher).run_once()

    shortlists = [row for row in session.added if isinstance(row, CandidateShortlist)]
    assert len(shortlists) == 1
    assert shortlists[0].content_item_id == item.id
    assert request.status == "shortlist_approval_pending"
    assert event.status == "processed"


async def test_request_api_enqueues_candidate_selection_without_running_it(monkeypatch):
    session = WorkflowSession()

    async def service_must_not_run_in_api(*_args, **_kwargs):
        raise AssertionError("candidate selection must be performed by the event worker")

    monkeypatch.setattr(CandidateSelectionService, "prepare_shortlist", service_must_not_run_in_api)
    _override_session(session)
    try:
        response = await _post(
            "/content-production/requests",
            json={"topic": "AI", "max_candidates": 1, "created_by": "operator"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert not [row for row in session.added if isinstance(row, CandidateShortlist)]
    assert [row.event_type for row in session.added if isinstance(row, WorkflowEvent)] == [
        WorkflowEventType.CONTENT_PRODUCTION_REQUEST_CREATED.value,
    ]


async def test_shortlist_approval_api_emits_event_and_defers_run_creation(monkeypatch):
    request_id = uuid4()
    item_id = uuid4()
    candidate = CandidateShortlist(
        id=uuid4(),
        request_id=request_id,
        selection_execution_id=uuid4(),
        content_item_id=item_id,
        rank=1,
        score=10,
        selection_reason_json={},
        risk_flags_json=[],
        source_snapshot_json={},
        approval_status="pending",
    )
    session = WorkflowSession(scalars_results=[[candidate]])

    async def run_must_not_be_created_in_api(*_args, **_kwargs):
        raise AssertionError("production runs must be created by the approval event handler")

    monkeypatch.setattr(ContentProductionRepository, "create_run", run_must_not_be_created_in_api)
    _override_session(session)
    try:
        response = await _post(
            f"/content-production/requests/{request_id}/shortlist/approve",
            json={
                "selection_execution_id": str(candidate.selection_execution_id),
                "content_item_ids": [str(item_id)],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert not [row for row in session.added if isinstance(row, ContentProductionRun)]
    events = [row for row in session.added if isinstance(row, WorkflowEvent)]
    assert [row.event_type for row in events] == [WorkflowEventType.CANDIDATE_SHORTLIST_APPROVED.value]


def test_run_identity_deduplicates_replay_without_blocking_a_new_approval_command():
    approval_command = uuid4()
    content_item_id = uuid4()

    first = artifact_id(approval_command, "content_production_run", str(content_item_id))
    replay = artifact_id(approval_command, "content_production_run", str(content_item_id))
    intentional_new_command = artifact_id(uuid4(), "content_production_run", str(content_item_id))

    assert replay == first
    assert intentional_new_command != first


async def test_event_driven_e2e_processes_events_instead_of_calling_the_service_chain_directly():
    orchestration = _orchestration_api()
    item = _content_item()
    image = _media_asset()
    item.primary_image_id = image.id
    item.content_text = ""
    extraction_client = AsyncClient(
        transport=MockTransport(
            lambda request: Response(
                200,
                request=request,
                text=(
                    f"<html><article><h1>{item.title}</h1>"
                    f"<p>{'Verified article context. ' * 100}</p></article></html>"
                ),
            )
        )
    )
    session = WorkflowSession(rows=[item, image])
    _override_session(session)
    try:
        create_response = await _post(
            "/content-production/requests",
            json={"topic": "AI", "max_candidates": 1, "created_by": "operator"},
        )
        assert create_response.status_code == 200
        request = next(row for row in session.added if isinstance(row, ContentProductionRequest))
        assert not [row for row in session.added if isinstance(row, CandidateShortlist)]

        dispatcher = orchestration.build_core_event_dispatcher(session, extraction_client=extraction_client)
        worker = orchestration.WorkflowEventWorker(FakeOutboxStore(session.added), dispatcher)
        await _drain(worker)

        shortlist = [row for row in session.added if isinstance(row, CandidateShortlist)]
        assert len(shortlist) == 1
        assert not [row for row in session.added if isinstance(row, ContentProductionRun)]
        selection_event = next(
            event
            for event in session.added
            if isinstance(event, WorkflowEvent)
            and event.event_type == WorkflowEventType.CANDIDATE_SELECTION_REQUESTED.value
        )
        selection_event.status = "pending"
        selection_event.processed_at = None
        selection_event.available_at = datetime.now(UTC)
        await _drain(worker)
        assert len([row for row in session.added if isinstance(row, CandidateShortlist)]) == 1

        approval_response = await _post(
            f"/content-production/requests/{request.id}/shortlist/approve",
            json={
                "selection_execution_id": str(shortlist[0].selection_execution_id),
                "content_item_ids": [str(shortlist[0].content_item_id)],
            },
        )
        assert approval_response.status_code == 200
        assert not [row for row in session.added if isinstance(row, ContentProductionRun)]
        await _drain(worker)

        runs = [row for row in session.added if isinstance(row, ContentProductionRun)]
        assert len(runs) == 1
        assert len([row for row in session.added if isinstance(row, ArticleExtractionResult)]) == 1
        reports = [row for row in session.added if isinstance(row, ContentSufficiencyReport)]
        assert [report.input_snapshot_json["stage"] for report in reports] == ["original", "post_extraction"]
        assert [row for row in session.added if isinstance(row, EditorialBrief)]
        assert [row for row in session.added if isinstance(row, TelegramDraft)]
        assert [row for row in session.added if isinstance(row, DraftQualityReport)]
        assert [row for row in session.added if isinstance(row, VisualBrief)]
        packages = [row for row in session.added if isinstance(row, TelegramPostPackage)]
        assert len(packages) == 1
        assert not [row for row in session.added if isinstance(row, TelegramDispatchRequest)]
        package_event = next(
            event
            for event in session.added
            if isinstance(event, WorkflowEvent)
            and event.event_type == WorkflowEventType.TELEGRAM_PACKAGE_REQUESTED.value
        )
        pinned_payload = dict(package_event.payload)
        package_event.status = "pending"
        package_event.processed_at = None
        package_event.available_at = datetime.now(UTC)
        await _drain(worker)
        assert len([row for row in session.added if isinstance(row, TelegramPostPackage)]) == 1
        assert package_event.payload == pinned_payload

        final_response = await _post(f"/content-production/packages/{packages[0].id}/approve")
        assert final_response.status_code == 200
        await _drain(worker)

        assert len([row for row in session.added if isinstance(row, TelegramDispatchRequest)]) == 1
        assert [row for row in session.added if isinstance(row, AgentStepRun)]
        final_approval_event = next(
            event
            for event in session.added
            if isinstance(event, WorkflowEvent)
            and event.event_type == WorkflowEventType.POST_PACKAGE_APPROVED.value
        )
        final_approval_event.status = "pending"
        final_approval_event.processed_at = None
        final_approval_event.available_at = datetime.now(UTC)
        await _drain(worker)
        assert len([row for row in session.added if isinstance(row, TelegramDispatchRequest)]) == 1

        replayed_approval = next(
            event
            for event in session.added
            if isinstance(event, WorkflowEvent) and event.event_type == WorkflowEventType.CANDIDATE_SHORTLIST_APPROVED
        )
        replayed_approval.status = "pending"
        replayed_approval.processed_at = None
        replayed_approval.available_at = datetime.now(UTC)
        await _drain(worker)

        assert len([row for row in session.added if isinstance(row, ContentProductionRun)]) == 1
        assert len([row for row in session.added if isinstance(row, TelegramDraft)]) == 1
        assert len([row for row in session.added if isinstance(row, TelegramPostPackage)]) == 1
        assert len([row for row in session.added if isinstance(row, TelegramDispatchRequest)]) == 1
    finally:
        await extraction_client.aclose()
        app.dependency_overrides.clear()


def test_core_dispatcher_registers_every_required_handler():
    orchestration = _orchestration_api()
    dispatcher = orchestration.build_core_event_dispatcher(SimpleNamespace())

    assert dispatcher.registered_event_types == frozenset(WorkflowEventType)


@pytest.mark.parametrize(
    ("event_type", "status", "attempts", "expected_next"),
    [
        (WorkflowEventType.CONTENT_SUFFICIENCY_CHECKED, "partial", {}, WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED),
        (
            WorkflowEventType.CONTENT_SUFFICIENCY_CHECKED,
            "partial",
            {"extraction_attempted": True},
            WorkflowEventType.WEB_ENRICHMENT_REQUESTED,
        ),
        (WorkflowEventType.ARTICLE_EXTRACTED, "ok", {}, WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED),
        (WorkflowEventType.WEB_ENRICHED, "ok", {}, WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED),
        (WorkflowEventType.CONTENT_SUFFICIENCY_CHECKED, "sufficient", {}, WorkflowEventType.EDITORIAL_BRIEF_REQUESTED),
    ],
)
def test_sufficiency_progression_emits_the_required_next_event(event_type, status, attempts, expected_next):
    orchestration = _orchestration_api()
    payload = {"status": status, **attempts}

    next_types = orchestration.next_event_types(event_type, payload)

    assert next_types == [expected_next]


def test_sufficiency_progression_stops_after_extraction_and_enrichment_attempts():
    orchestration = _orchestration_api()

    next_types = orchestration.next_event_types(
        WorkflowEventType.CONTENT_SUFFICIENCY_CHECKED,
        {"status": "partial", "extraction_attempted": True, "enrichment_attempted": True},
    )

    assert next_types == [WorkflowEventType.PRODUCTION_RUN_FAILED]


class FakeOutboxStore:
    def __init__(self, events):
        self.events = events
        self.claimed = []

    async def claim_pending_events(self, *, limit):
        claimable = [
            event
            for event in self.events
            if isinstance(event, WorkflowEvent)
            and event.status == "pending"
            and event.available_at <= datetime.now(UTC)
        ][:limit]
        for event in claimable:
            event.status = "processing"
        self.claimed.extend(claimable)
        return claimable

    async def flush(self):
        return None

    async def commit(self):
        return None


class WorkflowSession:
    def __init__(self, *, scalars_results=None, rows=None):
        self.scalars_results = list(scalars_results or [])
        self.added = []
        self.by_model_and_id = {}
        self.committed = False
        for row in rows or []:
            self.add(row)

    def add(self, row):
        self.added.append(row)
        row_id = getattr(row, "event_id", None) or getattr(row, "id", None)
        if row_id is not None:
            self.by_model_and_id[(type(row), row_id)] = row

    async def get(self, model, row_id):
        return self.by_model_and_id.get((model, row_id))

    async def scalars(self, statement):
        if self.scalars_results:
            return self.scalars_results.pop(0)
        return self._rows_for(statement)

    async def scalar(self, statement):
        rows = self._rows_for(statement)
        return rows[0] if rows else None

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True

    def _rows_for(self, statement):
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is None:
            return []
        return [row for row in self.added if isinstance(row, entity)]


def _content_item():
    return ContentItem(
        id=uuid4(),
        item_type="rss",
        title="AI agent platform launch",
        summary="A useful AI source summary.",
        content_text="AI agents are described with enough sourced detail for editorial production. " * 70,
        canonical_url="https://example.com/ai",
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


def _media_asset():
    return MediaAsset(
        id=uuid4(),
        original_url="https://example.com/image.jpg",
        normalized_url="https://example.com/image.jpg",
        url_hash=uuid4().hex,
        kind="image",
        mime_type="image/jpeg",
        width=1200,
        height=800,
        source_field="rss_enclosure",
        fetch_status="fetched",
        media_quality="high",
    )


def _override_session(session):
    async def override():
        yield session

    app.dependency_overrides[get_session] = override


async def _post(path, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, **kwargs)


async def _drain(worker, *, max_batches=30):
    for _ in range(max_batches):
        if await worker.run_once(limit=100) == 0:
            return
    raise AssertionError("event worker did not become idle; possible orchestration loop")
