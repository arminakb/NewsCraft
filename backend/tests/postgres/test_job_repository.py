from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.generation.default_prompts import (
    seed_default_telegram_configuration,
    seed_default_telegram_prompt,
)
from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplate, PromptTemplateVersion
from app.jobs.errors import InvalidJobTransition
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus

NOW = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)


async def test_default_telegram_seed_is_concurrency_safe_across_two_sessions(
    session_factory: async_sessionmaker[AsyncSession],
):
    async def seed_once():
        async with session_factory() as session:
            prompt = await seed_default_telegram_prompt(session)
            configuration = await seed_default_telegram_configuration(session, openrouter_available=True)
            await session.commit()
            return prompt.id, configuration.brand.id, tuple(sorted(item.id for item in configuration.providers))

    first, second = await asyncio.gather(seed_once(), seed_once())
    assert first == second

    async with session_factory() as session:
        assert len(list(await session.scalars(select(PromptTemplate)))) == 1
        assert len(list(await session.scalars(select(PromptTemplateVersion)))) == 1
        assert len(list(await session.scalars(select(BrandProfile)))) == 1
        assert len(list(await session.scalars(select(AIProviderProfile)))) == 2


async def enqueue_claimed_job(
    repository: JobRepository,
    *,
    key: str,
    worker_id: str = "worker-1",
    max_attempts: int = 3,
    now: datetime = NOW,
) -> WorkflowJob:
    enqueued = await repository.enqueue_job(
        job_type="ingest.collect",
        payload={},
        idempotency_key=key,
        origin=JobOrigin.AUTOMATION,
        max_attempts=max_attempts,
        scheduled_for=now,
    )
    claimed = await repository.claim_next_job(worker_id=worker_id, lease_seconds=120, now=now)
    assert claimed is not None
    assert claimed.id == enqueued.job.id
    return claimed


async def event_types(session: AsyncSession, job_id) -> Counter[str]:
    result = await session.scalars(select(WorkflowEvent.event_type).where(WorkflowEvent.workflow_job_id == job_id))
    return Counter(result)


async def test_enqueue_is_idempotent_and_emits_one_event(job_repository: JobRepository, db_session: AsyncSession):
    first = await job_repository.enqueue_job(
        job_type="ingest.collect",
        payload={"source": "rss"},
        idempotency_key="collect:one",
        origin=JobOrigin.SCHEDULER,
    )
    second = await job_repository.enqueue_job(
        job_type="ingest.collect",
        payload={"source": "different"},
        idempotency_key="collect:one",
        origin=JobOrigin.SCHEDULER,
    )

    assert first.created is True
    assert second.created is False
    assert second.job.id == first.job.id
    assert second.job.payload == {"source": "rss"}
    assert await event_types(db_session, first.job.id) == Counter(["job.enqueued"])


