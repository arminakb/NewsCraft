from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select

from app.automations.telegram.decisions import (
    classify_publication_failure,
)
from app.core.redaction import redact_string
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.events import redact_event_data
from app.publishing.models import (
    PublishAttempt,
    PublishJob,
    PublishOperationReceipt,
)
from app.publishing.telegram.client import (
    TelegramClientError,
    TelegramRateLimited,
)


@dataclass(frozen=True, slots=True)
class _PublishContext:
    publish_job_id: UUID
    destination_id: UUID
    destination_secret_ref: str
    proxy_profile_id: UUID | None
    target_ref: str
    revision_id: UUID
    dispatch_id: UUID | None
    route_id: UUID
    plan: Any
    attempt_id: UUID


async def _close_running_publish_attempts(
    session: Any,
    *,
    publish_job_id: UUID,
    status: Literal["failed", "needs_review"],
    error_class: Literal["retryable", "needs_review"],
    error_code: str,
    error_message: str,
    finished_at: datetime,
) -> None:
    attempts = list(
        await session.scalars(
            select(PublishAttempt)
            .where(
                PublishAttempt.publish_job_id == publish_job_id,
                PublishAttempt.status == "running",
            )
            .order_by(PublishAttempt.attempt_number)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for attempt in attempts:
        attempt.status = status
        attempt.error_class = error_class
        attempt.error_code = redact_string(error_code)
        attempt.error_message = redact_string(error_message)
        attempt.finished_at = finished_at


async def _record_failure(
    session: Any,
    *,
    context: _PublishContext,
    operation: Any,
    claimed_attempt_count: int,
    error: BaseException,
    observed_at: datetime,
) -> Exception:
    async with session.begin():
        publish_job = await session.scalar(
            select(PublishJob)
            .where(PublishJob.id == context.publish_job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        receipt = await session.scalar(
            select(PublishOperationReceipt)
            .where(
                PublishOperationReceipt.publish_job_id == context.publish_job_id,
                PublishOperationReceipt.operation_index == operation.index,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        attempt = await session.get(PublishAttempt, context.attempt_id)
        if (
            receipt is None
            or publish_job is None
            or attempt is None
            or receipt.status != "dispatching"
            or receipt.attempt_count != claimed_attempt_count
        ):
            return NeedsReviewJobError(
                code="telegram_publish_claim_superseded",
                message="Telegram publish claim was superseded",
            )
        attempt.finished_at = observed_at
        metadata = getattr(error, "metadata", {}) if isinstance(error, TelegramClientError) else {}
        safe_metadata = redact_event_data(metadata)
        if isinstance(safe_metadata, dict):
            receipt.response_metadata = safe_metadata
            attempt.remote_response = safe_metadata
            status = safe_metadata.get("http_status")
            if isinstance(status, int) and not isinstance(status, bool):
                attempt.http_status = status
        decision = classify_publication_failure(error)
        if decision.kind == "retry" and isinstance(error, TelegramRateLimited):
            retry_at = observed_at + timedelta(seconds=decision.retry_delay_seconds or 0)
            receipt.status = "pending"
            receipt.next_attempt_at = retry_at
            publish_job.status = "queued"
            publish_job.scheduled_for = retry_at
            attempt.status = "failed"
            attempt.error_class = "retryable"
            attempt.error_code = redact_string("telegram_rate_limited")
            attempt.error_message = redact_string("Telegram rate limit exceeded")
            return RetryableJobError(
                code="telegram_rate_limited",
                message="Telegram rate limit exceeded",
                retry_at=retry_at,
            )
        if decision.kind == "retry":
            retry_at = observed_at + timedelta(seconds=decision.retry_delay_seconds or 0)
            receipt.status = "pending"
            receipt.next_attempt_at = retry_at
            publish_job.status = "queued"
            publish_job.scheduled_for = retry_at
            attempt.status = "failed"
            attempt.error_class = "retryable"
            attempt.error_code = redact_string("telegram_connect_failed")
            attempt.error_message = redact_string("Telegram connection failed before dispatch")
            return RetryableJobError(
                code="telegram_connect_failed",
                message="Telegram connection failed before dispatch",
                retry_at=retry_at,
            )
        if decision.kind == "reconcile":
            receipt.status = "ambiguous"
            receipt.ambiguous_at = observed_at
            publish_job.status = "reconciliation_required"
            attempt.status = "needs_review"
            attempt.error_class = "needs_review"
            attempt.error_code = redact_string("telegram_publish_ambiguous")
            attempt.error_message = redact_string("Telegram publish outcome is ambiguous")
            return NeedsReviewJobError(
                code="telegram_publish_ambiguous",
                message="Telegram publish outcome is ambiguous",
            )
        receipt.status = "failed"
        publish_job.status = "attention"
        attempt.status = "failed"
        attempt.error_class = "permanent"
        attempt.error_code = redact_string("telegram_publish_permanent")
        attempt.error_message = redact_string("Telegram publish operation failed permanently")
        return PermanentJobError(
            code="telegram_publish_permanent",
            message="Telegram publish operation failed permanently",
        )
