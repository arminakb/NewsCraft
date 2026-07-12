from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.content_production.orchestration import WorkflowEventWorker, build_core_event_dispatcher
from app.db.models import (
    AgentStepRun,
    CandidateShortlist,
    ContentItem,
    ContentProductionRequest,
    ContentProductionRun,
    TelegramDispatchRequest,
    TelegramPostPackage,
    WorkflowEvent,
)
from app.db.session import get_session
from app.main import app


async def test_request_api_defers_shortlist_until_worker_processing():
    session = ApiSession(_content_item())
    _override_session(session)
    try:
        response = await _post(
            "/content-production/requests",
            json={"topic": "AI", "max_candidates": 1, "created_by": "operator"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    request = session.rows(ContentProductionRequest)[0]
    assert response.json()["status"] == "created"
    assert session.rows(CandidateShortlist) == []
    assert [event.event_type for event in session.rows(WorkflowEvent)] == ["ContentProductionRequestCreated"]

    worker = _worker(session)
    await worker.run_once()
    selection = session.event("CandidateSelectionRequested")
    initial = session.event("ContentProductionRequestCreated")
    assert selection.correlation_id == initial.correlation_id == request.id
    assert selection.causation_id == initial.event_id
    assert selection.aggregate_type == "content_production_request"
    assert selection.aggregate_id == request.id
    assert selection.payload == {"request_id": str(request.id), "max_candidates": 1}
    assert session.rows(CandidateShortlist) == []

    await worker.run_once()

    shortlist = session.rows(CandidateShortlist)
    assert len(shortlist) == 1
    assert shortlist[0].request_id == request.id
    prepared = session.event("CandidateShortlistPrepared")
    assert prepared.correlation_id == request.id
    assert prepared.causation_id is not None


async def test_repeated_request_payload_creates_distinct_request_commands():
    session = ApiSession(_content_item())
    _override_session(session)
    try:
        first = await _post("/content-production/requests", json={"topic": "AI", "max_candidates": 1})
        second = await _post("/content-production/requests", json={"topic": "AI", "max_candidates": 1})
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert len(session.rows(ContentProductionRequest)) == 2
    events = session.rows(WorkflowEvent)
    assert len(events) == 2
    assert len({event.correlation_id for event in events}) == 2


async def test_reprocessing_initial_event_does_not_duplicate_selection_request():
    request = _request()
    session = ApiSession(request)
    initial = WorkflowEvent(
        event_id=uuid4(),
        event_type="ContentProductionRequestCreated",
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        correlation_id=request.id,
        payload={"request_id": str(request.id)},
        status="pending",
        attempt_count=0,
        available_at=datetime.now(UTC),
    )
    session.add(initial)
    dispatcher = build_core_event_dispatcher(session)

    await dispatcher.dispatch(initial)
    await dispatcher.dispatch(initial)

    selections = [event for event in session.rows(WorkflowEvent) if event.event_type == "CandidateSelectionRequested"]
    assert len(selections) == 1
    assert selections[0].causation_id == initial.event_id


async def test_shortlist_approval_api_defers_run_and_worker_emits_sufficiency_request():
    request = _request(status="shortlist_approval_pending")
    item = _content_item()
    candidate = _candidate(request, item)
    session = ApiSession(request, item, candidate)
    _override_session(session)
    try:
        response = await _post(
            f"/content-production/requests/{request.id}/shortlist/approve",
            json={
                "selection_execution_id": str(candidate.selection_execution_id),
                "content_item_ids": [str(item.id)],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert candidate.approval_status == "approved"
    assert session.rows(ContentProductionRun) == []
    approval = session.event("CandidateShortlistApproved")
    assert approval.payload == {
        "request_id": str(request.id),
        "selection_execution_id": str(candidate.selection_execution_id),
        "content_item_ids": [str(item.id)],
    }
    trace = session.trace("shortlist_approval_decision")
    assert trace.production_run_id is None
    assert trace.input_snapshot_json["previous_state"] == {str(item.id): "pending"}
    assert trace.output_snapshot_json["new_state"] == "approved"
    assert trace.output_snapshot_json["resulting_event_id"] == str(approval.event_id)

    await _worker(session).run_once()

    runs = session.rows(ContentProductionRun)
    assert len(runs) == 1
    sufficiency = session.event("ContentSufficiencyCheckRequested")
    assert sufficiency.aggregate_id == runs[0].id
    assert sufficiency.correlation_id == approval.correlation_id
    assert sufficiency.causation_id == approval.event_id


async def test_repeated_shortlist_approval_reuses_event_and_creates_one_run():
    request = _request(status="shortlist_approval_pending")
    item = _content_item()
    candidate = _candidate(request, item)
    session = ApiSession(request, item, candidate)
    _override_session(session)
    try:
        first = await _post(
            f"/content-production/requests/{request.id}/shortlist/approve",
            json={
                "selection_execution_id": str(candidate.selection_execution_id),
                "content_item_ids": [str(item.id)],
            },
        )
        second = await _post(
            f"/content-production/requests/{request.id}/shortlist/approve",
            json={
                "selection_execution_id": str(candidate.selection_execution_id),
                "content_item_ids": [str(item.id)],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    approval_events = [
        event for event in session.rows(WorkflowEvent) if event.event_type == "CandidateShortlistApproved"
    ]
    assert len(approval_events) == 1
    decision_traces = [
        trace for trace in session.rows(AgentStepRun) if trace.step_name == "shortlist_approval_decision"
    ]
    assert [trace.status for trace in decision_traces] == ["completed", "completed"]
    assert decision_traces[1].input_snapshot_json["previous_state"] == {str(item.id): "approved"}

    await _worker(session).run_once()

    assert len(session.rows(ContentProductionRun)) == 1


async def test_reordered_shortlist_approval_is_one_canonical_command():
    request = _request(status="shortlist_approval_pending")
    first_item, second_item = _content_item(), _content_item()
    first_candidate = _candidate(request, first_item)
    second_candidate = _candidate(request, second_item)
    second_candidate.selection_execution_id = first_candidate.selection_execution_id
    second_candidate.rank = 2
    session = ApiSession(request, first_item, second_item, first_candidate, second_candidate)
    _override_session(session)
    try:
        first = await _post(
            f"/content-production/requests/{request.id}/shortlist/approve",
            json={
                "selection_execution_id": str(first_candidate.selection_execution_id),
                "content_item_ids": [str(first_item.id), str(second_item.id)],
            },
        )
        second = await _post(
            f"/content-production/requests/{request.id}/shortlist/approve",
            json={
                "selection_execution_id": str(first_candidate.selection_execution_id),
                "content_item_ids": [str(second_item.id), str(first_item.id)],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    events = [event for event in session.rows(WorkflowEvent) if event.event_type == "CandidateShortlistApproved"]
    assert len(events) == 1
    expected = [str(value) for value in sorted((first_item.id, second_item.id), key=lambda value: value.int)]
    assert events[0].payload["content_item_ids"] == expected
    await _worker(session).run_once()
    assert len(session.rows(ContentProductionRun)) == 2


async def test_reordered_shortlist_rejection_is_one_canonical_command():
    request = _request(status="shortlist_approval_pending")
    first_item, second_item = _content_item(), _content_item()
    first_candidate = _candidate(request, first_item)
    second_candidate = _candidate(request, second_item)
    second_candidate.selection_execution_id = first_candidate.selection_execution_id
    second_candidate.rank = 2
    session = ApiSession(request, first_item, second_item, first_candidate, second_candidate)
    _override_session(session)
    try:
        first = await _post(
            f"/content-production/requests/{request.id}/shortlist/reject",
            json={
                "selection_execution_id": str(first_candidate.selection_execution_id),
                "content_item_ids": [str(first_item.id), str(second_item.id)],
            },
        )
        second = await _post(
            f"/content-production/requests/{request.id}/shortlist/reject",
            json={
                "selection_execution_id": str(first_candidate.selection_execution_id),
                "content_item_ids": [str(second_item.id), str(first_item.id)],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    events = [event for event in session.rows(WorkflowEvent) if event.event_type == "CandidateShortlistRejected"]
    assert len(events) == 1


async def test_duplicate_shortlist_candidate_ids_are_rejected():
    request = _request(status="shortlist_approval_pending")
    item = _content_item()
    candidate = _candidate(request, item)
    session = ApiSession(request, item, candidate)
    _override_session(session)
    try:
        response = await _post(
            f"/content-production/requests/{request.id}/shortlist/approve",
            json={
                "selection_execution_id": str(candidate.selection_execution_id),
                "content_item_ids": [str(item.id), str(item.id)],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert candidate.approval_status == "pending"
    assert not [event for event in session.rows(WorkflowEvent) if event.event_type == "CandidateShortlistApproved"]


async def test_different_shortlist_candidate_set_is_a_distinct_approval_command():
    request = _request(status="shortlist_approval_pending")
    first_item = _content_item()
    second_item = _content_item()
    first_candidate = _candidate(request, first_item)
    second_candidate = _candidate(request, second_item)
    second_candidate.selection_execution_id = first_candidate.selection_execution_id
    second_candidate.rank = 2
    session = ApiSession(request, first_item, second_item, first_candidate, second_candidate)
    _override_session(session)
    try:
        first = await _post(
            f"/content-production/requests/{request.id}/shortlist/approve",
            json={
                "selection_execution_id": str(first_candidate.selection_execution_id),
                "content_item_ids": [str(first_item.id)],
            },
        )
        second = await _post(
            f"/content-production/requests/{request.id}/shortlist/approve",
            json={
                "selection_execution_id": str(second_candidate.selection_execution_id),
                "content_item_ids": [str(second_item.id)],
            },
        )
    finally:
        app.dependency_overrides.clear()

    events = [event for event in session.rows(WorkflowEvent) if event.event_type == "CandidateShortlistApproved"]
    assert first.status_code == second.status_code == 200
    assert len(events) == 2
    assert events[0].event_id != events[1].event_id


async def test_shortlist_rejection_api_traces_the_actual_human_decision():
    request = _request(status="shortlist_approval_pending")
    item = _content_item()
    candidate = _candidate(request, item)
    session = ApiSession(request, item, candidate)
    _override_session(session)
    try:
        response = await _post(
            f"/content-production/requests/{request.id}/shortlist/reject",
            json={
                "selection_execution_id": str(candidate.selection_execution_id),
                "content_item_ids": [str(item.id)],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert candidate.approval_status == "rejected"
    event = session.event("CandidateShortlistRejected")
    trace = session.trace("shortlist_rejection_decision")
    assert trace.input_snapshot_json["decision"] == "reject"
    assert trace.output_snapshot_json["new_state"] == "rejected"
    assert trace.output_snapshot_json["resulting_event_id"] == str(event.event_id)


async def test_final_approval_api_defers_dispatch_handoff_until_worker_processing():
    item = _content_item()
    run = _run(item, state="final_approval_pending")
    package = _package(run)
    session = ApiSession(item, run, package)
    _override_session(session)
    try:
        response = await _post(f"/content-production/packages/{package.id}/approve")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert package.approval_status == "approved"
    assert run.state == "final_approved"
    assert session.rows(TelegramDispatchRequest) == []
    approval = session.event("PostPackageApproved")
    assert approval.payload["production_run_id"] == str(run.id)
    assert approval.payload["package_id"] == str(package.id)
    trace = session.trace("final_package_approval_decision")
    assert trace.input_snapshot_json["previous_state"] == {
        "run": "final_approval_pending",
        "package": "pending",
    }
    assert trace.output_snapshot_json["new_state"] == {"run": "final_approved", "package": "approved"}
    assert trace.output_snapshot_json["resulting_event_id"] == str(approval.event_id)

    worker = _worker(session)
    await worker.run_once()
    assert session.rows(TelegramDispatchRequest) == []
    dispatch_event = session.event("TelegramDispatchRequested")
    assert dispatch_event.correlation_id == approval.correlation_id
    assert dispatch_event.causation_id == approval.event_id

    await worker.run_once()
    dispatches = session.rows(TelegramDispatchRequest)
    assert len(dispatches) == 1
    assert dispatches[0].status == "blocked"
    assert dispatches[0].dispatched_at is None


async def test_repeated_final_approval_returns_conflict_without_duplicate_event():
    item = _content_item()
    run = _run(item, state="final_approval_pending")
    package = _package(run)
    session = ApiSession(item, run, package)
    _override_session(session)
    try:
        first = await _post(f"/content-production/packages/{package.id}/approve")
        second = await _post(f"/content-production/packages/{package.id}/approve")
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 409
    approval_events = [event for event in session.rows(WorkflowEvent) if event.event_type == "PostPackageApproved"]
    assert len(approval_events) == 1
    assert session.rows(TelegramDispatchRequest) == []
    decision_traces = [
        trace for trace in session.rows(AgentStepRun) if trace.step_name == "final_package_approval_decision"
    ]
    assert [trace.status for trace in decision_traces] == ["completed", "failed"]
    assert decision_traces[1].output_snapshot_json["failure_phase"] == "human_decision"


async def test_rejection_and_revision_pause_without_dispatch():
    rejected_item = _content_item()
    rejected_run = _run(rejected_item, state="final_approval_pending")
    rejected_package = _package(rejected_run)
    rejected_session = ApiSession(rejected_item, rejected_run, rejected_package)
    _override_session(rejected_session)
    try:
        rejection = await _post(f"/content-production/packages/{rejected_package.id}/reject")
    finally:
        app.dependency_overrides.clear()

    assert rejection.status_code == 200
    assert rejected_run.state == "final_rejected"
    rejection_event = rejected_session.event("PostPackageRejected")
    assert rejection_event.payload["package_id"] == str(rejected_package.id)
    rejection_trace = rejected_session.trace("final_package_rejection_decision")
    assert rejection_trace.output_snapshot_json["new_state"] == {
        "run": "final_rejected",
        "package": "rejected",
    }
    assert rejection_trace.output_snapshot_json["resulting_event_id"] == str(rejection_event.event_id)
    await _worker(rejected_session).run_once()
    assert rejected_session.rows(TelegramDispatchRequest) == []

    revision_item = _content_item()
    revision_run = _run(revision_item, state="final_approval_pending")
    revision_package = _package(revision_run)
    revision_session = ApiSession(revision_item, revision_run, revision_package)
    _override_session(revision_session)
    try:
        revision = await _post(f"/content-production/runs/{revision_run.id}/request-revision")
    finally:
        app.dependency_overrides.clear()

    assert revision.status_code == 200
    assert revision_run.state == "revision_requested"
    assert revision_session.rows(WorkflowEvent) == []
    assert revision_session.rows(TelegramDispatchRequest) == []
    revision_trace = revision_session.trace("final_package_revision_request")
    assert revision_trace.input_snapshot_json["revision_reason"] is None
    assert revision_trace.output_snapshot_json["new_state"] == {
        "run": "revision_requested",
        "package": "revision_requested",
    }
    assert revision_trace.output_snapshot_json["resulting_event_id"] is None


def _request(*, status="created"):
    return ContentProductionRequest(
        id=uuid4(),
        topic="AI",
        platform="telegram",
        language="fa",
        max_candidates=1,
        require_rewrite_ready=True,
        require_media=False,
        status=status,
        constraints_json={},
    )


def _content_item():
    return ContentItem(
        id=uuid4(),
        item_type="rss",
        title="AI platform launch",
        summary="AI platform details for developers.",
        content_text="AI platform details for developers with enough ranking context.",
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


def _candidate(request, item):
    return CandidateShortlist(
        id=uuid4(),
        request_id=request.id,
        selection_execution_id=uuid4(),
        content_item_id=item.id,
        rank=1,
        score=50,
        selection_reason_json={},
        risk_flags_json=[],
        source_snapshot_json={},
        approval_status="pending",
    )


def _run(item, *, state):
    return ContentProductionRun(
        id=uuid4(),
        request_id=uuid4(),
        content_item_id=item.id,
        platform="telegram",
        state=state,
    )


def _package(run):
    return TelegramPostPackage(
        id=uuid4(),
        production_run_id=run.id,
        draft_id=uuid4(),
        package_json={"post_text": "AI update", "source_links": [], "media": {}},
        approval_status="pending",
    )


def _worker(session):
    return WorkflowEventWorker(ApiOutboxStore(session.added), build_core_event_dispatcher(session))


async def _drain(worker, *, max_batches=10):
    for _ in range(max_batches):
        if await worker.run_once() == 0:
            return
    raise AssertionError("worker did not become idle")


def _override_session(session):
    async def override():
        yield session

    app.dependency_overrides[get_session] = override


async def _post(path, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, **kwargs)


class ApiSession:
    def __init__(self, *rows):
        self.added = []
        self.by_key = {}
        self.committed = False
        for row in rows:
            self.add(row)

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
        self.committed = True

    def rows(self, model):
        return [row for row in self.added if isinstance(row, model)]

    def event(self, event_type):
        events = [event for event in self.rows(WorkflowEvent) if event.event_type == event_type]
        assert events, f"missing {event_type}"
        return events[-1]

    def trace(self, step_name):
        traces = [trace for trace in self.rows(AgentStepRun) if trace.step_name == step_name]
        assert traces, f"missing trace {step_name}"
        return traces[-1]

    def _rows_for(self, statement):
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        return self.rows(entity) if entity is not None else []


class ApiOutboxStore:
    def __init__(self, events):
        self.events = events

    async def claim_pending_events(self, *, limit):
        events = [
            event
            for event in self.events
            if isinstance(event, WorkflowEvent)
            and event.status == "pending"
            and event.available_at <= datetime.now(UTC)
        ][:limit]
        for event in events:
            event.status = "processing"
        return events

    async def flush(self):
        return None

    async def commit(self):
        return None
