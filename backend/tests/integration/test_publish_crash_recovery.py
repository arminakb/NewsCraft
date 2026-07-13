from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.automations.models import AutomationRoute
from app.automations.telegram.handlers import sha256_canonical
from app.core.faults import InjectedFault, ScriptedFaultInjector
from app.db.models import SourceItem
from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
from app.generation.telegram_schema import TelegramEvidenceCitation, TelegramVariantContent
from app.jobs.errors import NeedsReviewJobError
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowJob
from app.jobs.registry import JobHandlerRegistry
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin, JobStatus
from app.jobs.worker import WorkerRunner
from app.publishing.models import Publication, PublishAttempt, PublishJob, PublishOperationReceipt
from app.publishing.telegram.contracts import TelegramOperationResult
from app.publishing.telegram.service import get_reconciliation_case, publish_telegram
from app.stories.models import StoryEvidenceSnapshot
from tests.postgres.test_telegram_process_handler import seed_dispatch

CLAIMED_AT = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)


class CountingTelegramClient:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, operation, token):
        assert token == "destination-token"
        self.calls += 1
        return TelegramOperationResult(
            remote_message_ids=(9200 + self.calls,),
            response_metadata={"ok": True, "result_count": 1},
        )


class SimulatedHardDeath(BaseException):
    pass


class HardDeathTelegramClient:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, operation, token):
        assert token == "destination-token"
        self.calls += 1
        raise SimulatedHardDeath


async def resolve_destination_secret(secret_ref: str) -> str:
    assert secret_ref == "TELEGRAM_DESTINATION_TOKEN"
    return "destination-token"


async def _seed_publish_job(session_factory, *, route_name: str) -> UUID:
    async with session_factory() as session:
        async with session.begin():
            session.add(AutomationControl(id="global", global_pause=False, dry_run=False))
            dispatch, _, shared = await seed_dispatch(
                session,
                route_name=route_name,
                publishing_policy="auto_publish",
                allow_auto=True,
            )
            route = await session.get(AutomationRoute, dispatch.route_id)
            source_item = await session.get(SourceItem, dispatch.source_item_id)
            assert route is not None and source_item is not None
            snapshot = await session.scalar(
                select(StoryEvidenceSnapshot).where(
                    StoryEvidenceSnapshot.story_id == shared["story"].id,
                    StoryEvidenceSnapshot.content_item_id == source_item.content_item_id,
                )
            )
            assert snapshot is not None
            pack = ContentPack(
                story_revision_id=dispatch.story_revision_id,
                brand_profile_id=route.brand_profile_id,
                status="ready",
            )
            session.add(pack)
            await session.flush()
            variant = PlatformVariant(content_pack_id=pack.id, platform="telegram")
            session.add(variant)
            await session.flush()
            content = TelegramVariantContent(
                body=f"Publish {route_name}",
                source_item_id=dispatch.source_item_id,
                source_url=source_item.source_url,
                media_policy="omit",
                media_asset_ids=[],
                direction="rtl",
                dry_run=False,
            ).model_dump(mode="json")
            evidence_map = [
                TelegramEvidenceCitation(
                    evidence_snapshot_id=snapshot.id,
                    evidence_key=snapshot.evidence_key,
                    source_url=snapshot.source_url,
                    locator=f"chars:0-{len(snapshot.content_text)}",
                    excerpt_sha256=snapshot.content_sha256,
                ).model_dump(mode="json")
            ]
            revision = PlatformVariantRevision(
                platform_variant_id=variant.id,
                revision_number=1,
                content=content,
                content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
                evidence_map=evidence_map,
                validation_results=[{"gate": "telegram_schema", "ok": True}],
                approval_state="approved",
                approved_at=datetime.now(UTC),
                created_by="test",
            )
            session.add(revision)
            await session.flush()
            workflow_job = WorkflowJob(
                job_type="telegram.publish",
                payload={},
                idempotency_key=f"publish-workflow:{route_name}",
                origin=JobOrigin.AUTOMATION,
            )
            session.add(workflow_job)
            await session.flush()
            publish_job = PublishJob(
                workflow_job_id=workflow_job.id,
                destination_id=route.destination_id,
                platform_variant_revision_id=revision.id,
                status="queued",
                idempotency_key=f"publish-intent:{route_name}",
                payload_hash=revision.content_hash,
            )
            session.add(publish_job)
            await session.flush()
            workflow_job.payload = {"publish_job_id": str(publish_job.id)}
            dispatch.variant_revision_id = revision.id
            dispatch.publish_job_id = publish_job.id
            dispatch.status = "approved"
            publish_job_id = publish_job.id
    return publish_job_id


