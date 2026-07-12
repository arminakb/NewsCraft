from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from uuid import uuid4

import pytest

from app.content_production.events import WorkflowEventType
from app.content_production.repository import ContentProductionRepository, WorkflowEventConsistencyError
from app.content_production.states import InvalidWorkflowTransition, WorkflowState, require_valid_transition
from app.db.models import Base, ContentProductionRun, WorkflowEvent


def test_content_production_tables_are_registered():
    expected = {
        "content_production_requests",
        "candidate_shortlists",
        "content_production_runs",
        "agent_step_runs",
        "workflow_events",
    }

    assert expected.issubset(set(Base.metadata.tables))


def test_content_production_foundation_indexes_and_constraints_are_registered():
    request_indexes = {index.name for index in Base.metadata.tables["content_production_requests"].indexes}
    shortlist = Base.metadata.tables["candidate_shortlists"]
    run_indexes = {index.name for index in Base.metadata.tables["content_production_runs"].indexes}
    event_indexes = {index.name for index in Base.metadata.tables["workflow_events"].indexes}

    assert "ix_content_production_requests_status" in request_indexes
    assert "ix_candidate_shortlists_request_content_item" in {index.name for index in shortlist.indexes}
    assert "ix_content_production_runs_state_step" in run_indexes
    assert {
        "ix_workflow_events_status_available",
        "ix_workflow_events_correlation",
        "ix_workflow_events_aggregate",
    }.issubset(event_indexes)


def test_agent_step_run_supports_request_level_tracing_without_a_fake_run():
    table = Base.metadata.tables["agent_step_runs"]

    assert table.c.production_run_id.nullable is True


def test_agent_step_run_request_tracing_migration_is_linear_and_minimal():
    migration = Path("alembic/versions/0013_agent_step_run_request_tracing.py").read_text()

    assert "0012_telegram_dispatch_requests" in migration
    assert '"agent_step_runs", "production_run_id"' in migration
    assert "nullable=True" in migration
    assert "DELETE FROM agent_step_runs WHERE production_run_id IS NULL" in migration


def test_artifact_idempotency_migration_is_linear_and_replaces_overbroad_shortlist_constraint():
    migration = Path("alembic/versions/0014_artifact_idempotency.py").read_text()

    assert "0013_agent_step_run_request_tracing" in migration
    assert "uq_candidate_shortlists_request_content_item" in migration
    assert "ix_candidate_shortlists_request_content_item" in migration
    assert "DELETE FROM candidate_shortlists duplicate" in migration


def test_content_production_migration_adds_foundation_tables():
    migration = Path("alembic/versions/0004_content_production_foundation.py").read_text()

    assert "content_production_requests" in migration
    assert "candidate_shortlists" in migration
    assert "content_production_runs" in migration
    assert "agent_step_runs" in migration
    assert "workflow_events" in migration
    assert "0003_content_intelligence_schema" in migration
    assert '"alembic_version"' in migration
    assert "sa.String(length=64)" in migration


def test_persian_llm_generation_migration_is_linear_and_reversible():
    migration = Path("alembic/versions/0016_persian_llm_generation.py").read_text()

    assert 'down_revision = "0015_shortlist_selection_execution"' in migration
    assert "generation_metadata_json" in migration
    assert "evaluation_metadata_json" in migration
    assert 'op.drop_column("draft_quality_reports", "evaluation_metadata_json")' in migration


def test_workflow_state_allows_critical_happy_path_transitions():
    critical_path = [
        WorkflowState.CREATED,
        WorkflowState.SELECTING,
        WorkflowState.SHORTLIST_READY,
        WorkflowState.SHORTLIST_APPROVAL_PENDING,
        WorkflowState.SHORTLIST_APPROVED,
        WorkflowState.SUFFICIENCY_CHECKING,
        WorkflowState.SUFFICIENCY_SUFFICIENT,
        WorkflowState.BRIEFING,
        WorkflowState.BRIEF_READY,
        WorkflowState.DRAFTING,
        WorkflowState.DRAFT_READY,
        WorkflowState.QUALITY_CHECKING,
        WorkflowState.QUALITY_PASSED,
        WorkflowState.MEDIA_RESOLVING,
        WorkflowState.MEDIA_READY,
        WorkflowState.PACKAGING,
        WorkflowState.PACKAGE_READY,
        WorkflowState.FINAL_APPROVAL_PENDING,
        WorkflowState.FINAL_APPROVED,
        WorkflowState.DISPATCH_PENDING,
    ]

    for source, target in pairwise(critical_path):
        require_valid_transition(source, target)


def test_workflow_state_rejects_draft_before_sufficiency_and_dispatch_before_final_approval():
    with pytest.raises(InvalidWorkflowTransition):
        require_valid_transition(WorkflowState.CREATED, WorkflowState.DRAFTING)

    with pytest.raises(InvalidWorkflowTransition):
        require_valid_transition(WorkflowState.PACKAGE_READY, WorkflowState.DISPATCH_PENDING)


