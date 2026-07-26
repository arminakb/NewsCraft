from __future__ import annotations

import asyncio
import multiprocessing
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.automations.models import AutomationDispatch
from app.core.config import Settings
from app.core.faults import InjectedFault, ScriptedFaultInjector
from app.generation.handlers import build_canonical_generation_handler
from app.generation.models import GenerationAttempt, GenerationRun
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext, JobHandlerRegistry
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin, JobStatus
from app.jobs.worker import WorkerRunner
from app.operations.health import OperationalHealthService
from app.research.fake import FakeResearchBackend
from app.research.handlers import build_research_story_handler
from app.research.models import ResearchAttempt, ResearchRun
from app.stories.models import StoryRevision
from tests.postgres.test_telegram_process_handler import seed_dispatch

CLAIMED_AT = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)
CRASH_EXIT_CODE = 73
ROOT = Path(__file__).resolve().parents[3]


def _crash_after_claim(
    database_url: str,
    job_id: str,
    job_type: str = "fault.recovery",
    worker_id: str = "worker-before-crash",
    claimed_at_value: str | None = None,
    lease_seconds: int = 90,
) -> None:
    claimed_at = datetime.fromisoformat(claimed_at_value) if claimed_at_value else CLAIMED_AT

    async def run() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        registry = JobHandlerRegistry()

        async def handler(job, context):
            raise AssertionError("worker.after_claim must fire before the handler")

        registry.register(job_type, handler)
        runner = WorkerRunner(
            session_factory=factory,
            handler_registry=registry,
            worker_id=worker_id,
            capabilities=(),
            clock=lambda: claimed_at,
            lease_seconds=lease_seconds,
            heartbeat_seconds=30,
            fault_injector=ScriptedFaultInjector({"worker.after_claim": 1}),
        )
        await runner.run_once()

    try:
        asyncio.run(run())
    except InjectedFault as fault:
        if fault.point == "worker.after_claim" and fault.context["job_id"] == job_id:
            os._exit(CRASH_EXIT_CODE)
        os._exit(74)
    except BaseException:
        os._exit(75)
    os._exit(76)


async def test_before_heartbeat_fault_stops_before_handler_execution(
    release3_factory: async_sessionmaker,
) -> None:
    async with release3_factory() as session:
        enqueued = await JobRepository(session).enqueue_job(
            job_type="fault.before-heartbeat",
            payload={},
            idempotency_key="fault-recovery:before-heartbeat",
            origin=JobOrigin.AUTOMATION,
            scheduled_for=CLAIMED_AT,
        )
        job_id = enqueued.job.id
        await session.commit()

    handler_calls: list[UUID] = []

    async def handler(job, context):
        handler_calls.append(job.id)
        return {"unexpected": True}

    registry = JobHandlerRegistry()
    registry.register("fault.before-heartbeat", handler)
    injector = ScriptedFaultInjector({"worker.before_heartbeat": 1})
    worker = WorkerRunner(
        session_factory=release3_factory,
        handler_registry=registry,
        worker_id="worker-before-heartbeat",
        capabilities=(),
        clock=lambda: CLAIMED_AT,
        lease_seconds=90,
        heartbeat_seconds=30,
        fault_injector=injector,
    )

    with pytest.raises(InjectedFault, match="worker.before_heartbeat"):
        await worker.run_once()

    async with release3_factory() as session:
        claimed = await session.get(WorkflowJob, job_id)
        assert claimed is not None
        assert claimed.status == JobStatus.RUNNING
        assert claimed.attempt_count == 1

    assert handler_calls == []
    assert injector.hits[1].point == "worker.before_heartbeat"
    assert injector.hits[1].context["job_id"] == str(job_id)