@pytest.mark.asyncio
async def test_crash_before_remote_send_resets_safe_claim_and_retries_once(
    release3_factory,
):
    publish_job_id = await _seed_publish_job(
        release3_factory,
        route_name="PreSendCrash",
    )
    client = CountingTelegramClient()
    injector = ScriptedFaultInjector({"telegram.before_send": 1})

    async def crash_before_send(job, context):
        return await publish_telegram(
            context.session,
            publish_job_id=publish_job_id,
            client=client,
            secret_resolver=resolve_destination_secret,
            now=lambda: CLAIMED_AT,
            fault_injector=injector,
        )

    crashing_registry = JobHandlerRegistry()
    crashing_registry.register("telegram.publish", crash_before_send)
    crashing_worker = WorkerRunner(
        session_factory=release3_factory,
        handler_registry=crashing_registry,
        worker_id="telegram-worker-before-safe-crash",
        capabilities=(),
        clock=lambda: CLAIMED_AT,
        lease_seconds=90,
        heartbeat_seconds=30,
    )

    with pytest.raises(InjectedFault) as crashed:
        await crashing_worker.run_once()

    assert crashed.value.point == "telegram.before_send"
    assert [hit.point for hit in injector.hits] == ["telegram.before_send"]
    assert client.calls == 0

    async with release3_factory() as session:
        receipt = await session.scalar(
            select(PublishOperationReceipt).where(PublishOperationReceipt.publish_job_id == publish_job_id)
        )
        publish_job = await session.get(PublishJob, publish_job_id)
        workflow_job = await session.get(WorkflowJob, publish_job.workflow_job_id)
        attempts = list(
            await session.scalars(
                select(PublishAttempt)
                .where(PublishAttempt.publish_job_id == publish_job_id)
                .order_by(PublishAttempt.attempt_number)
            )
        )

    assert receipt is not None and receipt.status == "pending"
    assert publish_job is not None and publish_job.status == "queued"
    assert workflow_job is not None and workflow_job.status == JobStatus.RUNNING
    assert len(attempts) == 1 and attempts[0].status == "failed"
    assert attempts[0].error_code == "telegram_connect_failed"

    recovered_at = CLAIMED_AT + timedelta(seconds=91)
    async with release3_factory() as session:
        assert await JobRepository(session).requeue_expired_leases(now=recovered_at) == 1
        await session.commit()

    async def publish_once(job, context):
        return await publish_telegram(
            context.session,
            publish_job_id=publish_job_id,
            client=client,
            secret_resolver=resolve_destination_secret,
            now=lambda: recovered_at,
        )

    healthy_registry = JobHandlerRegistry()
    healthy_registry.register("telegram.publish", publish_once)
    healthy_worker = WorkerRunner(
        session_factory=release3_factory,
        handler_registry=healthy_registry,
        worker_id="telegram-worker-after-safe-crash",
        capabilities=(),
        clock=lambda: recovered_at,
        lease_seconds=90,
        heartbeat_seconds=30,
    )

    assert await healthy_worker.run_once() is True
    assert client.calls == 1

    async with release3_factory() as session:
        receipt = await session.scalar(
            select(PublishOperationReceipt).where(PublishOperationReceipt.publish_job_id == publish_job_id)
        )
        publish_job = await session.get(PublishJob, publish_job_id)
        workflow_job = await session.get(WorkflowJob, workflow_job.id)
        attempts = list(
            await session.scalars(
                select(PublishAttempt)
                .where(PublishAttempt.publish_job_id == publish_job_id)
                .order_by(PublishAttempt.attempt_number)
            )
        )
        publications = list(
            await session.scalars(select(Publication).where(Publication.publish_job_id == publish_job_id))
        )

    assert receipt is not None and receipt.status == "succeeded"
    assert receipt.attempt_count == 2
    assert publish_job is not None and publish_job.status == "succeeded"
    assert workflow_job is not None and workflow_job.status == JobStatus.SUCCEEDED
    assert [attempt.status for attempt in attempts] == ["failed", "succeeded"]
    assert len(publications) == 1 and publications[0].remote_message_ids == [9201]