def test_required_workflow_event_types_are_defined():
    required = {
        "ContentProductionRequestCreated",
        "CandidateSelectionRequested",
        "CandidateShortlistPrepared",
        "CandidateShortlistApprovalRequested",
        "CandidateShortlistApproved",
        "CandidateShortlistRejected",
        "ContentSufficiencyCheckRequested",
        "ContentSufficiencyChecked",
        "ArticleExtractionRequested",
        "ArticleExtracted",
        "ArticleExtractionFailed",
        "WebEnrichmentRequested",
        "WebEnriched",
        "WebEnrichmentFailed",
        "EditorialBriefRequested",
        "EditorialBriefCreated",
        "DraftGenerationRequested",
        "DraftGenerated",
        "DraftQualityCheckRequested",
        "DraftQualityChecked",
        "DraftRevisionRequested",
        "MediaResolutionRequested",
        "MediaSelected",
        "ImageGenerationRequested",
        "ImageGenerated",
        "ImageGenerationFailed",
        "TelegramPackageRequested",
        "TelegramPackageReady",
        "FinalApprovalRequested",
        "PostPackageApproved",
        "PostPackageRejected",
        "TelegramDispatchRequested",
        "TelegramPostPublished",
        "TelegramPostFailed",
        "ProductionRunFailed",
    }

    assert required == {event.value for event in WorkflowEventType}


async def test_repository_transition_run_rejects_invalid_state():
    session = FakeSession()
    run = ContentProductionRun(request_id=uuid4(), content_item_id=uuid4(), state=WorkflowState.CREATED.value)

    with pytest.raises(InvalidWorkflowTransition):
        await ContentProductionRepository(session).transition_run(run, WorkflowState.DRAFTING)

    assert session.flushed is False
    assert run.state == WorkflowState.CREATED.value


async def test_repository_enqueue_event_once_is_idempotent_by_event_id():
    event_id = uuid4()
    aggregate_id = uuid4()
    correlation_id = uuid4()
    session = FakeSession()
    repository = ContentProductionRepository(session)

    first, first_created = await repository.enqueue_event_once(
        event_id=event_id,
        event_type=WorkflowEventType.CONTENT_PRODUCTION_REQUEST_CREATED,
        aggregate_type="content_production_request",
        aggregate_id=aggregate_id,
        correlation_id=correlation_id,
        payload={"topic": "AI"},
    )
    second, second_created = await repository.enqueue_event_once(
        event_id=event_id,
        event_type=WorkflowEventType.CONTENT_PRODUCTION_REQUEST_CREATED,
        aggregate_type="content_production_request",
        aggregate_id=aggregate_id,
        correlation_id=correlation_id,
        payload={"topic": "AI"},
    )

    assert first_created is True
    assert second_created is False
    assert first is second
    assert len(session.added) == 1
    assert isinstance(first, WorkflowEvent)


async def test_repository_rejects_conflicting_payload_for_deterministic_event_id():
    event_id = uuid4()
    aggregate_id = uuid4()
    correlation_id = uuid4()
    repository = ContentProductionRepository(FakeSession())
    await repository.enqueue_event_once(
        event_id=event_id,
        event_type=WorkflowEventType.TELEGRAM_PACKAGE_READY,
        aggregate_type="content_production_run",
        aggregate_id=aggregate_id,
        correlation_id=correlation_id,
        payload={"package_id": str(uuid4())},
    )

    with pytest.raises(WorkflowEventConsistencyError, match="conflicting identity or payload"):
        await repository.enqueue_event_once(
            event_id=event_id,
            event_type=WorkflowEventType.TELEGRAM_PACKAGE_READY,
            aggregate_type="content_production_run",
            aggregate_id=aggregate_id,
            correlation_id=correlation_id,
            payload={"package_id": str(uuid4())},
        )


@pytest.mark.parametrize("conflict_field", ["aggregate_id", "correlation_id", "causation_id"])
async def test_repository_rejects_conflicting_event_metadata(conflict_field):
    values = {
        "event_id": uuid4(),
        "event_type": WorkflowEventType.TELEGRAM_PACKAGE_READY,
        "aggregate_type": "content_production_run",
        "aggregate_id": uuid4(),
        "correlation_id": uuid4(),
        "causation_id": uuid4(),
        "payload": {"nested": {"a": 1, "b": 2}, "ordered": ["first", "second"]},
    }
    repository = ContentProductionRepository(FakeSession())
    await repository.enqueue_event_once(**values)
    conflicting = dict(values)
    conflicting[conflict_field] = uuid4()

    with pytest.raises(WorkflowEventConsistencyError):
        await repository.enqueue_event_once(**conflicting)


async def test_repository_payload_equality_is_dictionary_order_insensitive_but_list_order_sensitive():
    values = {
        "event_id": uuid4(),
        "event_type": WorkflowEventType.TELEGRAM_PACKAGE_READY,
        "aggregate_type": "content_production_run",
        "aggregate_id": uuid4(),
        "correlation_id": uuid4(),
        "causation_id": uuid4(),
    }
    repository = ContentProductionRepository(FakeSession())
    first, _ = await repository.enqueue_event_once(
        **values,
        payload={"outer": {"a": 1, "b": 2}, "ordered": ["first", "second"]},
    )
    replay, created = await repository.enqueue_event_once(
        **values,
        payload={"ordered": ["first", "second"], "outer": {"b": 2, "a": 1}},
    )
    assert replay is first
    assert created is False

    with pytest.raises(WorkflowEventConsistencyError):
        await repository.enqueue_event_once(
            **values,
            payload={"outer": {"a": 1, "b": 2}, "ordered": ["second", "first"]},
        )


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed = False
        self.by_model_and_id = {}

    def add(self, obj):
        self.added.append(obj)
        obj_id = getattr(obj, "event_id", None) or getattr(obj, "id", None)
        if obj_id is not None:
            self.by_model_and_id[(type(obj), obj_id)] = obj

    async def flush(self):
        self.flushed = True

    async def get(self, model, obj_id):
        return self.by_model_and_id.get((model, obj_id))
