from __future__ import annotations

# ruff: noqa: F401
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.automations.models import AutomationDispatch, AutomationRoute, TelegramSourceConfig
from app.automations.telegram.contracts import (
    TelegramEnvelope,
    TelegramFetchRequest,
    telegram_envelope_fingerprint,
)
from app.automations.telegram.decisions import (
    classify_activation_page,
    evaluate_backfill_eligibility,
    evaluate_media_policy,
    evaluate_review_policy,
)
from app.automations.telegram.policy import evaluate_auto_publish
from app.automations.telegram.registry import TelegramSourceRegistry
from app.automations.telegram.route_policy import evaluate_content_filter, next_allowed_at, retry_at
from app.core.faults import FaultInjector, NoopFaultInjector
from app.core.redaction import redact_secrets, redact_string
from app.db.models import ContentItem, ItemMedia, MediaAsset, Source, SourceItem
from app.generation.models import (
    AIProviderProfile,
    BrandProfile,
    ContentPack,
    GenerationAttempt,
    GenerationRun,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.providers.base import GenerationProviderRequest, ProviderMessage
from app.generation.providers.openrouter import (
    OpenRouterNeedsReviewError,
    OpenRouterPermanentError,
    OpenRouterRetryableError,
)
from app.generation.providers.profiles import ProviderProfileConfigurationError
from app.generation.revision_fence import RegenerationFenceConflict, require_revision_write_allowed
from app.generation.revision_validation import RevisionValidationError, validate_approvable_revision
from app.generation.telegram_schema import (
    TelegramEvidenceCitation,
    TelegramRewriteInput,
    TelegramRewriteOutput,
    TelegramVariantContent,
)
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.events import redact_event_data
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext, JobHandler
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin, job_payload_copy
from app.media.reference_fence import fence_platform_revision_media_write
from app.publishing.models import Destination, PublishJob
from app.stories.models import StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision
from app.workflows.states import require_generation_run_transition

logger = logging.getLogger(__name__)


def _redacted_dict(value: object) -> dict[str, Any]:
    redacted = redact_secrets(value)
    return redacted if isinstance(redacted, dict) else {}


def _redacted_list(value: object) -> list[Any]:
    redacted = redact_secrets(value)
    return redacted if isinstance(redacted, list) else []


def sha256_canonical(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generation_input_hash(request_payload: dict[str, Any]) -> str | None:
    semantic = request_payload.get("semantic")
    input_payload = request_payload.get("input")
    if not isinstance(semantic, dict) or not isinstance(input_payload, dict):
        return None
    return sha256_canonical({"semantic": semantic, "input": input_payload})


def validate_evidence_snapshot(snapshot: Any) -> None:
    text = snapshot.content_text
    if not isinstance(text, str) or not text:
        raise ValueError("captured evidence text is empty")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != snapshot.content_sha256:
        raise ValueError("captured evidence hash does not match")


def build_evidence_map(snapshot: Any) -> list[dict[str, Any]]:
    validate_evidence_snapshot(snapshot)
    citation = TelegramEvidenceCitation(
        evidence_snapshot_id=snapshot.id,
        evidence_key=snapshot.evidence_key,
        source_url=snapshot.source_url,
        locator=f"chars:0-{len(snapshot.content_text)}",
        excerpt_sha256=snapshot.content_sha256,
    )
    return [citation.model_dump(mode="json")]


class RouteJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: UUID
    defer_root_job_id: UUID | None = None
    defer_sequence: int = Field(default=0, ge=0)


class ProcessDispatchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dispatch_id: UUID
    force_review: bool = False
    completed_research_run_id: UUID | None = None
    prompt_template_version_id: UUID | None = None
    prompt_checksum: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_prompt_snapshot(self):
        if (self.prompt_template_version_id is None) != (self.prompt_checksum is None):
            raise ValueError("prompt version and checksum must be supplied together")
        return self


class InitializeJobPayload(RouteJobPayload):
    activation_requested_at: datetime | None = None


class BackfillJobPayload(RouteJobPayload):
    count: int | None = Field(default=None, ge=1, le=100)
    since: datetime | None = None

    @model_validator(mode="after")
    def validate_bound(self):
        if (self.count is None) == (self.since is None):
            raise ValueError("provide exactly one backfill bound")
        if self.since is not None and (self.since.tzinfo is None or self.since.utcoffset() is None):
            raise ValueError("backfill since must be timezone-aware")
        return self


class DryRunJobPayload(RouteJobPayload):
    source_message_id: int | None = Field(default=None, ge=1)
    force_review: bool = True


@dataclass(frozen=True, slots=True)
class TelegramRouteHandlers:
    initialize: JobHandler
    poll: JobHandler
    backfill: JobHandler
    dry_run: JobHandler


@dataclass(frozen=True, slots=True)
class _LoadedRoute:
    route: AutomationRoute
    source: Source
    config: TelegramSourceConfig
    control: AutomationControl
    adapter: Any


@dataclass(frozen=True, slots=True)
class _ForwardStep:
    envelopes: tuple[TelegramEnvelope, ...]
    state: dict[str, Any] | None
    complete: bool
    last_scanned_id: int


def _parse_payload(model, payload: dict):
    try:
        return model.model_validate(payload)
    except ValidationError:
        raise PermanentJobError(
            code="invalid_telegram_route_payload",
            message="Invalid Telegram route job payload",
        ) from None


