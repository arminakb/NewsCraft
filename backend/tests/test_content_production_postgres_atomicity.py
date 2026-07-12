from __future__ import annotations

import asyncio
import importlib.util
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content_production import idempotency
from app.content_production.candidates import CandidateSelectionService
from app.content_production.dispatch import TelegramDispatchService
from app.content_production.enrichment import EnrichmentResponse
from app.content_production.events import WorkflowEventType
from app.content_production.handlers import build_core_event_dispatcher
from app.content_production.idempotency import create_or_get_artifact
from app.content_production.llm import LLMProviderError, LLMResponse
from app.content_production.orchestration import WorkflowEventWorker
from app.content_production.packages import TelegramPackageService
from app.content_production.repository import ContentProductionRepository
from app.content_production.telegram_drafts import TelegramDraftService
from app.content_production.tracing import WorkflowTraceService
from app.db.models import (
    AgentStepRun,
    Base,
    CandidateShortlist,
    ContentItem,
    ContentProductionRequest,
    ContentProductionRun,
    DraftQualityReport,
    EditorialBrief,
    TelegramDispatchRequest,
    TelegramDraft,
    TelegramPostPackage,
    WebEnrichmentResult,
    WorkflowEvent,
)

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://newscraft:newscraft@localhost:5432/newscraft"


@pytest.fixture
async def postgres_session_factory():
    database_url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    schema = f"test_atomicity_{uuid4().hex}"
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
    except Exception as exc:
        await engine.dispose()
        pytest.fail(
            "real PostgreSQL is required for this test; start the repository postgres service "
            f"or set TEST_DATABASE_URL ({exc})"
        )

    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def create_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            await session.execute(text(f'SET search_path TO "{schema}", public'))
            yield session

    try:
        yield create_session
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def test_request_and_outbox_event_roll_back_together_on_postgres_constraint_failure(
    postgres_session_factory,
):
    request_id = uuid4()
    event_id = uuid4()

    async with postgres_session_factory() as session:
        repository = ContentProductionRepository(session)
        request = await repository.create_request(topic="atomic rollback", created_by="integration-test")
        request_id = request.id
        assert await session.get(ContentProductionRequest, request.id) is request

        with pytest.raises(IntegrityError):
            await repository.enqueue_event_once(
                event_id=event_id,
                event_type=WorkflowEventType.CONTENT_PRODUCTION_REQUEST_CREATED,
                aggregate_type="content_production_request",
                aggregate_id=request.id,
                correlation_id=None,
                payload={"request_id": str(request.id)},
            )
        await session.rollback()

    async with postgres_session_factory() as verification_session:
        persisted_request = await verification_session.scalar(
            select(ContentProductionRequest).where(ContentProductionRequest.id == request_id)
        )
        persisted_event = await verification_session.scalar(
            select(WorkflowEvent).where(WorkflowEvent.event_id == event_id)
        )

    assert persisted_request is None
    assert persisted_event is None


async def test_postgres_permanent_brief_failure_emits_terminal_event_without_missing_greenlet(
    postgres_session_factory,
):
    fixture = await _create_editorial_brief_attempt(postgres_session_factory)
    provider = PermanentFailureLLM()

    async with postgres_session_factory() as session:
        event = await session.get(WorkflowEvent, fixture["event_id"])
        dispatcher = build_core_event_dispatcher(session, llm_provider=provider)

        await dispatcher.dispatch(event)
        await session.commit()

    async with postgres_session_factory() as session:
        failed_event = await session.scalar(
            select(WorkflowEvent).where(
                WorkflowEvent.correlation_id == fixture["request_id"],
                WorkflowEvent.event_type == WorkflowEventType.PRODUCTION_RUN_FAILED.value,
            )
        )
        traces = list(
            await session.scalars(
                select(AgentStepRun)
                .where(AgentStepRun.production_run_id == fixture["run_id"])
                .order_by(AgentStepRun.started_at)
            )
        )

    assert provider.calls == 1
    assert failed_event is not None
    assert failed_event.payload["failure_reason"] == "editorial_brief:schema_validation_failed"
    assert [(trace.step_name, trace.status) for trace in traces] == [("editorial_brief_creation", "completed")]


