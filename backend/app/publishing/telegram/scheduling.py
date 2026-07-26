from __future__ import annotations

# ruff: noqa: F401
import hashlib
import inspect
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError

from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.decisions import (
    classify_publication_failure,
    reconciliation_required,
)
from app.core.faults import FaultInjector, NoopFaultInjector
from app.core.redaction import redact_secrets, redact_string
from app.db.models import ItemMedia, MediaAsset, SourceItem
from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
from app.generation.revision_validation import RevisionValidationError, validate_approvable_revision
from app.generation.telegram_schema import (
    TelegramEvidenceCitation,
    TelegramVariantContent,
)
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.events import redact_event_data
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin, JobStatus
from app.publishing.models import (
    Destination,
    Publication,
    PublishAttempt,
    PublishJob,
    PublishOperationReceipt,
)
from app.publishing.telegram.client import (
    TelegramClientError,
    TelegramRateLimited,
    TelegramRetryableBeforeDispatch,
)
from app.publishing.telegram.renderer import TelegramPublishNeedsReview, build_publish_plan
from app.publishing.telegram.service_contracts import (
    PublishValidationError,
    ReconciliationCase,
    ReconciliationDestination,
    ReconciliationOperationSummary,
    ReviewedTelegramScheduleError,
    ReviewedTelegramScheduleRequest,
    ReviewedTelegramScheduleResult,
)
from app.stories.models import StoryEvidenceSnapshot, StoryRevision