@pytest.mark.asyncio
async def test_stale_dispatch_claim_enters_reconciliation_and_closes_running_attempt(
    release3_factory,
):
    publish_job_id = await _seed_publish_job(
        release3_factory,
        route_name="HardDeathDispatch",
    )
    crashing_client = HardDeathTelegramClient()

    async with release3_factory() as session:
        with pytest.raises(SimulatedHardDeath):
            await publish_telegram(
                session,
                publish_job_id=publish_job_id,
                client=crashing_client,
                secret_resolver=resolve_destination_secret,
                now=lambda: CLAIMED_AT,
            )

    assert crashing_client.calls == 1
    async with release3_factory() as session:
        receipt = await session.scalar(
            select(PublishOperationReceipt).where(PublishOperationReceipt.publish_job_id == publish_job_id)
        )
        attempts = list(
            await session.scalars(select(PublishAttempt).where(PublishAttempt.publish_job_id == publish_job_id))
        )
    assert receipt is not None and receipt.status == "dispatching"
    assert [attempt.status for attempt in attempts] == ["running"]

    detected_at = CLAIMED_AT + timedelta(minutes=5, seconds=1)
    healthy_client = CountingTelegramClient()
    async with release3_factory() as session:
        with pytest.raises(NeedsReviewJobError) as blocked:
            await publish_telegram(
                session,
                publish_job_id=publish_job_id,
                client=healthy_client,
                secret_resolver=resolve_destination_secret,
                now=lambda: detected_at,
            )

    assert blocked.value.code == "telegram_publish_reconciliation_required"
    assert healthy_client.calls == 0
    async with release3_factory() as session:
        receipt = await session.scalar(
            select(PublishOperationReceipt).where(PublishOperationReceipt.publish_job_id == publish_job_id)
        )
        publish_job = await session.get(PublishJob, publish_job_id)
        attempts = list(
            await session.scalars(select(PublishAttempt).where(PublishAttempt.publish_job_id == publish_job_id))
        )
    assert receipt is not None and receipt.status == "ambiguous"
    assert publish_job is not None and publish_job.status == "reconciliation_required"
    assert [attempt.status for attempt in attempts] == ["needs_review"]
    assert attempts[0].error_class == "needs_review"
    assert attempts[0].error_code == "telegram_publish_ambiguous"
    assert attempts[0].finished_at == detected_at


@pytest.mark.asyncio
@pytest.mark.parametrize("max_attempts", [1, 3])
async def test_expired_worker_lease_with_dispatching_receipt_requires_reconciliation(
    release3_factory,
    max_attempts: int,
):
    publish_job_id = await _seed_publish_job(
        release3_factory,
        route_name="FinalLeaseDispatch",
    )
    async with release3_factory() as session:
        publish_job = await session.get(PublishJob, publish_job_id)
        assert publish_job is not None
        workflow_job = await session.get(WorkflowJob, publish_job.workflow_job_id)
        assert workflow_job is not None
        workflow_job.status = JobStatus.RUNNING
        workflow_job.attempt_count = 1
        workflow_job.max_attempts = max_attempts
        workflow_job.lease_owner = "telegram-worker-final-attempt"
        workflow_job.lease_expires_at = CLAIMED_AT + timedelta(seconds=90)
        workflow_job.heartbeat_at = CLAIMED_AT
        workflow_job_id = workflow_job.id
        await session.commit()

    crashing_client = HardDeathTelegramClient()
    async with release3_factory() as session:
        with pytest.raises(SimulatedHardDeath):
            await publish_telegram(
                session,
                publish_job_id=publish_job_id,
                client=crashing_client,
                secret_resolver=resolve_destination_secret,
                now=lambda: CLAIMED_AT,
            )

    recovered_at = CLAIMED_AT + timedelta(seconds=91)
    async with release3_factory() as session:
        assert await JobRepository(session).requeue_expired_leases(now=recovered_at) == 1
        await session.commit()

    async with release3_factory() as session:
        workflow_job = await session.get(WorkflowJob, workflow_job_id)
        publish_job = await session.get(PublishJob, publish_job_id)
        receipt = await session.scalar(
            select(PublishOperationReceipt).where(PublishOperationReceipt.publish_job_id == publish_job_id)
        )
        attempts = list(
            await session.scalars(select(PublishAttempt).where(PublishAttempt.publish_job_id == publish_job_id))
        )
        workflow_events = list(
            await session.scalars(
                select(WorkflowEvent.event_type)
                .where(WorkflowEvent.workflow_job_id == workflow_job_id)
                .order_by(WorkflowEvent.created_at, WorkflowEvent.id)
            )
        )

    assert workflow_job is not None and workflow_job.status == JobStatus.NEEDS_REVIEW
    assert workflow_job.error_class == "needs_review"
    assert workflow_job.error_code == "telegram_publish_ambiguous"
    assert publish_job is not None and publish_job.status == "reconciliation_required"
    assert receipt is not None and receipt.status == "ambiguous"
    assert receipt.ambiguous_at == recovered_at
    assert [attempt.status for attempt in attempts] == ["needs_review"]
    assert attempts[0].error_code == "telegram_publish_ambiguous"
    assert attempts[0].finished_at == recovered_at
    assert sorted(workflow_events) == ["job.lease_expired", "job.needs_review"]