async def test_postgres_worker_creates_and_replays_canonical_llm_brief(postgres_session_factory):
    fixture = await _create_editorial_brief_attempt(postgres_session_factory)
    provider = SuccessfulBriefLLM()

    async with postgres_session_factory() as session:
        worker = WorkflowEventWorker(
            ContentProductionRepository(session),
            build_core_event_dispatcher(session, llm_provider=provider),
        )
        assert await worker.run_once(limit=1) == 1

    async with postgres_session_factory() as session:
        brief = await session.scalar(
            select(EditorialBrief).where(EditorialBrief.production_run_id == fixture["run_id"])
        )
        trace = await session.scalar(
            select(AgentStepRun).where(
                AgentStepRun.production_run_id == fixture["run_id"],
                AgentStepRun.step_name == "editorial_brief_creation",
            )
        )
        event = await session.get(WorkflowEvent, fixture["event_id"])
        assert brief is not None
        assert brief.generation_metadata_json["provider"] == "fake-llm"
        assert brief.generation_metadata_json["model"] == "fake-persian-model"
        assert trace.status == "completed"
        assert trace.model_name == "fake-persian-model"
        assert trace.token_usage_json == {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140}

        event.status = "pending"
        event.processed_at = None
        event.available_at = datetime.now(UTC)
        await session.commit()

    async with postgres_session_factory() as session:
        worker = WorkflowEventWorker(
            ContentProductionRepository(session),
            build_core_event_dispatcher(session, llm_provider=provider),
        )
        assert await worker.run_once(limit=1) == 1

    async with postgres_session_factory() as session:
        briefs = list(
            await session.scalars(select(EditorialBrief).where(EditorialBrief.production_run_id == fixture["run_id"]))
        )
        traces = list(
            await session.scalars(
                select(AgentStepRun).where(
                    AgentStepRun.production_run_id == fixture["run_id"],
                    AgentStepRun.step_name == "editorial_brief_creation",
                )
            )
        )

    assert provider.calls == 1
    assert len(briefs) == 1
    assert len(traces) == 2
    assert all(trace.status == "completed" for trace in traces)


async def test_failed_handler_trace_and_retry_state_persist_with_domain_rollback(postgres_session_factory):
    ids = await _create_enrichment_attempt(postgres_session_factory)

    async with postgres_session_factory() as session:
        worker = WorkflowEventWorker(
            ContentProductionRepository(session),
            build_core_event_dispatcher(session, enrichment_provider=FailingEnrichmentProvider()),
            retry_delay=timedelta(0),
        )
        assert await worker.run_once() == 1

    async with postgres_session_factory() as session:
        run = await session.get(ContentProductionRun, ids["run_id"])
        event = await session.get(WorkflowEvent, ids["event_id"])
        traces = list(
            await session.scalars(
                select(AgentStepRun)
                .where(AgentStepRun.production_run_id == ids["run_id"])
                .order_by(AgentStepRun.started_at)
            )
        )
        artifacts = list(
            await session.scalars(
                select(WebEnrichmentResult).where(WebEnrichmentResult.production_run_id == ids["run_id"])
            )
        )

    assert run.state == "sufficiency_partial"
    assert event.status == "pending"
    assert event.attempt_count == 1
    assert "provider failed deliberately" in event.last_error
    assert artifacts == []
    assert len(traces) == 1
    assert traces[0].status == "failed"
    assert traces[0].input_snapshot_json["event"]["attempt_count"] == 1
    assert traces[0].output_snapshot_json["failure_phase"] == "domain_handler"


async def test_failed_then_successful_retry_keeps_postgres_trace_history(postgres_session_factory):
    ids = await _create_enrichment_attempt(postgres_session_factory)

    async with postgres_session_factory() as session:
        worker = WorkflowEventWorker(
            ContentProductionRepository(session),
            build_core_event_dispatcher(session, enrichment_provider=FailingEnrichmentProvider()),
            retry_delay=timedelta(0),
        )
        await worker.run_once()

    async with postgres_session_factory() as session:
        worker = WorkflowEventWorker(
            ContentProductionRepository(session),
            build_core_event_dispatcher(session, enrichment_provider=SuccessfulEnrichmentProvider()),
            retry_delay=timedelta(0),
        )
        await worker.run_once()

    async with postgres_session_factory() as session:
        event = await session.get(WorkflowEvent, ids["event_id"])
        traces = list(
            await session.scalars(
                select(AgentStepRun)
                .where(
                    AgentStepRun.production_run_id == ids["run_id"],
                    AgentStepRun.step_name == "web_enrichment",
                )
                .order_by(AgentStepRun.started_at)
            )
        )
        artifacts = list(
            await session.scalars(
                select(WebEnrichmentResult).where(WebEnrichmentResult.production_run_id == ids["run_id"])
            )
        )

    assert event.status == "processed"
    assert event.attempt_count == 2
    assert [trace.status for trace in traces] == ["failed", "completed"]
    assert [trace.input_snapshot_json["event"]["attempt_count"] for trace in traces] == [1, 2]
    assert traces[0].id != traces[1].id
    assert len(artifacts) == 1


