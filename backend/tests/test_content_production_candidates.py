from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.content_production.candidates import CandidateSelectionService, ShortlistApprovalService, rank_candidate_items
from app.db.models import CandidateShortlist, ContentItem, ContentProductionRequest, WorkflowEvent
from app.db.session import get_session
from app.main import app


def test_candidate_ranking_filters_by_topic_rewrite_ready_and_risk():
    request = ContentProductionRequest(
        id=uuid4(),
        topic="AI",
        platform="telegram",
        language="fa",
        max_candidates=3,
        require_rewrite_ready=True,
        require_media=False,
    )
    strong = _content_item(title="AI agents launch", score=20, is_rewrite_ready=True, source_tier="A")
    weak = _content_item(title="AI promo", score=99, is_rewrite_ready=True, content_type="promo")
    mismatch = _content_item(title="Economy update", score=80, is_rewrite_ready=True)
    not_ready = _content_item(title="AI brief", score=90, is_rewrite_ready=False)

    ranked = rank_candidate_items([weak, mismatch, not_ready, strong], request)

    assert [decision.content_item.id for decision in ranked] == [strong.id]
    assert ranked[0].score > Decimal(str(strong.score))
    assert "topic_match" in ranked[0].selection_reason["signals"]


def test_candidate_ranking_uses_immutable_id_as_final_tie_breaker():
    request = ContentProductionRequest(
        id=uuid4(), topic="AI", max_candidates=2, require_rewrite_ready=True, require_media=False
    )
    items = [
        _content_item(title="AI tied", score=20, is_rewrite_ready=True, source_tier="A")
        for _ in range(3)
    ]

    forward = rank_candidate_items(items, request)
    reverse = rank_candidate_items(list(reversed(items)), request)

    expected = sorted((item.id for item in items), key=str)
    assert [decision.content_item.id for decision in forward] == expected
    assert [decision.content_item.id for decision in reverse] == expected


def test_candidate_ranking_uses_created_at_then_fixed_minimum_when_sort_time_is_missing():
    request = ContentProductionRequest(
        id=uuid4(), topic=None, max_candidates=3, require_rewrite_ready=True, require_media=False
    )
    with_sort, with_created, without_time = (
        _content_item(title="AI one", score=20, is_rewrite_ready=True),
        _content_item(title="AI two", score=20, is_rewrite_ready=True),
        _content_item(title="AI three", score=20, is_rewrite_ready=True),
    )
    with_sort.sort_at = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    with_created.sort_at = None
    with_created.created_at = datetime(2026, 7, 11, 11, 0, tzinfo=UTC)
    without_time.sort_at = None
    without_time.created_at = None

    ranked = rank_candidate_items([without_time, with_created, with_sort], request)

    assert [decision.content_item.id for decision in ranked] == [with_sort.id, with_created.id, without_time.id]


async def test_shortlist_approval_marks_matching_candidates_only():
    request_id = uuid4()
    content_item_id = uuid4()
    selection_execution_id = uuid4()
    candidate = CandidateShortlist(
        id=uuid4(),
        request_id=request_id,
        selection_execution_id=selection_execution_id,
        content_item_id=content_item_id,
        rank=1,
        score=10,
        approval_status="pending",
        selection_reason_json={},
        risk_flags_json=[],
        source_snapshot_json={},
    )
    session = FakeSession(scalars_results=[[candidate]])

    approved = await ShortlistApprovalService(session).approve(
        request_id, selection_execution_id, [content_item_id]
    )

    assert approved == [candidate]
    assert candidate.approval_status == "approved"
    assert candidate.approved_at is not None
    assert session.flushed is True


async def test_selection_replay_reuses_rows_and_new_command_can_create_a_new_selection_version():
    request = ContentProductionRequest(
        id=uuid4(),
        topic="AI",
        platform="telegram",
        language="fa",
        max_candidates=1,
        require_rewrite_ready=True,
        require_media=False,
        status="created",
    )
    item = _content_item(title="AI agents launch", score=20, is_rewrite_ready=True, source_tier="A")
    session = FakeSession(scalars_results=[[item], [item], [item]])
    service = CandidateSelectionService(session)
    first_command = uuid4()

    first = await service.prepare_shortlist(request, command_id=first_command)
    replay = await service.prepare_shortlist(request, command_id=first_command)
    new_version = await service.prepare_shortlist(request, command_id=uuid4())

    assert replay[0].id == first[0].id
    assert new_version[0].id != first[0].id
    assert len([row for row in session.added if isinstance(row, CandidateShortlist)]) == 2


async def test_candidate_selection_can_scope_an_explicit_pilot_dataset():
    first = _content_item(title="First AI item", score=90, is_rewrite_ready=True)
    selected = _content_item(title="Selected AI item", score=10, is_rewrite_ready=True)
    request = ContentProductionRequest(
        id=uuid4(),
        topic="AI",
        max_candidates=1,
        require_rewrite_ready=True,
        require_media=False,
        constraints_json={"pilot": True, "pilot_content_item_ids": [str(selected.id)]},
    )
    session = FakeSession(scalars_results=[[first, selected]])

    shortlist = await CandidateSelectionService(session).prepare_shortlist(request, command_id=uuid4())

    assert [row.content_item_id for row in shortlist] == [selected.id]