@pytest.mark.asyncio
async def test_final_worker_lease_moves_scheduled_publish_job_to_attention(
    release3_factory,
):
    publish_job_id = await _seed_publish_job(
        release3_factory,
        route_name="FinalScheduledLease",
    )
    async with release3_factory() as session:
        publish_job = await session.get(PublishJob, publish_job_id)
        assert publish_job is not None
        publish_job.status = "scheduled"
        publish_job.scheduled_for = CLAIMED_AT
        workflow_job = await session.get(WorkflowJob, publish_job.workflow_job_id)
        assert workflow_job is not None
        workflow_job.status = JobStatus.RUNNING
        workflow_job.attempt_count = 1
        workflow_job.max_attempts = 1
        workflow_job.lease_owner = "telegram-scheduled-worker-final-attempt"
        workflow_job.lease_expires_at = CLAIMED_AT + timedelta(seconds=90)
        workflow_job.heartbeat_at = CLAIMED_AT
        workflow_job_id = workflow_job.id
        await session.commit()

    recovered_at = CLAIMED_AT + timedelta(seconds=91)
    async with release3_factory() as session:
        assert await JobRepository(session).requeue_expired_leases(now=recovered_at) == 1
        await session.commit()

    async with release3_factory() as session:
        workflow_job = await session.get(WorkflowJob, workflow_job_id)
        publish_job = await session.get(PublishJob, publish_job_id)
        attempts = list(
            await session.scalars(select(PublishAttempt).where(PublishAttempt.publish_job_id == publish_job_id))
        )

    assert workflow_job is not None and workflow_job.status == JobStatus.FAILED
    assert publish_job is not None and publish_job.status == "attention"
    assert attempts == []


@pytest.mark.asyncio
async def test_crash_after_remote_send_requires_reconciliation_and_replay_does_not_duplicate(
    release3_factory,
):
    publish_job_id = await _seed_publish_job(
        release3_factory,
        route_name="PostSendCrash",
    )
    client = CountingTelegramClient()
    injector = ScriptedFaultInjector({"telegram.after_send_before_receipt": 1})

    async def crash_after_send(job, context):
        return await publish_telegram(
            context.session,
            publish_job_id=publish_job_id,
            client=client,
            secret_resolver=resolve_destination_secret,
            fault_injector=injector,
        )

    crashing_registry = JobHandlerRegistry()
    crashing_registry.register("telegram.publish", crash_after_send)
    crashing_worker = WorkerRunner(
        session_factory=release3_factory,
        handler_registry=crashing_registry,
        worker_id="telegram-worker-before-crash",
        capabilities=(),
        clock=lambda: CLAIMED_AT,
        lease_seconds=90,
        heartbeat_seconds=30,
    )

    with pytest.raises(InjectedFault) as crashed:
        await crashing_worker.run_once()

    assert crashed.value.point == "telegram.after_send_before_receipt"
    assert [hit.point for hit in injector.hits] == [
        "telegram.before_send",
        "telegram.after_send_before_receipt",
    ]
    assert client.calls == 1

    async with release3_factory() as session:
        receipt = await session.scalar(
            select(PublishOperationReceipt).where(PublishOperationReceipt.publish_job_id == publish_job_id)
        )
        publish_job = await session.get(PublishJob, publish_job_id)
        attempt = await session.scalar(select(PublishAttempt).where(PublishAttempt.publish_job_id == publish_job_id))
        publication = await session.scalar(select(Publication).where(Publication.publish_job_id == publish_job_id))
        reconciliation = await get_reconciliation_case(session, publish_job_id)
        workflow_job = await session.get(WorkflowJob, publish_job.workflow_job_id)

    assert receipt is not None and receipt.status == "ambiguous"
    assert receipt.attempt_count == 1
    assert receipt.remote_message_ids == []
    assert publish_job is not None and publish_job.status == "reconciliation_required"
    assert attempt is not None and attempt.status == "needs_review"
    assert publication is None
    assert reconciliation is not None and reconciliation.status == "pending"
    assert reconciliation.ambiguous_operation_key == receipt.operation_key
    assert workflow_job is not None and workflow_job.status == JobStatus.RUNNING
    assert workflow_job.lease_owner == "telegram-worker-before-crash"
    assert workflow_job.lease_expires_at == CLAIMED_AT + timedelta(seconds=90)

    recovered_at = CLAIMED_AT + timedelta(seconds=91)
    async with release3_factory() as session:
        assert await JobRepository(session).requeue_expired_leases(now=recovered_at) == 1
        await session.commit()

    async def reconcile_without_resend(job, context):
        return await publish_telegram(
            context.session,
            publish_job_id=publish_job_id,
            client=client,
            secret_resolver=resolve_destination_secret,
        )

    healthy_registry = JobHandlerRegistry()
    healthy_registry.register("telegram.publish", reconcile_without_resend)
    healthy_worker = WorkerRunner(
        session_factory=release3_factory,
        handler_registry=healthy_registry,
        worker_id="telegram-worker-after-crash",
        capabilities=(),
        clock=lambda: recovered_at,
        lease_seconds=90,
        heartbeat_seconds=30,
    )

    assert await healthy_worker.run_once() is True

    assert client.calls == 1
    async with release3_factory() as session:
        recovered_job = await session.get(WorkflowJob, workflow_job.id)
        receipt = await session.scalar(
            select(PublishOperationReceipt).where(PublishOperationReceipt.publish_job_id == publish_job_id)
        )
        publish_job = await session.get(PublishJob, publish_job_id)
        reconciliation = await get_reconciliation_case(session, publish_job_id)
    assert recovered_job is not None and recovered_job.status == JobStatus.NEEDS_REVIEW
    assert recovered_job.attempt_count == 2
    assert recovered_job.error_code == "telegram_publish_reconciliation_required"
    assert receipt is not None and receipt.status == "ambiguous"
    assert publish_job is not None and publish_job.status == "reconciliation_required"
    assert reconciliation is not None and reconciliation.status == "pending"