async def test_trace_finalization_failure_rolls_back_domain_work_before_retry(
    postgres_session_factory,
    monkeypatch,
):
    ids = await _create_candidate_selection_attempt(postgres_session_factory)
    original_output_snapshot = WorkflowTraceService._output_snapshot

    async def fail_output_snapshot(self, event, step_name):
        raise RuntimeError("output snapshot failed deliberately")

    monkeypatch.setattr(WorkflowTraceService, "_output_snapshot", fail_output_snapshot)
    async with postgres_session_factory() as session:
        worker = WorkflowEventWorker(
            ContentProductionRepository(session),
            build_core_event_dispatcher(session),
            retry_delay=timedelta(0),
        )
        await worker.run_once()

    async with postgres_session_factory() as session:
        request = await session.get(ContentProductionRequest, ids["request_id"])
        event = await session.get(WorkflowEvent, ids["event_id"])
        candidates = list(
            await session.scalars(
                select(CandidateShortlist).where(CandidateShortlist.request_id == ids["request_id"])
            )
        )
        failed_trace = await session.scalar(
            select(AgentStepRun).where(AgentStepRun.step_name == "candidate_selection")
        )

    assert request.status == "created"
    assert candidates == []
    assert event.status == "pending"
    assert event.attempt_count == 1
    assert failed_trace.status == "failed"
    assert failed_trace.output_snapshot_json["failure_phase"] == "output_snapshot"

    monkeypatch.setattr(WorkflowTraceService, "_output_snapshot", original_output_snapshot)
    async with postgres_session_factory() as session:
        worker = WorkflowEventWorker(
            ContentProductionRepository(session),
            build_core_event_dispatcher(session),
            retry_delay=timedelta(0),
        )
        await worker.run_once()

    async with postgres_session_factory() as session:
        traces = list(
            await session.scalars(
                select(AgentStepRun)
                .where(AgentStepRun.step_name == "candidate_selection")
                .order_by(AgentStepRun.started_at)
            )
        )
        candidates = list(
            await session.scalars(
                select(CandidateShortlist).where(CandidateShortlist.request_id == ids["request_id"])
            )
        )

    assert [trace.status for trace in traces] == ["failed", "completed"]
    assert len(candidates) == 1


async def test_completed_trace_and_domain_artifact_roll_back_on_outer_commit_failure(postgres_session_factory):
    ids = await _create_candidate_selection_attempt(postgres_session_factory)

    async with postgres_session_factory() as session:
        worker = WorkflowEventWorker(
            ConstraintFailingCommitStore(session),
            build_core_event_dispatcher(session),
        )
        with pytest.raises(IntegrityError):
            await worker.run_once()
        await session.rollback()

    async with postgres_session_factory() as session:
        event = await session.get(WorkflowEvent, ids["event_id"])
        traces = list(await session.scalars(select(AgentStepRun)))
        candidates = list(
            await session.scalars(
                select(CandidateShortlist).where(CandidateShortlist.request_id == ids["request_id"])
            )
        )

    assert event.status == "pending"
    assert event.attempt_count == 0
    assert traces == []
    assert candidates == []