async def test_shortlist_decisions_are_scoped_to_one_overlapping_selection_execution():
    request_id = uuid4()
    first_execution, second_execution = uuid4(), uuid4()
    item_a, item_b, item_c = uuid4(), uuid4(), uuid4()
    first_rows = [
        _candidate_row(request_id, first_execution, item_a, rank=1),
        _candidate_row(request_id, first_execution, item_b, rank=2),
    ]
    second_rows = [
        _candidate_row(request_id, second_execution, item_a, rank=1),
        _candidate_row(request_id, second_execution, item_c, rank=2),
    ]
    all_rows = first_rows + second_rows
    session = FakeSession(scalars_results=[all_rows, all_rows, all_rows])
    service = ShortlistApprovalService(session)

    assert await service.approve(request_id, first_execution, [item_a, item_b]) == first_rows
    assert await service.approve(request_id, second_execution, [item_a, item_c]) == second_rows
    with pytest.raises(LookupError, match="not found"):
        await service.approve(request_id, first_execution, [item_a, item_c])


def _candidate_row(request_id, selection_execution_id, content_item_id, *, rank):
    return CandidateShortlist(
        id=uuid4(),
        request_id=request_id,
        selection_execution_id=selection_execution_id,
        content_item_id=content_item_id,
        rank=rank,
        score=10,
        approval_status="pending",
        selection_reason_json={},
        risk_flags_json=[],
        source_snapshot_json={},
    )


async def test_create_content_production_request_endpoint_defers_shortlist_to_worker():
    content_item = _content_item(title="AI agents launch", score=20, is_rewrite_ready=True, source_tier="A")
    fake_session = FakeSession(scalars_results=[[content_item]])
    _override_session(fake_session)

    response = await _post(
        "/content-production/requests",
        json={"topic": "AI", "max_candidates": 5, "created_by": "operator"},
    )

    app.dependency_overrides.clear()
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "created"
    assert body["shortlist"] == []
    assert fake_session.committed is True
    assert [value.event_type for value in fake_session.added if isinstance(value, WorkflowEvent)] == [
        "ContentProductionRequestCreated",
    ]


async def test_shortlist_approve_endpoint_defers_run_creation_to_worker():
    request_id = uuid4()
    content_item_id = uuid4()
    selection_execution_id = uuid4()
    candidate = CandidateShortlist(
        id=uuid4(),
        request_id=request_id,
        selection_execution_id=selection_execution_id,
        content_item_id=content_item_id,
        rank=1,
        score=10,
        approval_status="pending",
        selection_reason_json={},
        risk_flags_json=[],
        source_snapshot_json={},
    )
    fake_session = FakeSession(scalars_results=[[candidate]])
    _override_session(fake_session)

    response = await _post(
        f"/content-production/requests/{request_id}/shortlist/approve",
        json={
            "selection_execution_id": str(selection_execution_id),
            "content_item_ids": [str(content_item_id)],
        },
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0]["approval_status"] == "approved"
    assert fake_session.committed is True
    runs = [value for value in fake_session.added if value.__class__.__name__ == "ContentProductionRun"]
    assert runs == []
    events = [value for value in fake_session.added if isinstance(value, WorkflowEvent)]
    assert [event.event_type for event in events] == ["CandidateShortlistApproved"]


def _content_item(
    *,
    title: str,
    score: int,
    is_rewrite_ready: bool,
    source_tier: str = "B",
    content_type: str = "news",
):
    return ContentItem(
        id=uuid4(),
        item_type="article",
        title=title,
        summary="A useful AI summary" if "AI" in title else "General summary",
        content_text=(
            "AI systems and software agents are discussed in enough detail for ranking."
            if "AI" in title
            else "General economy overview with enough context for ranking."
        ),
        canonical_url="https://example.com/article",
        tags=["ai"] if "AI" in title else [],
        sort_at=datetime(2026, 7, 9, tzinfo=UTC),
        date_parse_status="parsed",
        status="new",
        score=score,
        content_type=content_type,
        source_tier=source_tier,
        freshness_bucket="fresh",
        quality_status="ok",
        is_rewrite_ready=is_rewrite_ready,
    )


class FakeSession:
    def __init__(self, scalars_results=None):
        self.scalars_results = list(scalars_results or [])
        self.added = []
        self.by_model_and_id = {}
        self.flushed = False
        self.committed = False

    def add(self, obj):
        self.added.append(obj)
        obj_id = getattr(obj, "event_id", None) or getattr(obj, "id", None)
        if obj_id is not None:
            self.by_model_and_id[(type(obj), obj_id)] = obj

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def get(self, model, obj_id):
        return self.by_model_and_id.get((model, obj_id))

    async def scalars(self, stmt):
        if self.scalars_results:
            return self.scalars_results.pop(0)
        return []


def _override_session(fake_session: FakeSession) -> None:
    async def override():
        yield fake_session

    app.dependency_overrides[get_session] = override


async def _post(path: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, **kwargs)