@pytest.mark.asyncio
async def test_crash_after_durable_receipt_replay_skips_send_and_finishes_publication(
    release3_factory,
):
    publish_job_id = await _seed_publish_job(
        release3_factory,
        route_name="PostReceiptCrash",
    )
    client = CountingTelegramClient()
    injector = ScriptedFaultInjector({"publication.after_receipt_before_commit": 1})

    async with release3_factory() as session:
        with pytest.raises(InjectedFault) as crashed:
            await publish_telegram(
                session,
                publish_job_id=publish_job_id,
                client=client,
                secret_resolver=resolve_destination_secret,
                fault_injector=injector,
            )

    assert crashed.value.point == "publication.after_receipt_before_commit"
    assert [hit.point for hit in injector.hits] == [
        "telegram.before_send",
        "telegram.after_send_before_receipt",
        "publication.after_receipt_before_commit",
    ]
    assert client.calls == 1

    async with release3_factory() as session:
        receipt = await session.scalar(
            select(PublishOperationReceipt).where(PublishOperationReceipt.publish_job_id == publish_job_id)
        )
        publication = await session.scalar(select(Publication).where(Publication.publish_job_id == publish_job_id))
        interrupted_attempts = list(
            await session.scalars(
                select(PublishAttempt)
                .where(PublishAttempt.publish_job_id == publish_job_id)
                .order_by(PublishAttempt.attempt_number)
            )
        )
    assert receipt is not None and receipt.status == "succeeded"
    assert receipt.remote_message_ids == [9201]
    assert publication is None
    assert [attempt.status for attempt in interrupted_attempts] == ["running"]

    async with release3_factory() as session:
        replay = await publish_telegram(
            session,
            publish_job_id=publish_job_id,
            client=client,
            secret_resolver=resolve_destination_secret,
        )

    assert replay["remote_message_ids"] == [9201]
    assert client.calls == 1
    async with release3_factory() as session:
        publication = await session.scalar(select(Publication).where(Publication.publish_job_id == publish_job_id))
        publish_job = await session.get(PublishJob, publish_job_id)
        attempts = list(
            await session.scalars(
                select(PublishAttempt)
                .where(PublishAttempt.publish_job_id == publish_job_id)
                .order_by(PublishAttempt.attempt_number)
            )
        )
    assert publication is not None and publication.remote_message_ids == [9201]
    assert publish_job is not None and publish_job.status == "succeeded"
    assert [attempt.status for attempt in attempts] == ["failed", "succeeded"]
    assert attempts[0].error_class == "retryable"
    assert attempts[0].error_code == "telegram_publish_attempt_interrupted"
    assert all(attempt.finished_at is not None for attempt in attempts)
