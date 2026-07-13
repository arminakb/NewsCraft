from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import Response
from sqlalchemy import func, select

from app.api.telegram_drafts import (
    TelegramReconcileIn,
    reconcile_telegram_publish_job,
)
from app.automations.models import AutomationRoute
from app.automations.telegram.handlers import sha256_canonical
from app.db.models import ItemMedia, MediaAsset, SourceItem
from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
from app.generation.telegram_schema import TelegramEvidenceCitation, TelegramVariantContent
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.models import AutomationControl, WorkflowJob
from app.jobs.types import JobOrigin
from app.publishing.models import (
    Publication,
    PublishJob,
    PublishOperationReceipt,
)
from app.publishing.telegram import service as telegram_service
from app.publishing.telegram.client import (
    TelegramAmbiguousError,
    TelegramPermanentError,
    TelegramRateLimited,
    TelegramRetryableBeforeDispatch,
)
from app.publishing.telegram.contracts import TelegramOperationResult
from app.publishing.telegram.service import (
    ReviewedTelegramScheduleError,
    publish_telegram,
    schedule_reviewed_telegram,
)
from app.stories.models import StoryEvidenceSnapshot, StoryRevision
from tests.postgres.test_telegram_process_handler import seed_dispatch


class BlockingTelegramClient:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def execute(self, operation, token):
        assert token == "destination-token"
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return TelegramOperationResult(
            remote_message_ids=(7101,),
            response_metadata={"ok": True, "result_count": 1},
        )


class AmbiguousTelegramClient:
    async def execute(self, operation, token):
        raise TelegramAmbiguousError(
            "response lost after dispatch",
            metadata={"http_status": 502, "description": "upstream failure"},
        )


class FailingTelegramClient:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def execute(self, operation, token):
        self.calls += 1
        raise self.error


class ResumeTelegramClient:
    def __init__(self) -> None:
        self.methods: list[str] = []
        self.message_attempts = 0

    async def execute(self, operation, token):
        self.methods.append(operation.method)
        if operation.method == "sendPhoto":
            return TelegramOperationResult((8101,), {"ok": True, "result_count": 1})
        self.message_attempts += 1
        if self.message_attempts == 1:
            raise TelegramRateLimited(retry_after=1)
        return TelegramOperationResult((8102,), {"ok": True, "result_count": 1})


class CountingTelegramClient:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, operation, token):
        self.calls += 1
        return TelegramOperationResult((9101,), {"ok": True, "result_count": 1})


async def resolve_destination_secret(secret_ref: str) -> str:
    assert secret_ref == "TELEGRAM_DESTINATION_TOKEN"
    return "destination-token"


@dataclass(frozen=True)
class PublishFixture:
    concurrent_job_id: UUID
    reconcile_published_job_id: UUID
    reconcile_not_published_job_id: UUID


async def _seed_publish_fixtures(session_factory) -> PublishFixture:
    shared: dict = {}
    publish_job_ids: list[UUID] = []
    async with session_factory() as session:
        async with session.begin():
            for route_name in ("Concurrent", "ReconcilePublished", "ReconcileNotPublished"):
                dispatch, _, shared = await seed_dispatch(
                    session,
                    route_name=route_name,
                    publishing_policy="auto_publish",
                    allow_auto=True,
                    shared=shared,
                )
                route = await session.get(AutomationRoute, dispatch.route_id)
                source_item = await session.get(SourceItem, dispatch.source_item_id)
                snapshot = await session.scalar(
                    select(StoryEvidenceSnapshot).where(
                        StoryEvidenceSnapshot.story_id == shared["story"].id,
                        StoryEvidenceSnapshot.content_item_id == source_item.content_item_id,
                    )
                )
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
                    content_hash=sha256_canonical(
                        {"content": content, "evidence_map": evidence_map}
                    ),
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
                publish_job_ids.append(publish_job.id)

    return PublishFixture(*publish_job_ids)


async def _seed_schedulable_revision(session):
    dispatch, _, _ = await seed_dispatch(
        session,
        route_name="ReviewedScheduleFreshness",
        publishing_policy="review_required",
    )
    route = await session.get(AutomationRoute, dispatch.route_id)
    source_item = await session.get(SourceItem, dispatch.source_item_id)
    story_revision = await session.get(StoryRevision, dispatch.story_revision_id)
    snapshot = await session.scalar(
        select(StoryEvidenceSnapshot).where(
            StoryEvidenceSnapshot.story_id == story_revision.story_id,
            StoryEvidenceSnapshot.content_item_id == source_item.content_item_id,
        )
    )
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
        body="Reviewed schedule freshness",
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
    dispatch.variant_revision_id = revision.id
    dispatch.status = "approved"
    return revision, route