async def test_worker_death_after_claim_requeues_one_lease_and_runs_handler_once(
    release3_factory: async_sessionmaker,
) -> None:
    async with release3_factory() as session:
        enqueued = await JobRepository(session).enqueue_job(
            job_type="fault.recovery",
            payload={"case": "worker-after-claim"},
            idempotency_key="fault-recovery:worker-after-claim",
            origin=JobOrigin.AUTOMATION,
            scheduled_for=CLAIMED_AT,
        )
        job_id = enqueued.job.id
        await session.commit()

    process = multiprocessing.get_context("spawn").Process(
        target=_crash_after_claim,
        args=(os.environ["TEST_DATABASE_URL"], str(job_id)),
    )
    process.start()
    process.join(timeout=20)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
        raise AssertionError("crash worker did not terminate")
    assert process.exitcode == CRASH_EXIT_CODE

    async with release3_factory() as session:
        claimed = await session.get(WorkflowJob, job_id)
        assert claimed is not None
        assert claimed.status == JobStatus.RUNNING
        assert claimed.attempt_count == 1
        assert claimed.lease_owner == "worker-before-crash"
        assert claimed.lease_expires_at == CLAIMED_AT + timedelta(seconds=90)

    recovered_at = CLAIMED_AT + timedelta(seconds=91)
    async with release3_factory() as session:
        assert await JobRepository(session).requeue_expired_leases(now=recovered_at) == 1
        await session.commit()

    handler_calls: list[UUID] = []

    async def healthy_handler(job, context):
        handler_calls.append(job.id)
        return {"recovered": True}

    healthy_registry = JobHandlerRegistry()
    healthy_registry.register("fault.recovery", healthy_handler)
    healthy_worker = WorkerRunner(
        session_factory=release3_factory,
        handler_registry=healthy_registry,
        worker_id="worker-after-crash",
        capabilities=(),
        clock=lambda: recovered_at,
        lease_seconds=90,
        heartbeat_seconds=30,
    )

    assert await healthy_worker.run_once() is True
    assert await healthy_worker.run_once() is False

    async with release3_factory() as session:
        recovered = await session.get(WorkflowJob, job_id)
        assert recovered is not None
        assert recovered.status == JobStatus.SUCCEEDED
        assert recovered.attempt_count == 2
        assert recovered.result == {"recovered": True}
        duplicate = await JobRepository(session).enqueue_job(
            job_type="fault.recovery",
            payload={"case": "worker-after-claim"},
            idempotency_key="fault-recovery:worker-after-claim",
            origin=JobOrigin.AUTOMATION,
            scheduled_for=recovered_at,
        )
        assert duplicate.created is False
        assert duplicate.job.id == job_id
        event_types = list(
            await session.scalars(
                select(WorkflowEvent.event_type)
                .where(WorkflowEvent.workflow_job_id == job_id)
                .order_by(WorkflowEvent.created_at, WorkflowEvent.id)
            )
        )

    assert handler_calls == [job_id]
    assert event_types == [
        "job.enqueued",
        "job.claimed",
        "job.lease_expired",
        "job.claimed",
        "job.heartbeat",
        "job.succeeded",
    ]