async def test_migration_0013_downgrade_removes_unrepresentable_request_traces(postgres_session_factory):
    migration_path = Path("alembic/versions/0013_agent_step_run_request_tracing.py")
    spec = importlib.util.spec_from_file_location("migration_0013", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    async with postgres_session_factory() as session:
        await session.execute(text("ALTER TABLE agent_step_runs ALTER COLUMN production_run_id SET NOT NULL"))
        await session.commit()

        def upgrade(connection):
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

        connection = await session.connection()
        await connection.run_sync(upgrade)
        await session.execute(
            text(
                """
                INSERT INTO agent_step_runs (id, production_run_id, step_name, agent_name, status)
                VALUES (:id, NULL, 'request_trace', 'test', 'completed')
                """
            ),
            {"id": uuid4()},
        )
        await session.commit()

        def downgrade(connection):
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()

        connection = await session.connection()
        await connection.run_sync(downgrade)
        await session.commit()
        null_count = await session.scalar(
            text("SELECT count(*) FROM agent_step_runs WHERE production_run_id IS NULL")
        )
        nullable = await session.scalar(
            text(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'agent_step_runs'
                  AND column_name = 'production_run_id'
                """
            )
        )

    assert null_count == 0
    assert nullable == "NO"


async def test_migration_0014_allows_versions_and_downgrade_keeps_earliest(postgres_session_factory):
    migration_path = Path("alembic/versions/0014_artifact_idempotency.py")
    spec = importlib.util.spec_from_file_location("migration_0014", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    async with postgres_session_factory() as session:
        request = ContentProductionRequest(id=uuid4(), topic="migration", status="created")
        item = _content_item()
        session.add_all([request, item])
        await session.commit()
        await session.execute(text("DROP INDEX ix_candidate_shortlists_request_content_item"))
        await session.execute(
            text(
                """
                ALTER TABLE candidate_shortlists
                ADD CONSTRAINT uq_candidate_shortlists_request_content_item
                UNIQUE (request_id, content_item_id)
                """
            )
        )
        await session.commit()

        def upgrade(connection):
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

        connection = await session.connection()
        await connection.run_sync(upgrade)
        await session.commit()
        first_id, second_id = uuid4(), uuid4()
        first_execution_id, second_execution_id = uuid4(), uuid4()
        await session.execute(
            text(
                """
                INSERT INTO candidate_shortlists (
                    id, request_id, selection_execution_id, content_item_id, rank, score,
                    selection_reason_json, risk_flags_json, source_snapshot_json, approval_status
                ) VALUES
                    (:first_id, :request_id, :first_execution_id, :item_id, 1, 10,
                        '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'pending'),
                    (:second_id, :request_id, :second_execution_id, :item_id, 1, 10,
                        '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'pending')
                """
            ),
            {
                "first_id": first_id,
                "second_id": second_id,
                "first_execution_id": first_execution_id,
                "second_execution_id": second_execution_id,
                "request_id": request.id,
                "item_id": item.id,
            },
        )
        await session.commit()

        def downgrade(connection):
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()

        connection = await session.connection()
        await connection.run_sync(downgrade)
        await session.commit()
        rows = list(
            await session.scalars(
                select(CandidateShortlist).where(
                    CandidateShortlist.request_id == request.id,
                    CandidateShortlist.content_item_id == item.id,
                )
            )
        )
        assert len(rows) == 1

        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    """
                    INSERT INTO candidate_shortlists (
                        id, request_id, selection_execution_id, content_item_id, rank, score,
                        selection_reason_json, risk_flags_json, source_snapshot_json, approval_status
                    ) VALUES (:id, :request_id, :execution_id, :item_id, 2, 9,
                        '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'pending')
                    """
                ),
                {
                    "id": uuid4(),
                    "request_id": request.id,
                    "execution_id": uuid4(),
                    "item_id": item.id,
                },
            )
        await session.rollback()


async def test_migration_0015_backfills_legacy_execution_and_is_reversible(postgres_session_factory):
    migration_path = Path("alembic/versions/0015_shortlist_selection_execution.py")
    spec = importlib.util.spec_from_file_location("migration_0015", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    async with postgres_session_factory() as session:
        request = ContentProductionRequest(id=uuid4(), topic="migration 0015", status="created")
        request_id = request.id
        first_item, second_item, third_item = _content_item(), _content_item(), _content_item()
        session.add_all([request, first_item, second_item, third_item])
        await session.commit()
        await session.execute(
            text("ALTER TABLE candidate_shortlists DROP CONSTRAINT uq_candidate_shortlists_execution_content_item")
        )
        await session.execute(text("DROP INDEX ix_candidate_shortlists_request_execution"))
        await session.execute(text("ALTER TABLE candidate_shortlists DROP COLUMN selection_execution_id"))
        await session.execute(
            text(
                """
                INSERT INTO candidate_shortlists (
                    id, request_id, content_item_id, rank, score,
                    selection_reason_json, risk_flags_json, source_snapshot_json, approval_status, created_at
                ) VALUES
                    (:first_id, :request_id, :first_item_id, 1, 10,
                        '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'pending', :first_at),
                    (:second_id, :request_id, :second_item_id, 2, 9,
                        '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'pending', :second_at),
                    (:third_id, :request_id, :first_item_id, 1, 8,
                        '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'pending', :third_at),
                    (:fourth_id, :request_id, :third_item_id, 2, 7,
                        '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'pending', :fourth_at)
                """
            ),
            {
                "first_id": (first_id := uuid4()),
                "second_id": (second_id := uuid4()),
                "third_id": (third_id := uuid4()),
                "fourth_id": (fourth_id := uuid4()),
                "request_id": request.id,
                "first_item_id": first_item.id,
                "second_item_id": second_item.id,
                "third_item_id": third_item.id,
                "first_at": (first_at := datetime(2026, 7, 11, 10, 0, tzinfo=UTC)),
                "second_at": first_at + timedelta(seconds=1),
                "third_at": first_at + timedelta(seconds=2),
                "fourth_at": first_at + timedelta(seconds=3),
            },
        )
        await session.commit()

        def upgrade(connection):
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

        connection = await session.connection()
        await connection.run_sync(upgrade)
        await session.commit()
        rows = list(
            await session.scalars(
                select(CandidateShortlist)
                .where(CandidateShortlist.request_id == request_id)
                .order_by(CandidateShortlist.created_at, CandidateShortlist.id)
            )
        )
        assert [row.id for row in rows] == [first_id, second_id, third_id, fourth_id]
        assert rows[0].selection_execution_id == rows[1].selection_execution_id
        assert rows[2].selection_execution_id == rows[3].selection_execution_id
        assert rows[0].selection_execution_id != rows[2].selection_execution_id
        first_upgrade_mapping = {row.id: row.selection_execution_id for row in rows}
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    """
                    INSERT INTO candidate_shortlists (
                        id, request_id, selection_execution_id, content_item_id, rank, score,
                        selection_reason_json, risk_flags_json, source_snapshot_json, approval_status
                    ) VALUES (:id, :request_id, :execution_id, :item_id, 3, 8,
                        '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'pending')
                    """
                ),
                {
                    "id": uuid4(),
                    "request_id": request.id,
                    "execution_id": rows[0].selection_execution_id,
                    "item_id": first_item.id,
                },
            )
        await session.rollback()

        def downgrade(connection):
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()

        connection = await session.connection()
        await connection.run_sync(downgrade)
        await session.commit()
        columns = list(
            await session.scalars(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'candidate_shortlists'
                    """
                )
            )
        )
        assert "selection_execution_id" not in columns

        connection = await session.connection()
        await connection.run_sync(upgrade)
        await session.commit()
        reupgraded = list(
            await session.scalars(
                select(CandidateShortlist).where(CandidateShortlist.request_id == request_id)
            )
        )
        assert {row.id: row.selection_execution_id for row in reupgraded} == first_upgrade_mapping


async def test_postgres_tied_candidate_order_matches_in_memory_total_order(postgres_session_factory):
    request_id = uuid4()
    command_id = uuid4()
    tied_at = datetime(2026, 7, 11, tzinfo=UTC)
    items = [_content_item() for _ in range(4)]
    for item in items:
        item.score = 50
        item.sort_at = tied_at
        item.is_rewrite_ready = True

    async with postgres_session_factory() as session:
        request = ContentProductionRequest(
            id=request_id,
            topic=None,
            max_candidates=2,
            require_rewrite_ready=True,
            require_media=False,
            status="created",
        )
        session.add_all([request, *reversed(items)])
        await session.commit()
        selected = await CandidateSelectionService(session).prepare_shortlist(request, command_id=command_id)
        await session.commit()
        replayed = await CandidateSelectionService(session).prepare_shortlist(request, command_id=command_id)
        await session.commit()

    expected = sorted((item.id for item in items), key=str)[:2]
    assert [candidate.content_item_id for candidate in selected] == expected
    assert [candidate.content_item_id for candidate in replayed] == expected
    assert [candidate.id for candidate in replayed] == [candidate.id for candidate in selected]


async def test_postgres_selection_uses_calculated_business_score(postgres_session_factory):
    raw_score_winner = _content_item()
    raw_score_winner.score = 90
    raw_score_winner.source_tier = "C"
    calculated_winner = _content_item()
    calculated_winner.score = 86
    calculated_winner.source_tier = "A"
    request = ContentProductionRequest(
        id=uuid4(),
        topic="AI",
        max_candidates=1,
        require_rewrite_ready=True,
        require_media=False,
        status="created",
    )

    async with postgres_session_factory() as session:
        session.add_all([request, raw_score_winner, calculated_winner])
        await session.commit()
        selected = await CandidateSelectionService(session).prepare_shortlist(request, command_id=uuid4())

    assert raw_score_winner.score > calculated_winner.score
    assert selected[0].content_item_id == calculated_winner.id


async def test_postgres_selection_uses_stable_persisted_timestamp_order(postgres_session_factory):
    first, second, third = _content_item(), _content_item(), _content_item()
    first.sort_at = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    first.created_at = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    second.sort_at = datetime(2026, 7, 11, 11, 0, tzinfo=UTC)
    second.created_at = datetime(2026, 7, 11, 11, 0, tzinfo=UTC)
    third.sort_at = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
    third.created_at = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
    request = ContentProductionRequest(
        id=uuid4(), topic=None, max_candidates=3, require_rewrite_ready=True, require_media=False, status="created"
    )

    async with postgres_session_factory() as session:
        session.add_all([request, third, first, second])
        await session.commit()
        selected = await CandidateSelectionService(session).prepare_shortlist(request, command_id=uuid4())

    assert [candidate.content_item_id for candidate in selected] == [first.id, second.id, third.id]


async def test_postgres_selection_does_not_prelimit_by_raw_score(postgres_session_factory):
    target = _content_item()
    target.score = 40
    target.source_tier = "A"
    target.is_rewrite_ready = True
    decoys = [_content_item() for _ in range(30)]
    for decoy in decoys:
        decoy.score = 50
        decoy.source_tier = "C"
        decoy.is_rewrite_ready = False
    request = ContentProductionRequest(
        id=uuid4(), topic=None, max_candidates=1, require_rewrite_ready=False, require_media=False, status="created"
    )

    async with postgres_session_factory() as session:
        session.add_all([request, *decoys, target])
        await session.commit()
        selected = await CandidateSelectionService(session).prepare_shortlist(request, command_id=uuid4())

    assert selected[0].content_item_id == target.id


async def test_concurrent_production_run_creation_returns_one_canonical_row(
    postgres_session_factory, monkeypatch
):
    request_id, item_id = await _create_request_and_item(postgres_session_factory)
    command_id = uuid4()
    race = _force_primary_key_conflict(monkeypatch)

    async def create_run():
        async with postgres_session_factory() as session:
            run = await ContentProductionRepository(session).create_run(
                request_id=request_id,
                content_item_id=item_id,
                initial_state="shortlist_approved",
                command_id=command_id,
            )
            assert await session.scalar(select(1)) == 1
            race["usable_sessions"] += 1
            await session.commit()
            return run.id

    ids = await asyncio.gather(create_run(), create_run())

    async with postgres_session_factory() as session:
        rows = list(
            await session.scalars(
                select(ContentProductionRun).where(
                    ContentProductionRun.request_id == request_id,
                    ContentProductionRun.content_item_id == item_id,
                )
            )
        )

    assert ids[0] == ids[1]
    assert len([row for row in rows if row.id == ids[0]]) == 1
    _assert_forced_conflict(race)


async def test_concurrent_draft_creation_returns_one_canonical_row(postgres_session_factory, monkeypatch):
    fixture = await _create_artifact_concurrency_fixture(postgres_session_factory, run_state="brief_ready")
    command_id = uuid4()
    race = _force_primary_key_conflict(monkeypatch)

    async def create_draft():
        async with postgres_session_factory() as session:
            run = await session.get(ContentProductionRun, fixture["run_id"])
            brief = await session.get(EditorialBrief, fixture["brief_id"])
            draft = await TelegramDraftService(session).create_draft(
                run=run,
                brief=brief,
                command_id=command_id,
            )
            assert await session.scalar(select(1)) == 1
            race["usable_sessions"] += 1
            await session.commit()
            return draft.id

    ids = await asyncio.gather(create_draft(), create_draft())

    async with postgres_session_factory() as session:
        rows = list(
            await session.scalars(
                select(TelegramDraft).where(TelegramDraft.production_run_id == fixture["run_id"])
            )
        )

    assert ids[0] == ids[1]
    assert len([row for row in rows if row.id == ids[0]]) == 1
    _assert_forced_conflict(race)


async def test_concurrent_package_creation_returns_one_canonical_row(postgres_session_factory, monkeypatch):
    fixture = await _create_artifact_concurrency_fixture(postgres_session_factory, run_state="media_ready")
    command_id = uuid4()
    race = _force_primary_key_conflict(monkeypatch)

    async def create_package():
        async with postgres_session_factory() as session:
            run = await session.get(ContentProductionRun, fixture["run_id"])
            draft = await session.get(TelegramDraft, fixture["draft_id"])
            quality = await session.get(DraftQualityReport, fixture["quality_id"])
            package = await TelegramPackageService(session).build_package(
                run=run,
                draft=draft,
                quality_report=quality,
                command_id=command_id,
            )
            assert await session.scalar(select(1)) == 1
            race["usable_sessions"] += 1
            await session.commit()
            return package.id

    ids = await asyncio.gather(create_package(), create_package())

    async with postgres_session_factory() as session:
        rows = list(
            await session.scalars(
                select(TelegramPostPackage).where(TelegramPostPackage.production_run_id == fixture["run_id"])
            )
        )

    assert ids[0] == ids[1]
    assert len([row for row in rows if row.id == ids[0]]) == 1
    _assert_forced_conflict(race)


async def test_concurrent_dispatch_creation_returns_one_canonical_row(postgres_session_factory, monkeypatch):
    fixture = await _create_artifact_concurrency_fixture(postgres_session_factory, run_state="final_approved")
    command_id = uuid4()
    race = _force_primary_key_conflict(monkeypatch)

    async def create_dispatch():
        async with postgres_session_factory() as session:
            run = await session.get(ContentProductionRun, fixture["run_id"])
            package = await session.get(TelegramPostPackage, fixture["package_id"])
            dispatch = await TelegramDispatchService(
                session,
                bot_token="configured",
                channel_id="@channel",
            ).create_dispatch_request(run=run, package=package, command_id=command_id)
            assert await session.scalar(select(1)) == 1
            race["usable_sessions"] += 1
            await session.commit()
            return dispatch.id

    ids = await asyncio.gather(create_dispatch(), create_dispatch())

    async with postgres_session_factory() as session:
        rows = list(
            await session.scalars(
                select(TelegramDispatchRequest).where(
                    TelegramDispatchRequest.production_run_id == fixture["run_id"]
                )
            )
        )

    assert ids[0] == ids[1]
    assert len(rows) == 1
    _assert_forced_conflict(race)


async def test_unrelated_postgres_integrity_error_is_not_treated_as_replay(
    postgres_session_factory,
):
    object_id = uuid4()
    missing_request_id = uuid4()
    missing_item_id = uuid4()

    async with postgres_session_factory() as session:
        async def create_invalid_run():
            run = ContentProductionRun(
                id=object_id,
                request_id=missing_request_id,
                content_item_id=missing_item_id,
                state="created",
            )
            session.add(run)
            await session.flush()
            return run

        with pytest.raises(IntegrityError) as exc_info:
            await create_or_get_artifact(session, ContentProductionRun, object_id, create_invalid_run)

        assert idempotency._constraint_name(exc_info.value) != "content_production_runs_pkey"
        assert await session.scalar(select(1)) == 1
        assert await session.get(ContentProductionRun, object_id) is None


def _force_primary_key_conflict(monkeypatch):
    barrier = asyncio.Barrier(2)
    original_get = idempotency._get_by_id
    original_constraint_name = idempotency._constraint_name
    first_lookup_tasks = set()
    evidence = {"initial_misses": 0, "primary_key_conflicts": 0, "usable_sessions": 0}

    async def synchronized_get(session, model, object_id):
        result = await original_get(session, model, object_id)
        task = asyncio.current_task()
        if result is None and task not in first_lookup_tasks:
            first_lookup_tasks.add(task)
            evidence["initial_misses"] += 1
            await barrier.wait()
        return result

    def counted_constraint_name(exc):
        name = original_constraint_name(exc)
        if name and name.endswith("_pkey"):
            evidence["primary_key_conflicts"] += 1
        return name

    monkeypatch.setattr(idempotency, "_get_by_id", synchronized_get)
    monkeypatch.setattr(idempotency, "_constraint_name", counted_constraint_name)
    return evidence


def _assert_forced_conflict(evidence):
    assert evidence == {"initial_misses": 2, "primary_key_conflicts": 1, "usable_sessions": 2}


class FailingEnrichmentProvider:
    provider_name = "failing-test-provider"

    async def search(self, query):
        raise RuntimeError("provider failed deliberately")


class SuccessfulEnrichmentProvider:
    provider_name = "successful-test-provider"

    async def search(self, query):
        return EnrichmentResponse(status="ok")


class PermanentFailureLLM:
    provider_name = "fake-llm"

    def __init__(self):
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        raise LLMProviderError("schema_validation_failed", retryable=False)


class SuccessfulBriefLLM:
    provider_name = "fake-llm"

    def __init__(self):
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        assert request.operation == "editorial_brief"
        return LLMResponse(
            output={
                "central_claim": "یک خبر مستند درباره محصول جدید",
                "why_it_matters": "این خبر برای کاربران فناوری اهمیت دارد.",
                "key_facts": [{"claim": "محصول جدید معرفی شده است.", "evidence_ids": ["rss:title"]}],
                "important_entities": ["OpenAI"],
                "source_context": [
                    {"context": "اطلاعات از منبع اصلی است.", "evidence_ids": ["rss:excerpt"]}
                ],
                "uncertainties": [],
                "prohibited_claims": ["جزئیات تاییدنشده اضافه نشود"],
                "persian_angle": "معرفی روشن محصول و کاربرد آن",
                "suggested_structure": ["تیتر", "خلاصه", "منبع"],
            },
            provider_name=self.provider_name,
            model_name="fake-persian-model",
            input_tokens=100,
            output_tokens=40,
            total_tokens=140,
            latency_ms=12.5,
        )


class ConstraintFailingCommitStore(ContentProductionRepository):
    async def commit(self) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO workflow_events (
                    event_id, event_type, aggregate_type, aggregate_id, correlation_id, payload, status, attempt_count
                ) VALUES (
                    :event_id, 'CommitFailure', 'test', :aggregate_id, NULL, '{}'::jsonb, 'pending', 0
                )
                """
            ),
            {"event_id": uuid4(), "aggregate_id": uuid4()},
        )
        await super().commit()


async def _create_enrichment_attempt(postgres_session_factory) -> dict[str, object]:
    async with postgres_session_factory() as session:
        request = ContentProductionRequest(id=uuid4(), topic="trace retry", status="created")
        item = _content_item()
        run = ContentProductionRun(
            id=uuid4(),
            request_id=request.id,
            content_item_id=item.id,
            platform="telegram",
            state="sufficiency_partial",
        )
        event = _event(WorkflowEventType.WEB_ENRICHMENT_REQUESTED, run.id, request.id)
        session.add_all([request, item, run, event])
        await session.commit()
        return {"run_id": run.id, "event_id": event.event_id}


async def _create_editorial_brief_attempt(postgres_session_factory) -> dict[str, object]:
    async with postgres_session_factory() as session:
        request = ContentProductionRequest(
            id=uuid4(),
            topic=None,
            tone="professional",
            audience="Persian Telegram readers",
            status="shortlist_approved",
        )
        item = _content_item()
        run = ContentProductionRun(
            id=uuid4(),
            request_id=request.id,
            content_item_id=item.id,
            platform="telegram",
            state="sufficiency_sufficient",
            current_step="content_sufficiency",
        )
        event = _event(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED, run.id, request.id)
        session.add_all([request, item, run, event])
        await session.commit()
        return {
            "request_id": request.id,
            "run_id": run.id,
            "event_id": event.event_id,
        }


async def _create_candidate_selection_attempt(postgres_session_factory) -> dict[str, object]:
    async with postgres_session_factory() as session:
        request = ContentProductionRequest(
            id=uuid4(),
            topic="AI",
            platform="telegram",
            language="fa",
            max_candidates=1,
            require_rewrite_ready=True,
            require_media=False,
            status="created",
            constraints_json={},
        )
        item = _content_item()
        event = WorkflowEvent(
            event_id=uuid4(),
            event_type=WorkflowEventType.CANDIDATE_SELECTION_REQUESTED.value,
            aggregate_type="content_production_request",
            aggregate_id=request.id,
            correlation_id=request.id,
            payload={"request_id": str(request.id), "max_candidates": 1},
            status="pending",
            attempt_count=0,
            available_at=datetime.now(UTC),
        )
        session.add_all([request, item, event])
        await session.commit()
        return {"request_id": request.id, "event_id": event.event_id}


def _content_item() -> ContentItem:
    return ContentItem(
        id=uuid4(),
        item_type="rss",
        title="AI platform launch",
        summary="A complete source summary.",
        content_text="A complete source body with enough detail for candidate selection.",
        canonical_url="https://example.com/ai",
        tags=["ai"],
        sort_at=datetime.now(UTC),
        date_parse_status="parsed",
        status="new",
        score=50,
        content_type="news",
        source_tier="A",
        freshness_bucket="fresh",
        quality_status="ok",
        is_rewrite_ready=True,
    )


def _event(event_type: WorkflowEventType, run_id, correlation_id) -> WorkflowEvent:
    return WorkflowEvent(
        event_id=uuid4(),
        event_type=event_type.value,
        aggregate_type="content_production_run",
        aggregate_id=run_id,
        correlation_id=correlation_id,
        payload={"production_run_id": str(run_id)},
        status="pending",
        attempt_count=0,
        available_at=datetime.now(UTC),
    )


async def _create_request_and_item(postgres_session_factory):
    async with postgres_session_factory() as session:
        request = ContentProductionRequest(id=uuid4(), topic="idempotency", status="created")
        item = _content_item()
        session.add_all([request, item])
        await session.commit()
        return request.id, item.id


async def _create_artifact_concurrency_fixture(postgres_session_factory, *, run_state: str) -> dict[str, object]:
    async with postgres_session_factory() as session:
        request = ContentProductionRequest(id=uuid4(), topic="idempotency", status="created")
        item = _content_item()
        run = ContentProductionRun(
            id=uuid4(),
            request_id=request.id,
            content_item_id=item.id,
            platform="telegram",
            state=run_state,
        )
        brief = EditorialBrief(
            id=uuid4(),
            production_run_id=run.id,
            angle="Canonical brief",
            key_facts_json=[{"claim": "A fact", "source_url": item.canonical_url}],
            source_claims_json=[],
            unsafe_or_unverified_claims_json=[],
            do_not_say_json=[],
        )
        draft = TelegramDraft(
            id=uuid4(),
            production_run_id=run.id,
            brief_id=brief.id,
            draft_text="Canonical draft",
            title="Canonical",
            hashtags_json=[],
            source_links_json=[item.canonical_url],
            warnings_json=[],
            status="draft",
        )
        quality = DraftQualityReport(
            id=uuid4(),
            production_run_id=run.id,
            draft_id=draft.id,
            status="passed",
            score=1,
            factuality_warnings_json=[],
            unsupported_claims_json=[],
            style_warnings_json=[],
            required_revisions_json=[],
        )
        package = TelegramPostPackage(
            id=uuid4(),
            production_run_id=run.id,
            draft_id=draft.id,
            package_json={"post_text": "Canonical", "source_links": [], "media": {}},
            approval_status="approved",
        )
        session.add_all([request, item])
        await session.flush()
        session.add(run)
        await session.flush()
        session.add(brief)
        await session.flush()
        session.add(draft)
        await session.flush()
        session.add_all([quality, package])
        await session.commit()
        return {
            "run_id": run.id,
            "brief_id": brief.id,
            "draft_id": draft.id,
            "quality_id": quality.id,
            "package_id": package.id,
        }