@pytest.mark.asyncio
async def test_reviewed_schedule_refreshes_identity_mapped_revision(
    db_session,
    session_factory,
):
    async with db_session.begin():
        revision, route = await _seed_schedulable_revision(db_session)
    revision_id = revision.id
    content_hash = revision.content_hash
    destination_id = route.destination_id

    async with session_factory() as concurrent:
        async with concurrent.begin():
            changed = await concurrent.get(PlatformVariantRevision, revision_id)
            changed.approval_state = "pending_review"
            changed.approved_at = None

    due = datetime.now(UTC) + timedelta(hours=1)
    with pytest.raises(ReviewedTelegramScheduleError, match="approved"):
        async with db_session.begin():
            await schedule_reviewed_telegram(
                db_session,
                revision_id=revision_id,
                request=SimpleNamespace(
                    content_hash=content_hash,
                    destination_id=destination_id,
                    scheduled_for=due,
                ),
                clock=lambda: due - timedelta(minutes=30),
            )


@pytest.mark.asyncio
async def test_pre_dispatch_revalidation_refreshes_control_changed_between_transactions(
    session_factory,
    monkeypatch,
):
    fixture = await _seed_publish_fixtures(session_factory)
    client = CountingTelegramClient()
    original_revalidate = telegram_service._revalidate_claim
    changed = False

    async def change_control_then_revalidate(session, context):
        nonlocal changed
        if not changed:
            async with session_factory() as concurrent:
                async with concurrent.begin():
                    control = await concurrent.get(AutomationControl, "global")
                    control.global_pause = True
            changed = True
        return await original_revalidate(session, context)

    monkeypatch.setattr(
        telegram_service,
        "_revalidate_claim",
        change_control_then_revalidate,
    )

    async with session_factory() as session:
        with pytest.raises(NeedsReviewJobError) as caught:
            await publish_telegram(
                session,
                publish_job_id=fixture.concurrent_job_id,
                client=client,
                secret_resolver=resolve_destination_secret,
            )

    assert caught.value.code == "telegram_publish_context_drift"
    assert changed is True
    assert client.calls == 0


@pytest.mark.asyncio
async def test_concurrent_publish_claim_sends_once_and_creates_one_publication(
    session_factory,
):
    fixture = await _seed_publish_fixtures(session_factory)
    client = BlockingTelegramClient()

    async def publish_first():
        async with session_factory() as session:
            return await publish_telegram(
                session,
                publish_job_id=fixture.concurrent_job_id,
                client=client,
                secret_resolver=resolve_destination_secret,
            )

    first = asyncio.create_task(publish_first())
    await asyncio.wait_for(client.entered.wait(), timeout=10)

    async with session_factory() as inspection_session:
        committed_receipt = await inspection_session.scalar(
            select(PublishOperationReceipt).where(
                PublishOperationReceipt.publish_job_id == fixture.concurrent_job_id
            )
        )
        assert committed_receipt.status == "dispatching"
        assert committed_receipt.attempt_count == 1

    async with session_factory() as losing_session:
        with pytest.raises(RetryableJobError) as caught:
            await publish_telegram(
                losing_session,
                publish_job_id=fixture.concurrent_job_id,
                client=client,
                secret_resolver=resolve_destination_secret,
            )
    assert caught.value.code == "telegram_publish_not_due"
    assert caught.value.retry_at is not None

    client.release.set()
    result = await asyncio.wait_for(first, timeout=10)
    assert result["remote_message_ids"] == [7101]
    assert client.calls == 1

    async with session_factory() as session:
        receipts = list(
            await session.scalars(
                select(PublishOperationReceipt).where(
                    PublishOperationReceipt.publish_job_id == fixture.concurrent_job_id
                )
            )
        )
        publications = list(
            await session.scalars(
                select(Publication).where(
                    Publication.publish_job_id == fixture.concurrent_job_id
                )
            )
        )
        assert len(receipts) == 1
        assert receipts[0].status == "succeeded"
        assert receipts[0].attempt_count == 1
        assert receipts[0].remote_message_ids == [7101]
        assert len(publications) == 1
        assert publications[0].remote_message_ids == [7101]

    async with session_factory() as idempotent_session:
        repeated = await publish_telegram(
            idempotent_session,
            publish_job_id=fixture.concurrent_job_id,
            client=client,
            secret_resolver=resolve_destination_secret,
        )
    assert repeated["idempotent"] is True
    assert client.calls == 1


