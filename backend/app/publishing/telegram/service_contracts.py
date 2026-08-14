from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.automations.models import AutomationDispatch
from app.generation.models import PlatformVariant, PlatformVariantRevision
from app.jobs.models import WorkflowJob
from app.publishing.models import (
    PublishJob,
)


def immediate_publish_intent_key(*, destination_id: UUID, revision_id: UUID, content_hash: str) -> str:
    """Idempotency key of the immediate Telegram publish intent.

    Used by the automation dispatcher and by the operator "publish now" action.
    """

    return f"telegram-publish:{destination_id}:{revision_id}:{content_hash}"


def reviewed_schedule_intent_key(*, destination_id: UUID, revision_id: UUID, content_hash: str) -> str:
    """Idempotency key of the operator-reviewed *scheduled* Telegram intent.

    Deliberately namespaced away from :func:`immediate_publish_intent_key`: the
    two intents carry different durable shapes (``queued`` with no due time vs.
    ``scheduled`` with an exact one) and sharing a key made an already-queued
    immediate publish indistinguishable from a drifted schedule replay.
    """

    return f"telegram-publish-schedule:{destination_id}:{revision_id}:{content_hash}"


async def revision_dispatch(session: Any, revision: PlatformVariantRevision) -> AutomationDispatch | None:
    """Walk a revision's ancestry to the automation dispatch that produced it.

    Canonical implementation shared by every Telegram publish entry point
    (reviewed schedule, draft publish, worker publication, reconciliation) so
    provenance resolves under one freshness and platform rule everywhere:
    non-Telegram variants never resolve, and both reads bypass any stale
    identity-mapped row.
    """

    variant = await session.get(
        PlatformVariant,
        revision.platform_variant_id,
        populate_existing=True,
    )
    if variant is None or variant.platform != "telegram":
        return None
    expected_variant_id = revision.platform_variant_id
    current: PlatformVariantRevision | None = revision
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
            if current.parent_revision_id is not None
            else None
        )
    return None


class PublishValidationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ReviewedTelegramScheduleError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class ReviewedTelegramScheduleRequest(Protocol):
    content_hash: str
    destination_id: UUID
    scheduled_for: datetime


@dataclass(frozen=True, slots=True)
class ReviewedTelegramScheduleResult:
    publish_job: PublishJob
    workflow_job: WorkflowJob
    created: bool


class ReconciliationDestination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    target_ref: str


class ReconciliationOperationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_index: int
    operation_key: str
    method: str
    request_hash: str
    status: str
    attempt_count: int
    remote_message_ids: list[int]
    sent_at: datetime | None


class ReconciliationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish_job_id: UUID
    status: Literal["pending"] = "pending"
    publish_status: str
    workflow_job_id: UUID | None
    platform_variant_revision_id: UUID
    destination: ReconciliationDestination
    operations: list[ReconciliationOperationSummary]
    ambiguous_operation_key: str
    ambiguous_at: datetime | None
    ambiguity_reason: str