def _canonical_hash(value: Any) -> str:
    import json

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _revision_dispatch(session: Any, revision: PlatformVariantRevision) -> AutomationDispatch | None:
    current: PlatformVariantRevision | None = revision
    expected_variant_id = revision.platform_variant_id
    seen: set[UUID] = set()
    while current is not None and current.id not in seen:
        if current.platform_variant_id != expected_variant_id:
            return None
        seen.add(current.id)
        dispatch = await session.scalar(
            select(AutomationDispatch)
            .where(AutomationDispatch.variant_revision_id == current.id)
            .order_by(AutomationDispatch.created_at.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        if dispatch is not None:
            return dispatch
        current = (
            await session.get(
                PlatformVariantRevision,
                current.parent_revision_id,
                populate_existing=True,
            )
            if current.parent_revision_id
            else None
        )
    return None


def _schedule_utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReviewedTelegramScheduleError(
            "telegram_schedule_time_naive",
            f"{field} must be timezone-aware",
        )
    return value.astimezone(UTC)


def _row_time_matches(value: datetime | None, expected: datetime) -> bool:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return False
    return value.astimezone(UTC) == expected


def _enum_text(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


def _validate_schedule_replay(
    *,
    publish_job: PublishJob,
    workflow_job: WorkflowJob,
    publication: Publication | None,
    revision: PlatformVariantRevision,
    destination: Destination,
    idempotency_key: str,
    scheduled_for: datetime,
) -> None:
    if publication is not None:
        raise ReviewedTelegramScheduleError(
            "telegram_schedule_already_published",
            "Telegram revision is already published",
        )
    if (
        publish_job.destination_id != destination.id
        or publish_job.platform_variant_revision_id != revision.id
        or publish_job.idempotency_key != idempotency_key
        or publish_job.payload_hash != revision.content_hash
        or publish_job.workflow_job_id != workflow_job.id
        or publish_job.status != "scheduled"
        or not _row_time_matches(publish_job.scheduled_for, scheduled_for)
    ):
        raise ReviewedTelegramScheduleError(
            "telegram_schedule_conflict",
            "Existing Telegram publish intent conflicts with this schedule",
        )
    if (
        workflow_job.job_type != "telegram.publish"
        or workflow_job.idempotency_key != idempotency_key
        or _enum_text(workflow_job.status) != JobStatus.QUEUED.value
        or _enum_text(workflow_job.origin) != JobOrigin.MANUAL.value
        or workflow_job.pause_sensitive is not True
        or not _row_time_matches(workflow_job.scheduled_for, scheduled_for)
        or workflow_job.payload != {"publish_job_id": str(publish_job.id)}
    ):
        raise ReviewedTelegramScheduleError(
            "telegram_schedule_workflow_drift",
            "Existing Telegram workflow drift conflicts with this schedule",
        )


async def schedule_reviewed_telegram(
    session: Any,
    *,
    revision_id: UUID,
    request: ReviewedTelegramScheduleRequest,
    clock: Callable[[], datetime] | None = None,
) -> ReviewedTelegramScheduleResult:
    """Persist one exact reviewed Telegram schedule without contacting Telegram."""

    schedule_clock = clock or (lambda: datetime.now(UTC))
    observed_at = _schedule_utc(
        schedule_clock(),
        field="Scheduling clock",
    )
    scheduled_for = _schedule_utc(request.scheduled_for, field="scheduled_for")

    candidate = await session.scalar(
        select(PlatformVariantRevision)
        .where(PlatformVariantRevision.id == revision_id)
        .execution_options(populate_existing=True)
    )
    if candidate is None:
        raise ReviewedTelegramScheduleError(
            "telegram_revision_missing",
            "Telegram draft not found",
            status_code=404,
        )

    # Revision creation serializes on the parent variant. Lock it first so the
    # currentness check cannot race a newly-created higher revision.
    variant = await session.scalar(
        select(PlatformVariant)
        .where(PlatformVariant.id == candidate.platform_variant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if variant is None or variant.platform != "telegram":
        raise ReviewedTelegramScheduleError(
            "telegram_revision_lineage_invalid",
            "Telegram draft lineage is invalid",
        )
    revision = await session.scalar(
        select(PlatformVariantRevision)
        .where(
            PlatformVariantRevision.id == revision_id,
            PlatformVariantRevision.platform_variant_id == variant.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if revision is None:
        raise ReviewedTelegramScheduleError(
            "telegram_revision_missing",
            "Telegram draft not found",
            status_code=404,
        )
    latest_id = await session.scalar(
        select(PlatformVariantRevision.id)
        .where(PlatformVariantRevision.platform_variant_id == variant.id)
        .order_by(
            PlatformVariantRevision.revision_number.desc(),
            PlatformVariantRevision.created_at.desc(),
            PlatformVariantRevision.id.desc(),
        )
        .limit(1)
    )
    if latest_id != revision.id:
        raise ReviewedTelegramScheduleError(
            "telegram_revision_not_current",
            "Telegram draft revision is not current",
        )
    if revision.approval_state != "approved":
        raise ReviewedTelegramScheduleError(
            "telegram_revision_not_approved",
            "Telegram revision must be approved before scheduling",
        )
    if request.content_hash != revision.content_hash:
        raise ReviewedTelegramScheduleError(
            "telegram_revision_changed",
            "Telegram draft content changed",
        )
    try:
        content = TelegramVariantContent.model_validate(revision.content)
        validate_approvable_revision(revision)
    except RevisionValidationError, TypeError, ValueError:
        raise ReviewedTelegramScheduleError(
            "telegram_revision_schema_invalid",
            "Telegram revision schema or validation gates are invalid",
        ) from None
    if content.dry_run:
        raise ReviewedTelegramScheduleError(
            "telegram_revision_dry_run",
            "Dry-run Telegram revisions cannot be scheduled",
        )
    if _canonical_hash({"content": revision.content, "evidence_map": revision.evidence_map}) != revision.content_hash:
        raise ReviewedTelegramScheduleError(
            "telegram_revision_hash_drift",
            "Telegram revision hash no longer matches its content",
        )

    idempotency_key = f"telegram-publish:{request.destination_id}:{revision.id}:{revision.content_hash}"
    publish_job = await session.scalar(
        select(PublishJob)
        .where(PublishJob.idempotency_key == idempotency_key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    dispatch = await _revision_dispatch(session, revision)
    if dispatch is None:
        raise ReviewedTelegramScheduleError(
            "telegram_route_provenance_missing",
            "Telegram revision has no route provenance",
        )
    route = await session.get(
        AutomationRoute,
        dispatch.route_id,
        populate_existing=True,
    )
    if route is None:
        raise ReviewedTelegramScheduleError(
            "telegram_route_missing",
            "Telegram revision route is missing",
        )
    if route.destination_id != request.destination_id:
        raise ReviewedTelegramScheduleError(
            "telegram_route_destination_mismatch",
            "Telegram route does not match the requested destination",
        )

    publish_job_created = False
    if publish_job is None:
        observed_at = _schedule_utc(
            schedule_clock(),
            field="Scheduling clock",
        )
        if scheduled_for <= observed_at:
            raise ReviewedTelegramScheduleError(
                "telegram_schedule_not_future",
                "scheduled_for must be strictly in the future",
            )
        candidate_publish_job = PublishJob(
            destination_id=request.destination_id,
            platform_variant_revision_id=revision.id,
            status="scheduled",
            idempotency_key=idempotency_key,
            payload_hash=revision.content_hash,
            scheduled_for=scheduled_for,
        )
        try:
            async with session.begin_nested():
                session.add(candidate_publish_job)
                await session.flush()
        except IntegrityError:
            publish_job = await session.scalar(
                select(PublishJob)
                .where(PublishJob.idempotency_key == idempotency_key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if publish_job is None:  # pragma: no cover - unique conflict guarantees it
                raise ReviewedTelegramScheduleError(
                    "telegram_schedule_insert_conflict",
                    "Telegram publish intent conflicted with this schedule",
                ) from None
        else:
            publish_job = candidate_publish_job
            publish_job_created = True

    destination = await session.scalar(
        select(Destination)
        .where(Destination.id == request.destination_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if destination is None or destination.platform != "telegram":
        raise ReviewedTelegramScheduleError(
            "telegram_destination_invalid",
            "An existing Telegram destination is required",
        )
    if not destination.enabled:
        raise ReviewedTelegramScheduleError(
            "telegram_destination_disabled",
            "Telegram destination must be enabled",
        )

    workflow_job = await session.scalar(
        select(WorkflowJob)
        .where(WorkflowJob.idempotency_key == idempotency_key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if publish_job is None:  # pragma: no cover - creation/reload above is exhaustive
        raise ReviewedTelegramScheduleError(
            "telegram_schedule_publish_intent_missing",
            "Telegram publish intent is unavailable",
        )
    if publish_job_created and workflow_job is not None:
        raise ReviewedTelegramScheduleError(
            "telegram_schedule_durable_drift",
            "Existing Telegram durable rows conflict with this schedule",
        )
    if not publish_job_created:
        if workflow_job is None:
            raise ReviewedTelegramScheduleError(
                "telegram_schedule_durable_drift",
                "Existing Telegram durable rows conflict with this schedule",
            )
        publication = await session.scalar(
            select(Publication)
            .where(Publication.publish_job_id == publish_job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        _validate_schedule_replay(
            publish_job=publish_job,
            workflow_job=workflow_job,
            publication=publication,
            revision=revision,
            destination=destination,
            idempotency_key=idempotency_key,
            scheduled_for=scheduled_for,
        )
        return ReviewedTelegramScheduleResult(
            publish_job=publish_job,
            workflow_job=workflow_job,
            created=False,
        )

    enqueue = await JobRepository(session).enqueue_job(
        job_type="telegram.publish",
        payload={"publish_job_id": str(publish_job.id)},
        idempotency_key=idempotency_key,
        origin=JobOrigin.MANUAL,
        scheduled_for=scheduled_for,
        pause_sensitive=True,
    )
    if not enqueue.created:
        raise ReviewedTelegramScheduleError(
            "telegram_schedule_concurrent_drift",
            "Telegram workflow already exists without a matching publish intent",
        )
    observed_at = _schedule_utc(
        schedule_clock(),
        field="Scheduling clock",
    )
    if scheduled_for <= observed_at:
        raise ReviewedTelegramScheduleError(
            "telegram_schedule_not_future",
            "scheduled_for must be strictly in the future",
        )
    publish_job.workflow_job_id = enqueue.job.id
    session.add(
        WorkflowEvent(
            workflow_job_id=enqueue.job.id,
            event_type="telegram.publish.scheduled",
            actor="operator",
            event_data=redact_event_data(
                {
                    "publish_job_id": str(publish_job.id),
                    "destination_id": str(destination.id),
                    "revision_id": str(revision.id),
                    "content_hash": revision.content_hash,
                    "scheduled_for": scheduled_for.isoformat(),
                }
            ),
        )
    )
    await session.flush()
    return ReviewedTelegramScheduleResult(
        publish_job=publish_job,
        workflow_job=enqueue.job,
        created=True,
    )