@pytest.mark.asyncio
async def test_publish_failure_classes_persist_safe_retry_and_attention_states(session_factory):
    fixture = await _seed_publish_fixtures(session_factory)
    cases = (
        (
            fixture.concurrent_job_id,
            FailingTelegramClient(TelegramRateLimited(retry_after=7)),
            RetryableJobError,
            "telegram_rate_limited",
            "pending",
            "queued",
        ),
        (
            fixture.reconcile_published_job_id,
            FailingTelegramClient(TelegramRetryableBeforeDispatch("connect failed")),
            RetryableJobError,
            "telegram_connect_failed",
            "pending",
            "queued",
        ),
        (
            fixture.reconcile_not_published_job_id,
            FailingTelegramClient(TelegramPermanentError("rejected")),
            PermanentJobError,
            "telegram_publish_permanent",
            "failed",
            "attention",
        ),
    )

    for publish_job_id, client, error_type, code, receipt_status, job_status in cases:
        async with session_factory() as session:
            with pytest.raises(error_type) as caught:
                await publish_telegram(
                    session,
                    publish_job_id=publish_job_id,
                    client=client,
                    secret_resolver=resolve_destination_secret,
                )
        assert caught.value.code == code
        assert client.calls == 1
        async with session_factory() as session:
            receipt = await session.scalar(
                select(PublishOperationReceipt).where(
                    PublishOperationReceipt.publish_job_id == publish_job_id
                )
            )
            publish_job = await session.get(PublishJob, publish_job_id)
            assert receipt.status == receipt_status
            assert publish_job.status == job_status
            if receipt_status == "pending":
                assert receipt.next_attempt_at is not None


@pytest.mark.asyncio
async def test_multi_operation_retry_skips_succeeded_receipt_and_orders_publication_ids(
    session_factory,
    tmp_path,
):
    fixture = await _seed_publish_fixtures(session_factory)
    payload = b"exact-image-content"
    media_path = tmp_path / "publish.jpg"
    media_path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()

    async with session_factory() as session:
        async with session.begin():
            publish_job = await session.get(PublishJob, fixture.concurrent_job_id)
            revision = await session.get(
                PlatformVariantRevision,
                publish_job.platform_variant_revision_id,
            )
            content = TelegramVariantContent.model_validate(revision.content)
            source_item = await session.get(SourceItem, content.source_item_id)
            asset = MediaAsset(
                original_url="https://t.me/source/media.jpg",
                normalized_url="https://t.me/source/media.jpg",
                url_hash=hashlib.sha256(b"https://t.me/source/media.jpg").hexdigest(),
                kind="image",
                mime_type="image/jpeg",
                source_field="telegram_media",
                checksum_sha256=checksum,
                storage_path=str(media_path),
                fetch_status="downloaded",
            )
            session.add(asset)
            await session.flush()
            session.add(
                ItemMedia(
                    content_item_id=source_item.content_item_id,
                    media_asset_id=asset.id,
                    role="primary",
                    sort_order=0,
                    extracted_from="telegram",
                )
            )
            updated_content = content.model_copy(
                update={
                    "body": "x" * 1025,
                    "media_policy": "preserve",
                    "media_asset_ids": [asset.id],
                }
            ).model_dump(mode="json")
            revision.content = updated_content
            revision.content_hash = sha256_canonical(
                {"content": updated_content, "evidence_map": revision.evidence_map}
            )
            publish_job.payload_hash = revision.content_hash

    client = ResumeTelegramClient()
    async with session_factory() as session:
        with pytest.raises(RetryableJobError) as caught:
            await publish_telegram(
                session,
                publish_job_id=fixture.concurrent_job_id,
                client=client,
                secret_resolver=resolve_destination_secret,
            )
    assert caught.value.code == "telegram_rate_limited"

    async with session_factory() as session:
        receipts = list(
            await session.scalars(
                select(PublishOperationReceipt)
                .where(PublishOperationReceipt.publish_job_id == fixture.concurrent_job_id)
                .order_by(PublishOperationReceipt.operation_index)
            )
        )
        assert [receipt.status for receipt in receipts] == ["succeeded", "pending"]
        receipts[1].next_attempt_at = datetime.now(UTC)
        await session.commit()

    async with session_factory() as session:
        result = await publish_telegram(
            session,
            publish_job_id=fixture.concurrent_job_id,
            client=client,
            secret_resolver=resolve_destination_secret,
        )

    assert client.methods == ["sendPhoto", "sendMessage", "sendMessage"]
    assert result["remote_message_ids"] == [8101, 8102]
    assert result["permalink"] == "https://t.me/destination/8101"
    async with session_factory() as session:
        publication = await session.scalar(
            select(Publication).where(Publication.publish_job_id == fixture.concurrent_job_id)
        )
        receipts = list(
            await session.scalars(
                select(PublishOperationReceipt)
                .where(PublishOperationReceipt.publish_job_id == fixture.concurrent_job_id)
                .order_by(PublishOperationReceipt.operation_index)
            )
        )
        assert publication.remote_message_ids == [8101, 8102]
        assert [receipt.attempt_count for receipt in receipts] == [1, 2]