async def test_enqueue_without_schedule_persists_timezone_aware_runtime_schedule(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    before = datetime.now(UTC)

    result = await job_repository.enqueue_job(
        job_type="ingest.collect",
        payload={},
        idempotency_key="default-runtime-schedule",
        origin=JobOrigin.MANUAL,
    )
    await db_session.commit()
    await db_session.refresh(result.job)

    assert before <= result.job.scheduled_for <= datetime.now(UTC)


async def test_idempotent_enqueue_repairs_legacy_null_schedule(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    legacy = WorkflowJob(
        job_type="ingest.collect",
        payload={},
        idempotency_key="legacy-null-schedule",
        origin=JobOrigin.MANUAL,
        scheduled_for=None,
    )
    db_session.add(legacy)
    await db_session.commit()

    result = await job_repository.enqueue_job(
        job_type="ingest.collect",
        payload={"ignored": True},
        idempotency_key="legacy-null-schedule",
        origin=JobOrigin.MANUAL,
    )
    await db_session.commit()
    await db_session.refresh(result.job)

    assert result.created is False
    assert result.job.id == legacy.id
    assert result.job.scheduled_for is not None
    assert result.job.scheduled_for.tzinfo is not None


async def test_claim_uses_skip_locked_to_let_another_session_claim_a_different_job(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as seed_session:
        seed_repository = JobRepository(seed_session)
        await seed_repository.enqueue_job(
            job_type="first",
            payload={},
            idempotency_key="first",
            origin=JobOrigin.AUTOMATION,
            scheduled_for=NOW,
        )
        await seed_repository.enqueue_job(
            job_type="second",
            payload={},
            idempotency_key="second",
            origin=JobOrigin.AUTOMATION,
            scheduled_for=NOW,
        )
        await seed_session.commit()

    async with session_factory() as session_a, session_factory() as session_b:
        first = await JobRepository(session_a).claim_next_job(worker_id="worker-a", lease_seconds=120, now=NOW)
        second = await asyncio.wait_for(
            JobRepository(session_b).claim_next_job(worker_id="worker-b", lease_seconds=120, now=NOW),
            timeout=2,
        )

        assert first is not None
        assert second is not None
        assert first.id != second.id
        await session_a.rollback()
        await session_b.rollback()


async def test_actual_claim_statement_contains_postgresql_skip_locked(
    job_repository: JobRepository,
    postgres_engine: AsyncEngine,
):
    await job_repository.enqueue_job(
        job_type="ingest.collect",
        payload={},
        idempotency_key="sql-shape",
        origin=JobOrigin.AUTOMATION,
        scheduled_for=NOW,
    )
    statements = []

    def record_statement(_conn, clauseelement, _multiparams, _params, _execution_options):
        statements.append(clauseelement)

    event.listen(postgres_engine.sync_engine, "before_execute", record_statement)
    try:
        claimed = await job_repository.claim_next_job(worker_id="worker-1", lease_seconds=120, now=NOW)
    finally:
        event.remove(postgres_engine.sync_engine, "before_execute", record_statement)

    assert claimed is not None
    compiled = [
        str(statement.compile(dialect=postgresql.dialect())).upper()
        for statement in statements
        if "WORKFLOW_JOBS" in str(statement.compile(dialect=postgresql.dialect())).upper()
    ]
    assert any("FOR UPDATE SKIP LOCKED" in statement for statement in compiled)


async def test_claim_filters_job_type_before_lock_or_state_change(
    job_repository: JobRepository,
    postgres_engine: AsyncEngine,
):
    source = await job_repository.enqueue_job(
        job_type="telegram.route.poll",
        payload={},
        idempotency_key="source-job",
        origin=JobOrigin.AUTOMATION,
        priority=100,
        scheduled_for=NOW,
    )
    publish = await job_repository.enqueue_job(
        job_type="telegram.publish",
        payload={},
        idempotency_key="publish-job",
        origin=JobOrigin.AUTOMATION,
        scheduled_for=NOW,
    )
    statements = []

    def record_statement(_conn, clauseelement, _multiparams, _params, _execution_options):
        statements.append(clauseelement)

    event.listen(postgres_engine.sync_engine, "before_execute", record_statement)
    try:
        claimed = await job_repository.claim_next_job(
            worker_id="publisher-1",
            lease_seconds=120,
            allowed_job_types=("telegram.destination.check", "telegram.publish"),
            now=NOW,
        )
    finally:
        event.remove(postgres_engine.sync_engine, "before_execute", record_statement)

    assert claimed is not None
    assert claimed.id == publish.job.id
    untouched = await job_repository.get_job(source.job.id)
    assert untouched is not None
    assert untouched.status == JobStatus.QUEUED
    assert untouched.lease_owner is None
    assert untouched.attempt_count == 0
    claim_sql = [
        str(statement.compile(dialect=postgresql.dialect())).upper()
        for statement in statements
        if "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect())).upper()
    ]
    assert len(claim_sql) == 1
    assert "WORKFLOW_JOBS.JOB_TYPE IN" in claim_sql[0]
    assert "SKIP LOCKED" in claim_sql[0]


async def test_empty_allowed_job_types_returns_without_a_query_or_mutation(
    job_repository: JobRepository,
    postgres_engine: AsyncEngine,
):
    queued = await job_repository.enqueue_job(
        job_type="ingest.collect", payload={}, idempotency_key="empty-capability", origin=JobOrigin.AUTOMATION
    )
    statements = []

    def record_statement(_conn, clauseelement, _multiparams, _params, _execution_options):
        statements.append(clauseelement)

    event.listen(postgres_engine.sync_engine, "before_execute", record_statement)
    try:
        assert (
            await job_repository.claim_next_job(worker_id="worker-1", lease_seconds=120, allowed_job_types=(), now=NOW)
            is None
        )
    finally:
        event.remove(postgres_engine.sync_engine, "before_execute", record_statement)

    assert statements == []
    assert queued.job.status == JobStatus.QUEUED
    assert queued.job.lease_owner is None
    assert queued.job.attempt_count == 0


async def test_none_allowed_job_types_keeps_claim_any_behavior(job_repository: JobRepository):
    queued = await job_repository.enqueue_job(
        job_type="future.registered.type",
        payload={},
        idempotency_key="claim-any",
        origin=JobOrigin.AUTOMATION,
        scheduled_for=NOW,
    )

    claimed = await job_repository.claim_next_job(
        worker_id="worker-1", lease_seconds=120, allowed_job_types=None, now=NOW
    )

    assert claimed is not None
    assert claimed.id == queued.job.id


async def test_claim_orders_by_priority_then_schedule_then_creation(job_repository: JobRepository):
    low_priority = await job_repository.enqueue_job(
        job_type="ordered",
        payload={},
        idempotency_key="low",
        origin=JobOrigin.AUTOMATION,
        priority=1,
        scheduled_for=NOW,
    )
    later_schedule = await job_repository.enqueue_job(
        job_type="ordered",
        payload={},
        idempotency_key="later-schedule",
        origin=JobOrigin.AUTOMATION,
        priority=10,
        scheduled_for=NOW - timedelta(minutes=1),
    )
    earlier_created = await job_repository.enqueue_job(
        job_type="ordered",
        payload={},
        idempotency_key="earlier-created",
        origin=JobOrigin.AUTOMATION,
        priority=10,
        scheduled_for=NOW - timedelta(minutes=2),
    )
    later_created = await job_repository.enqueue_job(
        job_type="ordered",
        payload={},
        idempotency_key="later-created",
        origin=JobOrigin.AUTOMATION,
        priority=10,
        scheduled_for=NOW - timedelta(minutes=2),
    )
    earlier_created.job.created_at = NOW - timedelta(hours=2)
    later_created.job.created_at = NOW - timedelta(hours=1)
    await job_repository.session.flush()

    claimed_ids = []
    for worker_number in range(4):
        claimed = await job_repository.claim_next_job(worker_id=f"worker-{worker_number}", lease_seconds=120, now=NOW)
        assert claimed is not None
        claimed_ids.append(claimed.id)

    assert claimed_ids == [
        earlier_created.job.id,
        later_created.job.id,
        later_schedule.job.id,
        low_priority.job.id,
    ]


async def test_capability_filter_is_applied_before_claim_ordering(job_repository: JobRepository):
    unsupported = await job_repository.enqueue_job(
        job_type="unsupported",
        payload={},
        idempotency_key="unsupported-high",
        origin=JobOrigin.AUTOMATION,
        priority=99,
        scheduled_for=NOW,
    )
    supported = await job_repository.enqueue_job(
        job_type="supported",
        payload={},
        idempotency_key="supported-low",
        origin=JobOrigin.AUTOMATION,
        priority=1,
        scheduled_for=NOW,
    )

    claimed = await job_repository.claim_next_job(
        worker_id="worker-1", lease_seconds=120, allowed_job_types=("supported",), now=NOW
    )

    assert claimed is not None
    assert claimed.id == supported.job.id
    assert unsupported.job.status == JobStatus.QUEUED


async def test_future_job_is_not_claimed(job_repository: JobRepository):
    await job_repository.enqueue_job(
        job_type="future",
        payload={},
        idempotency_key="future",
        origin=JobOrigin.SCHEDULER,
        scheduled_for=NOW + timedelta(seconds=1),
    )

    assert await job_repository.claim_next_job(worker_id="worker-1", lease_seconds=120, now=NOW) is None


async def test_global_pause_holds_sensitive_work_but_allows_manual_non_sensitive_work(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    await db_session.execute(
        update(AutomationControl).where(AutomationControl.id == "global").values(global_pause=True)
    )
    sensitive = await job_repository.enqueue_job(
        job_type="scheduled",
        payload={},
        idempotency_key="sensitive",
        origin=JobOrigin.SCHEDULER,
        scheduled_for=NOW,
    )
    manual = await job_repository.enqueue_job(
        job_type="manual",
        payload={},
        idempotency_key="manual-non-sensitive",
        origin=JobOrigin.MANUAL,
        pause_sensitive=False,
        scheduled_for=NOW,
    )

    claimed = await job_repository.claim_next_job(worker_id="worker-1", lease_seconds=120, now=NOW)

    assert claimed is not None
    assert claimed.id == manual.job.id
    assert sensitive.job.status == JobStatus.QUEUED
    assert await job_repository.claim_next_job(worker_id="worker-2", lease_seconds=120, now=NOW) is None


async def test_claim_fills_running_attempt_and_lease_fields_and_emits_event(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    queued = await job_repository.enqueue_job(
        job_type="ingest.collect",
        payload={},
        idempotency_key="claim-fields",
        origin=JobOrigin.AUTOMATION,
        scheduled_for=NOW,
    )

    claimed = await job_repository.claim_next_job(worker_id="worker-1", lease_seconds=120, now=NOW)

    assert claimed is not None
    assert claimed.id == queued.job.id
    assert claimed.status == JobStatus.RUNNING
    assert claimed.attempt_count == 1
    assert claimed.lease_owner == "worker-1"
    assert claimed.lease_expires_at == NOW + timedelta(seconds=120)
    assert claimed.heartbeat_at == NOW
    assert claimed.started_at == NOW
    assert await event_types(db_session, claimed.id) == Counter(["job.enqueued", "job.claimed"])


async def test_heartbeat_only_current_owner_updates_progress_and_event(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    claimed = await enqueue_claimed_job(job_repository, key="heartbeat")

    assert (
        await job_repository.heartbeat_job(
            job_id=claimed.id,
            worker_id="wrong-worker",
            lease_seconds=60,
            progress=15,
            progress_message="wrong",
            now=NOW + timedelta(seconds=10),
        )
        is False
    )
    assert (
        await job_repository.heartbeat_job(
            job_id=claimed.id,
            worker_id="worker-1",
            lease_seconds=60,
            progress=40,
            progress_message="Fetched 4/10",
            now=NOW + timedelta(seconds=20),
        )
        is True
    )
    assert claimed.progress == 40
    assert claimed.progress_message == "Fetched 4/10"
    assert claimed.heartbeat_at == NOW + timedelta(seconds=20)
    assert claimed.lease_expires_at == NOW + timedelta(seconds=80)
    assert await event_types(db_session, claimed.id) == Counter(["job.enqueued", "job.claimed", "job.heartbeat"])


async def test_expired_lease_owner_cannot_heartbeat(job_repository: JobRepository):
    claimed = await enqueue_claimed_job(job_repository, key="expired-heartbeat", now=NOW)

    assert (
        await job_repository.heartbeat_job(
            job_id=claimed.id,
            worker_id="worker-1",
            lease_seconds=120,
            progress=50,
            now=NOW + timedelta(seconds=121),
        )
        is False
    )
    assert claimed.status == JobStatus.RUNNING
    assert claimed.lease_expires_at == NOW + timedelta(seconds=120)


async def test_expired_lease_owner_cannot_finish(job_repository: JobRepository):
    claimed = await enqueue_claimed_job(job_repository, key="expired-finish", now=NOW)

    with pytest.raises(InvalidJobTransition):
        await job_repository.finish_job(
            job_id=claimed.id,
            worker_id="worker-1",
            result={"stale": True},
            now=NOW + timedelta(seconds=121),
        )
    assert claimed.status == JobStatus.RUNNING


async def test_expired_lease_owner_cannot_fail(job_repository: JobRepository):
    claimed = await enqueue_claimed_job(job_repository, key="expired-fail", now=NOW)

    with pytest.raises(InvalidJobTransition):
        await job_repository.fail_job(
            job_id=claimed.id,
            worker_id="worker-1",
            error_class=JobErrorClass.RETRYABLE,
            error_code="stale_worker",
            error_message="Stale worker result",
            retry_at=NOW + timedelta(minutes=5),
            now=NOW + timedelta(seconds=121),
        )
    assert claimed.status == JobStatus.RUNNING


async def test_checkpoint_requires_live_owner_and_persists_redacted_handler_state(
    job_repository: JobRepository,
):
    claimed = await enqueue_claimed_job(job_repository, key="checkpoint", now=NOW)

    with pytest.raises(InvalidJobTransition):
        await job_repository.checkpoint_job(
            job_id=claimed.id,
            worker_id="wrong-worker",
            result={"ignored": True},
            now=NOW + timedelta(seconds=1),
        )
    await job_repository.checkpoint_job(
        job_id=claimed.id,
        worker_id="worker-1",
        payload={"normalized": True},
        result={"completed": ["instagram"], "token": "secret-canary"},
        now=NOW + timedelta(seconds=1),
    )

    assert claimed.payload == {"normalized": True}
    assert claimed.result == {"completed": ["instagram"], "token": "[REDACTED]"}
    with pytest.raises(InvalidJobTransition):
        await job_repository.checkpoint_job(
            job_id=claimed.id,
            worker_id="worker-1",
            result={"stale": True},
            now=NOW + timedelta(seconds=121),
        )


async def test_released_owner_cannot_finish_or_fail_new_owner_lease(job_repository: JobRepository):
    first_claim = await enqueue_claimed_job(job_repository, key="re-leased-owner", now=NOW)
    assert await job_repository.requeue_expired_leases(now=NOW + timedelta(seconds=121)) == 1
    second_claim = await job_repository.claim_next_job(
        worker_id="worker-2",
        lease_seconds=120,
        now=NOW + timedelta(seconds=121),
    )
    assert second_claim is not None
    assert second_claim.id == first_claim.id

    with pytest.raises(InvalidJobTransition):
        await job_repository.finish_job(
            job_id=first_claim.id,
            worker_id="worker-1",
            result={"stale": True},
            now=NOW + timedelta(seconds=122),
        )
    with pytest.raises(InvalidJobTransition):
        await job_repository.fail_job(
            job_id=first_claim.id,
            worker_id="worker-1",
            error_class=JobErrorClass.RETRYABLE,
            error_code="stale_worker",
            error_message="Stale worker result",
            now=NOW + timedelta(seconds=122),
        )

    finished = await job_repository.finish_job(
        job_id=second_claim.id,
        worker_id="worker-2",
        result={"owner": "worker-2"},
        now=NOW + timedelta(seconds=122),
    )
    assert finished.status == JobStatus.SUCCEEDED
    assert finished.result == {"owner": "worker-2"}


async def test_finish_requires_owner_stores_result_clears_lease_and_sanitizes_event(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    claimed = await enqueue_claimed_job(job_repository, key="finish")
    with pytest.raises(InvalidJobTransition):
        await job_repository.finish_job(
            job_id=claimed.id, worker_id="wrong-worker", result={}, now=NOW + timedelta(minutes=1)
        )

    finished = await job_repository.finish_job(
        job_id=claimed.id,
        worker_id="worker-1",
        result={"safe": "yes", "nested": {"token": "real-token"}},
        now=NOW + timedelta(minutes=1),
    )

    assert finished.status == JobStatus.SUCCEEDED
    assert finished.result == {"safe": "yes", "nested": {"token": "[REDACTED]"}}
    assert finished.progress == 100
    assert finished.finished_at == NOW + timedelta(minutes=1)
    assert finished.lease_owner is None
    assert finished.lease_expires_at is None
    assert finished.heartbeat_at is None
    succeeded_event = await db_session.scalar(
        select(WorkflowEvent).where(
            WorkflowEvent.workflow_job_id == claimed.id,
            WorkflowEvent.event_type == "job.succeeded",
        )
    )
    assert succeeded_event is not None
    assert succeeded_event.event_data["result"] == {"safe": "yes", "nested": {"token": "[REDACTED]"}}


async def test_state_and_event_roll_back_together(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        repository = JobRepository(session)
        claimed = await enqueue_claimed_job(repository, key="atomic-finish")
        await session.commit()
        job_id = claimed.id

    async with session_factory() as session:
        repository = JobRepository(session)
        await repository.finish_job(job_id=job_id, worker_id="worker-1", result={"ok": True}, now=NOW)
        await session.rollback()

    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        succeeded_events = await session.scalars(
            select(WorkflowEvent).where(
                WorkflowEvent.workflow_job_id == job_id,
                WorkflowEvent.event_type == "job.succeeded",
            )
        )
        assert job is not None
        assert job.status == JobStatus.RUNNING
        assert list(succeeded_events) == []


async def test_retryable_failure_with_attempts_remaining_requeues_at_explicit_time(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    claimed = await enqueue_claimed_job(job_repository, key="retryable", max_attempts=3)
    retry_at = NOW + timedelta(minutes=5)

    failed = await job_repository.fail_job(
        job_id=claimed.id,
        worker_id="worker-1",
        error_class=JobErrorClass.RETRYABLE,
        error_code="network_timeout",
        error_message="Temporary timeout",
        retry_at=retry_at,
        now=NOW + timedelta(minutes=1),
    )

    assert failed.status == JobStatus.QUEUED
    assert failed.scheduled_for == retry_at
    assert failed.error_class == JobErrorClass.RETRYABLE
    assert failed.lease_owner is None
    assert await event_types(db_session, claimed.id) == Counter(["job.enqueued", "job.claimed", "job.retry_scheduled"])


async def test_retryable_failure_without_retry_time_requeues_at_observed_time(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    claimed = await enqueue_claimed_job(
        job_repository,
        key="retryable-default-time",
        max_attempts=3,
    )
    observed_at = NOW + timedelta(minutes=1)

    failed = await job_repository.fail_job(
        job_id=claimed.id,
        worker_id="worker-1",
        error_class=JobErrorClass.RETRYABLE,
        error_code="network_timeout",
        error_message="Temporary timeout",
        now=observed_at,
    )

    assert failed.status == JobStatus.QUEUED
    assert failed.scheduled_for == observed_at
    assert failed.error_class == JobErrorClass.RETRYABLE
    assert await event_types(db_session, claimed.id) == Counter(["job.enqueued", "job.claimed", "job.retry_scheduled"])


async def test_exhausted_retryable_failure_becomes_failed(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    claimed = await enqueue_claimed_job(job_repository, key="retry-exhausted", max_attempts=1)

    failed = await job_repository.fail_job(
        job_id=claimed.id,
        worker_id="worker-1",
        error_class=JobErrorClass.RETRYABLE,
        error_code="network_timeout",
        error_message="Still unavailable",
        retry_at=NOW + timedelta(minutes=5),
        now=NOW + timedelta(minutes=1),
    )

    assert failed.status == JobStatus.FAILED
    assert failed.finished_at == NOW + timedelta(minutes=1)
    assert await event_types(db_session, claimed.id) == Counter(["job.enqueued", "job.claimed", "job.failed"])


async def test_permanent_failure_becomes_failed_even_with_attempts_remaining(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    claimed = await enqueue_claimed_job(job_repository, key="permanent", max_attempts=5)

    failed = await job_repository.fail_job(
        job_id=claimed.id,
        worker_id="worker-1",
        error_class=JobErrorClass.PERMANENT,
        error_code="invalid_configuration",
        error_message="Reference is invalid",
        now=NOW + timedelta(minutes=1),
    )

    assert failed.status == JobStatus.FAILED
    assert failed.error_class == JobErrorClass.PERMANENT
    assert await event_types(db_session, claimed.id) == Counter(["job.enqueued", "job.claimed", "job.failed"])


async def test_needs_review_failure_becomes_needs_review(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    claimed = await enqueue_claimed_job(job_repository, key="review")

    failed = await job_repository.fail_job(
        job_id=claimed.id,
        worker_id="worker-1",
        error_class=JobErrorClass.NEEDS_REVIEW,
        error_code="weak_evidence",
        error_message="Operator decision required",
        now=NOW + timedelta(minutes=1),
    )

    assert failed.status == JobStatus.NEEDS_REVIEW
    assert await event_types(db_session, claimed.id) == Counter(["job.enqueued", "job.claimed", "job.needs_review"])


@pytest.mark.parametrize("terminal_status", [JobStatus.FAILED, JobStatus.NEEDS_REVIEW])
async def test_retry_accepts_only_attention_states(
    job_repository: JobRepository,
    db_session: AsyncSession,
    terminal_status: JobStatus,
):
    queued = await job_repository.enqueue_job(
        job_type="retry", payload={}, idempotency_key=f"retry-{terminal_status}", origin=JobOrigin.AUTOMATION
    )
    queued.job.status = terminal_status
    queued.job.finished_at = NOW - timedelta(minutes=1)
    queued.job.error_class = JobErrorClass.PERMANENT
    queued.job.error_code = "old"
    queued.job.error_message = "old message"
    await db_session.flush()

    retried = await job_repository.retry_job(job_id=queued.job.id, now=NOW)

    assert retried.status == JobStatus.QUEUED
    assert retried.origin == JobOrigin.AUTOMATION
    assert retried.scheduled_for == NOW
    assert retried.finished_at is None
    assert retried.error_class is None
    assert retried.error_code is None
    assert retried.error_message is None
    assert await event_types(db_session, retried.id) == Counter(["job.enqueued", "job.retried"])


async def test_retry_rejects_non_attention_state(job_repository: JobRepository):
    queued = await job_repository.enqueue_job(
        job_type="retry", payload={}, idempotency_key="retry-invalid", origin=JobOrigin.AUTOMATION
    )

    with pytest.raises(InvalidJobTransition):
        await job_repository.retry_job(job_id=queued.job.id, now=NOW)


async def test_cancel_accepts_only_queued_and_emits_event(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    queued = await job_repository.enqueue_job(
        job_type="cancel", payload={}, idempotency_key="cancel-valid", origin=JobOrigin.MANUAL
    )

    cancelled = await job_repository.cancel_job(job_id=queued.job.id, now=NOW)

    assert cancelled.status == JobStatus.CANCELLED
    assert cancelled.finished_at == NOW
    assert await event_types(db_session, cancelled.id) == Counter(["job.enqueued", "job.cancelled"])
    with pytest.raises(InvalidJobTransition):
        await job_repository.cancel_job(job_id=cancelled.id, now=NOW)


async def test_expired_running_leases_requeue_clear_owner_and_emit_event(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    expired = await enqueue_claimed_job(job_repository, key="expired", now=NOW)
    live = await enqueue_claimed_job(job_repository, key="live", worker_id="worker-2", now=NOW + timedelta(minutes=1))

    recovered = await job_repository.requeue_expired_leases(now=NOW + timedelta(seconds=121))

    assert recovered == 1
    assert expired.status == JobStatus.QUEUED
    assert expired.lease_owner is None
    assert expired.lease_expires_at is None
    assert expired.heartbeat_at is None
    assert live.status == JobStatus.RUNNING
    assert await event_types(db_session, expired.id) == Counter(["job.enqueued", "job.claimed", "job.lease_expired"])


async def test_expired_running_lease_at_attempt_limit_becomes_truthful_terminal_failure(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    exhausted = await enqueue_claimed_job(
        job_repository,
        key="expired-attempt-limit",
        max_attempts=1,
        now=NOW,
    )
    observed_at = NOW + timedelta(seconds=121)

    recovered = await job_repository.requeue_expired_leases(now=observed_at)

    assert recovered == 1
    assert exhausted.status == JobStatus.FAILED
    assert exhausted.finished_at == observed_at
    assert exhausted.scheduled_for == NOW
    assert exhausted.attempt_count == exhausted.max_attempts == 1
    assert exhausted.error_class == JobErrorClass.RETRYABLE
    assert exhausted.error_code == "worker_lease_expired"
    assert exhausted.error_message == "Worker lease expired after the final configured attempt"
    assert exhausted.lease_owner is None
    assert exhausted.lease_expires_at is None
    assert exhausted.heartbeat_at is None
    assert await event_types(db_session, exhausted.id) == Counter(
        ["job.enqueued", "job.claimed", "job.lease_expired", "job.failed"]
    )
    failed_event = await db_session.scalar(
        select(WorkflowEvent).where(
            WorkflowEvent.workflow_job_id == exhausted.id,
            WorkflowEvent.event_type == "job.failed",
        )
    )
    assert failed_event is not None
    assert failed_event.event_data == {
        "error_class": "retryable",
        "error_code": "worker_lease_expired",
        "error_message": "Worker lease expired after the final configured attempt",
        "attempt_count": 1,
        "max_attempts": 1,
    }
    lease_event = await db_session.scalar(
        select(WorkflowEvent).where(
            WorkflowEvent.workflow_job_id == exhausted.id,
            WorkflowEvent.event_type == "job.lease_expired",
        )
    )
    assert lease_event is not None
    assert lease_event.event_data == {
        "lease_owner": "worker-1",
        "lease_expired_at": (NOW + timedelta(seconds=120)).isoformat(),
    }
    assert (
        await job_repository.claim_next_job(
            worker_id="automatic-worker",
            lease_seconds=120,
            now=observed_at,
        )
        is None
    )

    retried = await job_repository.retry_job(
        job_id=exhausted.id,
        now=observed_at + timedelta(seconds=1),
    )
    manually_claimed = await job_repository.claim_next_job(
        worker_id="operator-retry-worker",
        lease_seconds=120,
        now=observed_at + timedelta(seconds=1),
    )

    assert retried.origin == JobOrigin.AUTOMATION
    assert manually_claimed is not None and manually_claimed.id == exhausted.id
    assert manually_claimed.attempt_count == 2


async def test_retry_preserves_origin_so_pause_exempt_work_stays_claimable(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    exempt = await job_repository.enqueue_job(
        job_type="manual",
        payload={},
        idempotency_key="pause-exempt-retry",
        origin=JobOrigin.MANUAL,
        pause_sensitive=False,
        max_attempts=1,
        scheduled_for=NOW,
    )
    exempt.job.status = JobStatus.FAILED
    exempt.job.finished_at = NOW
    exempt.job.error_class = JobErrorClass.PERMANENT
    exempt.job.error_code = "boom"
    await db_session.flush()
    await db_session.execute(
        update(AutomationControl).where(AutomationControl.id == "global").values(global_pause=True)
    )

    retried = await job_repository.retry_job(job_id=exempt.job.id, now=NOW)

    assert retried.origin == JobOrigin.MANUAL
    assert retried.pause_sensitive is False
    claimed = await job_repository.claim_next_job(worker_id="worker-1", lease_seconds=120, now=NOW)
    assert claimed is not None and claimed.id == exempt.job.id


async def test_list_jobs_attention_filter_returns_only_attention_newest_first(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    failed = await job_repository.enqueue_job(
        job_type="attention", payload={}, idempotency_key="failed", origin=JobOrigin.AUTOMATION
    )
    review = await job_repository.enqueue_job(
        job_type="attention", payload={}, idempotency_key="review-list", origin=JobOrigin.AUTOMATION
    )
    await job_repository.enqueue_job(
        job_type="attention", payload={}, idempotency_key="queued-list", origin=JobOrigin.AUTOMATION
    )
    failed.job.status = JobStatus.FAILED
    failed.job.updated_at = NOW - timedelta(minutes=2)
    review.job.status = JobStatus.NEEDS_REVIEW
    review.job.updated_at = NOW - timedelta(minutes=1)
    await db_session.flush()

    attention = await job_repository.list_jobs(statuses=(JobStatus.FAILED, JobStatus.NEEDS_REVIEW))

    assert [job.id for job in attention] == [review.job.id, failed.job.id]


async def test_list_jobs_supports_type_error_and_limit_filters(
    job_repository: JobRepository,
    db_session: AsyncSession,
):
    matching = await job_repository.enqueue_job(
        job_type="publish", payload={}, idempotency_key="matching", origin=JobOrigin.AUTOMATION
    )
    other = await job_repository.enqueue_job(
        job_type="collect", payload={}, idempotency_key="other", origin=JobOrigin.AUTOMATION
    )
    matching.job.status = JobStatus.FAILED
    matching.job.error_class = JobErrorClass.PERMANENT
    other.job.status = JobStatus.FAILED
    other.job.error_class = JobErrorClass.RETRYABLE
    await db_session.flush()

    jobs = await job_repository.list_jobs(
        statuses=(JobStatus.FAILED,),
        job_type="publish",
        error_class=JobErrorClass.PERMANENT,
        limit=1,
    )

    assert [job.id for job in jobs] == [matching.job.id]
