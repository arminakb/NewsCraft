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
from app.stories.models import StoryEvidenceSnapshot, StoryRevision


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