async def _make_publish_ambiguous(session_factory, publish_job_id: UUID) -> None:
    async with session_factory() as session:
        with pytest.raises(NeedsReviewJobError) as caught:
            await publish_telegram(
                session,
                publish_job_id=publish_job_id,
                client=AmbiguousTelegramClient(),
                secret_resolver=resolve_destination_secret,
            )
    assert caught.value.code == "telegram_publish_ambiguous"


@pytest.mark.asyncio
async def test_reconciliation_published_and_not_published_are_durable_and_deterministic(
    session_factory,
):
    fixture = await _seed_publish_fixtures(session_factory)
    await _make_publish_ambiguous(session_factory, fixture.reconcile_published_job_id)
    await _make_publish_ambiguous(session_factory, fixture.reconcile_not_published_job_id)

    async with session_factory() as session:
        response = Response()
        published = await reconcile_telegram_publish_job(
            fixture.reconcile_published_job_id,
            TelegramReconcileIn(outcome="published", remote_message_ids=[7201]),
            response,
            session,
        )
    assert response.status_code == 200
    assert published["remote_message_ids"] == [7201]
    assert published["reconciliation_status"] == "confirmed"

    async with session_factory() as session:
        response = Response()
        requeued = await reconcile_telegram_publish_job(
            fixture.reconcile_not_published_job_id,
            TelegramReconcileIn(outcome="not_published"),
            response,
            session,
        )
    assert response.status_code == 202
    assert requeued["reconciliation_status"] == "requeued"
    workflow_job_id = UUID(str(requeued["job"]["job_id"]))

    async with session_factory() as session:
        published_receipt = await session.scalar(
            select(PublishOperationReceipt).where(
                PublishOperationReceipt.publish_job_id == fixture.reconcile_published_job_id
            )
        )
        confirmed_publication = await session.scalar(
            select(Publication).where(
                Publication.publish_job_id == fixture.reconcile_published_job_id
            )
        )
        not_published_receipt = await session.scalar(
            select(PublishOperationReceipt).where(
                PublishOperationReceipt.publish_job_id
                == fixture.reconcile_not_published_job_id
            )
        )
        not_published_job = await session.get(
            PublishJob,
            fixture.reconcile_not_published_job_id,
        )
        retry_job = await session.get(WorkflowJob, workflow_job_id)
        retry_job_count = await session.scalar(
            select(func.count())
            .select_from(WorkflowJob)
            .where(
                WorkflowJob.idempotency_key.like(
                    f"telegram-publish-reconcile:{fixture.reconcile_not_published_job_id}:%"
                )
            )
        )

        assert published_receipt.status == "succeeded"
        assert published_receipt.remote_message_ids == [7201]
        assert published_receipt.response_metadata["operator_confirmed"] is True
        assert confirmed_publication.remote_message_ids == [7201]

        assert not_published_receipt.status == "pending"
        assert not_published_receipt.remote_message_ids == []
        assert not_published_receipt.ambiguous_at is None
        assert not_published_job.status == "queued"
        assert not_published_job.workflow_job_id == retry_job.id
        assert retry_job.job_type == "telegram.publish"
        assert retry_job.payload == {
            "publish_job_id": str(fixture.reconcile_not_published_job_id)
        }
        assert retry_job.idempotency_key == (
            f"telegram-publish-reconcile:{fixture.reconcile_not_published_job_id}:"
            f"{not_published_job.scheduled_for.isoformat()}"
        )
        assert retry_job_count == 1
        assert await session.scalar(
            select(func.count())
            .select_from(Publication)
            .where(Publication.publish_job_id == fixture.reconcile_not_published_job_id)
        ) == 0