async def test_generation_provider_crash_retries_full_handler_without_duplicate_revision(
    app_harness,
    acceptance_profile_resolver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    researched = await app_harness.create_researched_story()
    requested = await app_harness.request_pack(
        researched.id,
        research_run_id=researched.research_run_id,
        platforms=["telegram"],
    )
    workflow_job_id = UUID(requested["job_id"])
    provider_calls = 0
    original_generate = acceptance_profile_resolver.provider.generate

    async def counted_generate(request):
        nonlocal provider_calls
        provider_calls += 1
        return await original_generate(request)

    monkeypatch.setattr(
        acceptance_profile_resolver.provider,
        "generate",
        counted_generate,
    )
    injector = ScriptedFaultInjector({"generation.after_provider_before_persist": 1})

    async with app_harness.session_factory() as session:
        job = await session.get(WorkflowJob, workflow_job_id)
        assert job is not None
        job.attempt_count = 1
        await session.commit()
        context = JobContext(
            session=session,
            providers=app_harness.worker.provider_registry,
        )

        with pytest.raises(InjectedFault) as crashed:
            await build_canonical_generation_handler(
                acceptance_profile_resolver,
                fault_injector=injector,
            )(job, context)

        assert crashed.value.point == "generation.after_provider_before_persist"
        generated_before_retry = list(
            await session.scalars(
                select(StoryRevision).where(
                    StoryRevision.story_id == researched.id,
                    StoryRevision.created_by == "generation",
                )
            )
        )
        assert generated_before_retry == []

        job.attempt_count = 2
        await session.commit()
        healthy = build_canonical_generation_handler(acceptance_profile_resolver)
        recovered = await healthy(job, context)
        await session.commit()

        job.attempt_count = 3
        await session.commit()
        replayed = await healthy(job, context)
        await session.commit()

        runs = list(await session.scalars(select(GenerationRun)))
        attempts = list(await session.scalars(select(GenerationAttempt).order_by(GenerationAttempt.attempt_number)))
        generated = list(
            await session.scalars(
                select(StoryRevision).where(
                    StoryRevision.story_id == researched.id,
                    StoryRevision.created_by == "generation",
                )
            )
        )

    assert provider_calls == 2
    assert len(runs) == 1 and runs[0].status == "succeeded"
    assert [attempt.status for attempt in attempts] == ["failed", "succeeded"]
    assert len(generated) == 1
    assert recovered["story_revision_id"] == replayed["story_revision_id"] == str(generated[0].id)
    assert recovered["continuation_job_id"] == replayed["continuation_job_id"]
    assert replayed["idempotent"] is True


async def test_final_generation_crash_exhausts_lease_and_closes_provider_attempt(
    app_harness,
    acceptance_profile_resolver,
) -> None:
    researched = await app_harness.create_researched_story()
    requested = await app_harness.request_pack(
        researched.id,
        research_run_id=researched.research_run_id,
        platforms=["telegram"],
    )
    workflow_job_id = UUID(requested["job_id"])
    injector = ScriptedFaultInjector({"generation.after_provider_before_persist": 1})

    async with app_harness.session_factory() as session:
        job = await session.get(WorkflowJob, workflow_job_id)
        assert job is not None
        job.status = JobStatus.RUNNING
        job.attempt_count = 1
        job.max_attempts = 1
        job.lease_owner = "generation-worker-final-attempt"
        job.lease_expires_at = CLAIMED_AT + timedelta(seconds=90)
        job.heartbeat_at = CLAIMED_AT
        await session.commit()
        context = JobContext(
            session=session,
            providers=app_harness.worker.provider_registry,
        )

        with pytest.raises(InjectedFault, match="generation.after_provider_before_persist"):
            await build_canonical_generation_handler(
                acceptance_profile_resolver,
                fault_injector=injector,
            )(job, context)

        assert await JobRepository(session).requeue_expired_leases(now=CLAIMED_AT + timedelta(seconds=91)) == 1
        await session.commit()

        terminal_job = await session.get(WorkflowJob, workflow_job_id)
        runs = list(
            await session.scalars(
                select(GenerationRun).where(
                    GenerationRun.request_payload["execution"]["workflow_job_id"].as_string() == str(workflow_job_id)
                )
            )
        )
        attempts = list(
            await session.scalars(
                select(GenerationAttempt).where(GenerationAttempt.generation_run_id.in_([run.id for run in runs]))
            )
        )
        generated = list(
            await session.scalars(
                select(StoryRevision).where(
                    StoryRevision.story_id == researched.id,
                    StoryRevision.created_by == "generation",
                )
            )
        )

    assert terminal_job is not None and terminal_job.status == JobStatus.FAILED
    assert terminal_job.error_code == "worker_lease_expired"
    assert len(runs) == 1 and runs[0].status == "failed"
    assert runs[0].error_code == "worker_lease_expired"
    assert len(attempts) == 1 and attempts[0].status == "failed"
    assert attempts[0].error_code == "worker_lease_expired"
    assert attempts[0].finished_at == CLAIMED_AT + timedelta(seconds=91)
    assert generated == []


async def test_final_research_crash_exhausts_lease_and_closes_provider_attempt(
    app_harness,
) -> None:
    intake = await app_harness.post_json(
        "/stories/manual",
        {
            "kind": "text",
            "title": "Research lease exhaustion",
            "text": "Source-backed research recovery context. " * 40,
            "source_label": "Recovery operator",
            "source_url": None,
        },
        expected_status=202,
    )
    await app_harness.run_until_idle()
    story = await app_harness.story_for_job(intake["job_id"])
    requested = await app_harness.post_json(
        f"/stories/{story.id}/research-runs",
        {
            "mode": "manual",
            "depth": "standard",
            "provider_profile_id": str(app_harness.fake_provider_profile_id),
            "query_hint": "Verify terminal recovery",
        },
        expected_status=202,
    )
    workflow_job_id = UUID(requested["job_id"])
    research_run_id = UUID(requested["run_id"])
    backend = FakeResearchBackend.from_fixture(ROOT / "backend/tests/fixtures/research_brief.json")
    injector = ScriptedFaultInjector({"research.after_provider_before_persist": 1})

    async with app_harness.session_factory() as session:
        job = await session.get(WorkflowJob, workflow_job_id)
        assert job is not None
        job.status = JobStatus.RUNNING
        job.attempt_count = 1
        job.max_attempts = 1
        job.lease_owner = "research-worker-final-attempt"
        job.lease_expires_at = CLAIMED_AT + timedelta(seconds=90)
        job.heartbeat_at = CLAIMED_AT
        await session.commit()

        with pytest.raises(InjectedFault, match="research.after_provider_before_persist"):
            await build_research_story_handler(
                lambda _profile: backend,
                fault_injector=injector,
            )(
                job,
                JobContext(session=session, providers=app_harness.worker.provider_registry),
            )

        assert await JobRepository(session).requeue_expired_leases(now=CLAIMED_AT + timedelta(seconds=91)) == 1
        await session.commit()

        terminal_job = await session.get(WorkflowJob, workflow_job_id)
        run = await session.get(ResearchRun, research_run_id)
        attempts = list(
            await session.scalars(select(ResearchAttempt).where(ResearchAttempt.research_run_id == research_run_id))
        )

    assert terminal_job is not None and terminal_job.status == JobStatus.FAILED
    assert terminal_job.error_code == "worker_lease_expired"
    assert run is not None and run.status == "failed"
    assert run.finished_at == CLAIMED_AT + timedelta(seconds=91)
    assert len(attempts) == 1 and attempts[0].status == "failed"
    assert attempts[0].error_code == "worker_lease_expired"
    assert attempts[0].finished_at == CLAIMED_AT + timedelta(seconds=91)


async def test_final_route_generation_crash_closes_active_run_attempt_and_dispatch(
    release3_factory,
) -> None:
    async with release3_factory() as session:
        async with session.begin():
            dispatch, job, shared = await seed_dispatch(
                session,
                route_name="RouteGenerationLeaseExhaustion",
            )
            job.max_attempts = 1
            job.lease_owner = "route-generation-worker-final-attempt"
            job.lease_expires_at = CLAIMED_AT + timedelta(seconds=90)
            job.heartbeat_at = CLAIMED_AT
            run = GenerationRun(
                story_revision_id=dispatch.story_revision_id,
                provider_profile_id=shared["provider"].id,
                prompt_template_version_id=shared["prompt"].id,
                requested_model="fake-route-model",
                status="running",
                input_hash="f" * 64,
                request_payload={
                    "execution": {
                        "active_workflow_job_id": str(job.id),
                        "active_workflow_attempt": 1,
                    }
                },
                output_payload={},
                started_at=CLAIMED_AT,
            )
            session.add(run)
            await session.flush()
            attempt = GenerationAttempt(
                generation_run_id=run.id,
                attempt_number=1,
                provider="fake",
                requested_model="fake-route-model",
                resolved_model="fake-route-model",
                prompt_snapshot={},
                response_payload={},
                usage={},
                validation_errors=[],
                status="running",
                started_at=CLAIMED_AT,
            )
            session.add(attempt)
            await session.flush()
            dispatch.generation_run_id = run.id
            dispatch.status = "generating"
            job_id = job.id
            dispatch_id = dispatch.id
            run_id = run.id
            attempt_id = attempt.id

    recovered_at = CLAIMED_AT + timedelta(seconds=91)
    async with release3_factory() as session:
        assert await JobRepository(session).requeue_expired_leases(now=recovered_at) == 1
        await session.commit()

    async with release3_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        run = await session.get(GenerationRun, run_id)
        attempt = await session.get(GenerationAttempt, attempt_id)

    assert job is not None and job.status == JobStatus.FAILED
    assert dispatch is not None and dispatch.status == "failed"
    assert dispatch.error_code == "worker_lease_expired"
    assert run is not None and run.status == "failed"
    assert run.error_code == "worker_lease_expired"
    assert attempt is not None and attempt.status == "failed"
    assert attempt.error_code == "worker_lease_expired"
    assert attempt.finished_at == recovered_at


@pytest.mark.parametrize("dispatch_status", ["captured", "retryable"])
async def test_final_route_process_claim_before_handler_terminalizes_dispatch(
    release3_factory,
    dispatch_status: str,
) -> None:
    async with release3_factory() as session:
        async with session.begin():
            dispatch, job, _ = await seed_dispatch(
                session,
                route_name=f"RoutePreHandlerLeaseExhaustion-{dispatch_status}",
            )
            dispatch.status = dispatch_status
            job.max_attempts = 1
            job.lease_owner = "route-worker-before-handler-final-attempt"
            job.lease_expires_at = CLAIMED_AT + timedelta(seconds=90)
            job.heartbeat_at = CLAIMED_AT
            job_id = job.id
            dispatch_id = dispatch.id

    recovered_at = CLAIMED_AT + timedelta(seconds=91)
    async with release3_factory() as session:
        assert await JobRepository(session).requeue_expired_leases(now=recovered_at) == 1
        await session.commit()

    async with release3_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        dispatch = await session.get(AutomationDispatch, dispatch_id)

    assert job is not None and job.status == JobStatus.FAILED
    assert job.error_code == "worker_lease_expired"
    assert dispatch is not None and dispatch.status == "failed"
    assert dispatch.error_code == "worker_lease_expired"
    assert dispatch.error_message == "Worker lease expired after the final configured attempt"
    assert dispatch.generation_run_id is None


async def test_final_route_research_crash_marks_subscribed_dispatch_for_review(
    release3_factory,
) -> None:
    async with release3_factory() as session:
        async with session.begin():
            dispatch, _, shared = await seed_dispatch(
                session,
                route_name="RouteResearchLeaseExhaustion",
            )
            run = ResearchRun(
                story_id=shared["story"].id,
                requested_mode="auto_if_incomplete",
                provider_profile_id=shared["provider"].id,
                status="queued",
                query_budget=4,
                page_budget=8,
                time_budget_seconds=120,
            )
            session.add(run)
            await session.flush()
            research_job = WorkflowJob(
                job_type="research_story",
                payload={
                    "run_id": str(run.id),
                    "continuations": [{
                        "job_type": "telegram.route.process",
                        "payload": {
                            "dispatch_id": str(dispatch.id),
                            "force_review": False,
                        },
                        "idempotency_prefix": (f"telegram-route-process-after-research:{dispatch.id}"),
                        "subscriber_id": f"telegram-dispatch:{dispatch.id}",
                        "expected_route_id": str(dispatch.route_id),
                        "expected_story_id": str(shared["story"].id),
                        "expected_story_revision_id": str(dispatch.story_revision_id),
                        "expected_provider_profile_id": str(shared["provider"].id),
                        "expected_research_mode": "auto_if_incomplete",
                    }],
                },
                idempotency_key=f"research-route-final:{dispatch.id}",
                origin=JobOrigin.AUTOMATION,
                status=JobStatus.RUNNING,
                attempt_count=1,
                max_attempts=1,
                lease_owner="route-research-worker-final-attempt",
                lease_expires_at=CLAIMED_AT + timedelta(seconds=90),
                heartbeat_at=CLAIMED_AT,
            )
            session.add(research_job)
            await session.flush()
            dispatch.status = "researching"
            job_id = research_job.id
            dispatch_id = dispatch.id
            run_id = run.id

    recovered_at = CLAIMED_AT + timedelta(seconds=91)
    async with release3_factory() as session:
        assert await JobRepository(session).requeue_expired_leases(now=recovered_at) == 1
        await session.commit()

    async with release3_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        dispatch = await session.get(AutomationDispatch, dispatch_id)
        run = await session.get(ResearchRun, run_id)
        attempts = list(await session.scalars(select(ResearchAttempt).where(ResearchAttempt.research_run_id == run_id)))

    assert job is not None and job.status == JobStatus.FAILED
    assert dispatch is not None and dispatch.status == "needs_review"
    assert dispatch.error_code == "worker_lease_expired"
    assert run is not None and run.status == "failed"
    assert run.finished_at == recovered_at
    assert attempts == []


@pytest.mark.asyncio
async def test_repeated_process_killing_poison_job_exhausts_bounded_attempts(
    release3_factory,
    tmp_path,
):
    async with release3_factory() as session:
        queued = await JobRepository(session).enqueue_job(
            job_type="fault.poison",
            payload={},
            idempotency_key="phase3:poison-process-kill",
            origin=JobOrigin.MANUAL,
            max_attempts=3,
            scheduled_for=CLAIMED_AT,
        )
        job_id = queued.job.id
        await session.commit()

    for attempt in range(1, 4):
        claimed_at = CLAIMED_AT + timedelta(seconds=(attempt - 1) * 31)
        worker_id = f"poison-worker-{attempt}"
        process = multiprocessing.get_context("spawn").Process(
            target=_crash_after_claim,
            args=(
                os.environ["TEST_DATABASE_URL"],
                str(job_id),
                "fault.poison",
                worker_id,
                claimed_at.isoformat(),
                30,
            ),
        )
        process.start()
        process.join(timeout=20)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
            raise AssertionError(f"poison attempt {attempt} did not terminate")
        assert process.exitcode == CRASH_EXIT_CODE

        async with release3_factory() as session:
            claimed = await session.get(WorkflowJob, job_id)
            assert claimed is not None
            assert claimed.status == JobStatus.RUNNING
            assert claimed.lease_owner == worker_id
            assert claimed.attempt_count == attempt

        # Each process dies without a terminal transition. Lease recovery is
        # the only retry path and must become terminal after the configured bound.
        async with release3_factory() as session:
            assert await JobRepository(session).requeue_expired_leases(now=claimed_at + timedelta(seconds=31)) == 1
            await session.commit()

    async with release3_factory() as session:
        terminal = await session.get(WorkflowJob, job_id)
        replay = await JobRepository(session).claim_next_job(
            worker_id="poison-worker-4",
            lease_seconds=30,
            allowed_job_types=("fault.poison",),
            now=CLAIMED_AT + timedelta(seconds=94),
        )
        events = list(
            await session.scalars(
                select(WorkflowEvent.event_type)
                .where(WorkflowEvent.workflow_job_id == job_id)
                .order_by(WorkflowEvent.created_at)
            )
        )

    assert terminal is not None
    assert terminal.status == JobStatus.FAILED
    assert terminal.attempt_count == terminal.max_attempts == 3
    assert terminal.error_code == "worker_lease_expired"
    assert terminal.lease_owner is None
    assert replay is None
    assert events.count("job.lease_expired") == 3
    assert events.count("job.failed") == 1

    (tmp_path / "media").mkdir()
    (tmp_path / "exports").mkdir()
    async with release3_factory() as session:
        operational = await OperationalHealthService(
            session,
            config=Settings(
                media_root=str(tmp_path / "media"),
                export_root=str(tmp_path / "exports"),
                expected_runtime_component_ids="",
                readiness_required_capabilities="",
                recovery_observation_window_seconds=604_800,
            ),
        ).snapshot()

    recovery = next(item for item in operational.recoveries if item.job_id == str(job_id))
    assert recovery.code == "poison_job_terminal"
    assert recovery.recovery_count == 3
    assert recovery.attempt_count == recovery.max_attempts == 3
    assert any(alert.code == "poison_job_terminal" and alert.scope == f"job:{job_id}" for alert in operational.alerts)
    assert operational.metrics["poison_jobs_terminal"] == 1
