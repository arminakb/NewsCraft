from __future__ import annotations

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


async def _load_route(
    context: JobContext,
    route_id: UUID,
    source_registry: TelegramSourceRegistry,
) -> _LoadedRoute:
    route = await context.session.get(AutomationRoute, route_id)
    if route is None:
        raise PermanentJobError(code="route_missing", message="Telegram route was not found")
    source = await context.session.get(Source, route.source_id)
    config = await context.session.get(TelegramSourceConfig, route.source_id)
    control = await context.session.get(AutomationControl, "global")
    if source is None or config is None:
        raise PermanentJobError(
            code="source_configuration_missing",
            message="Telegram source configuration was not found",
        )
    try:
        adapter = source_registry.get(config.access_mode)
    except LookupError:
        raise PermanentJobError(
            code="source_adapter_missing",
            message="Telegram source adapter is not configured",
        ) from None
    return _LoadedRoute(
        route=route,
        source=source,
        config=config,
        control=control or AutomationControl(id="global", global_pause=False, dry_run=False),
        adapter=adapter,
    )


def _request(
    loaded: _LoadedRoute,
    *,
    after_id: int | None = None,
    before_id: int | None = None,
    limit: int = 100,
    since: datetime | None = None,
    snapshot_token: str | None = None,
    page_token: str | None = None,
) -> TelegramFetchRequest:
    config = loaded.config
    return TelegramFetchRequest(
        channel_ref=config.channel_ref,
        after_id=after_id,
        before_id=before_id,
        limit=limit,
        since=since,
        snapshot_token=snapshot_token,
        page_token=page_token,
        api_id_secret_ref=config.api_id_secret_ref,
        api_hash_secret_ref=config.api_hash_secret_ref,
        session_secret_ref=config.session_secret_ref,
    )


def _coordinate(envelope: TelegramEnvelope) -> tuple[datetime, int]:
    return envelope.published_at, envelope.anchor_message_id


async def _capture(
    *,
    loaded: _LoadedRoute,
    envelope: TelegramEnvelope,
    dispatch_kind: str,
    job: JobExecution,
    context: JobContext,
    media_stager: Any,
    enqueue_process: bool = True,
    scheduled_for: datetime | None = None,
    force_review: bool = False,
    filter_reason: str | None = None,
    activation_requested_at: str | None = None,
    required_status: str = "ready",
    deferred_until: datetime,
    dry_run_identity_id: UUID | None = None,
):
    materialized = await media_stager.materialize(loaded.adapter, envelope)
    capture = media_stager.capture_repository(context.session)
    deferred = None
    dispatch = None
    try:
        async with context.session.begin():
            locked, control = await _lock_route_and_control(context, loaded.route.id)
            pause_reason = _validate_locked_route(
                locked,
                control,
                required_status=required_status,
                activation_requested_at=activation_requested_at,
            )
            if pause_reason is not None:
                await _defer_route_job(
                    context,
                    media_stager,
                    route=locked,
                    job=job,
                    scheduled_for=deferred_until,
                )
                deferred = {
                    "held": True,
                    "reason": pause_reason,
                    "deferred_until": deferred_until.isoformat(),
                }
            else:
                dispatch = await capture.capture_and_enqueue(
                    route_id=loaded.route.id,
                    source=loaded.source,
                    cursor=locked,
                    envelope=envelope,
                    materialized_media=materialized,
                    dispatch_kind=dispatch_kind,
                    dry_run_job_id=(dry_run_identity_id or job.id) if dispatch_kind == "dry_run" else None,
                    enqueue_process=enqueue_process,
                    process_scheduled_for=scheduled_for,
                    process_max_attempts=int((locked.retry_policy or {}).get("max_attempts", 3)),
                    force_review=force_review,
                    filter_reason=filter_reason,
                )
    finally:
        try:
            media_stager.cleanup(materialized)
        except Exception:  # noqa: BLE001 - cleanup must not mask durable capture outcome
            logger.exception("failed to clean staged Telegram media")
    return dispatch, deferred


async def _lock_route_and_control(
    context: JobContext,
    route_id: UUID,
) -> tuple[AutomationRoute, AutomationControl]:
    route = await context.session.scalar(
        select(AutomationRoute).where(AutomationRoute.id == route_id).with_for_update()
    )
    if route is None:
        raise PermanentJobError(code="route_missing", message="Telegram route was not found")
    control = await context.session.scalar(
        select(AutomationControl).where(AutomationControl.id == "global").with_for_update()
    )
    return route, control or AutomationControl(id="global", global_pause=False, dry_run=False)


def _validate_locked_route(
    route: AutomationRoute,
    control: AutomationControl,
    *,
    required_status: str,
    activation_requested_at: str | None = None,
) -> str | None:
    if (
        activation_requested_at is not None
        and (route.cursor_state or {}).get("activation_requested_at") != activation_requested_at
    ):
        raise PermanentJobError(
            code="activation_changed",
            message="Telegram route activation changed during initialization",
        )
    if not route.enabled:
        raise PermanentJobError(code="route_disabled", message="Telegram route is disabled")
    if (route.cursor_state or {}).get("status") != required_status:
        raise PermanentJobError(
            code="route_state_changed",
            message="Telegram route state changed before capture",
        )
    if control.global_pause:
        return "global_pause"
    if route.paused_at is not None:
        return "route_pause"
    return None


async def _enqueue_continuation(
    context: JobContext,
    media_stager: Any,
    *,
    route_id: UUID,
    last_scanned_id: int,
    activation_requested_at: str,
    phase: str,
    continuation_state: dict[str, Any],
):
    repository = media_stager if hasattr(media_stager, "enqueue_job") else JobRepository(context.session)
    digest = hashlib.sha256(json.dumps(continuation_state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return await repository.enqueue_job(
        job_type="telegram.route.initialize",
        payload={
            "route_id": str(route_id),
            "activation_requested_at": activation_requested_at,
        },
        idempotency_key=(f"telegram-route-initialize-catch-up:{route_id}:{last_scanned_id}:{phase}:{digest}"),
        origin=JobOrigin.AUTOMATION,
    )


async def _defer_route_job(
    context: JobContext,
    media_stager: Any,
    *,
    route: AutomationRoute,
    job: JobExecution,
    scheduled_for: datetime,
) -> None:
    repository = media_stager if hasattr(media_stager, "enqueue_job") else JobRepository(context.session)
    payload = job_payload_copy(job)
    root_job_id = str(payload.get("defer_root_job_id") or job.id)
    next_sequence = int(payload.get("defer_sequence") or 0) + 1
    payload.update(
        {
            "defer_root_job_id": root_job_id,
            "defer_sequence": next_sequence,
        }
    )
    await repository.enqueue_job(
        job_type=job.job_type,
        payload=payload,
        idempotency_key=(f"telegram-route-deferred:{route.id}:{root_job_id}:{next_sequence}"),
        origin=JobOrigin.AUTOMATION,
        scheduled_for=scheduled_for,
    )


async def _enqueue_forward_continuation(
    context: JobContext,
    media_stager: Any,
    *,
    route_id: UUID,
    job: JobExecution,
    state: dict[str, Any],
    last_scanned_id: int,
) -> None:
    if job.job_type == "telegram.route.initialize":
        activation_requested_at = str(state["activation_requested_at"])
        await _enqueue_continuation(
            context,
            media_stager,
            route_id=route_id,
            last_scanned_id=last_scanned_id,
            activation_requested_at=activation_requested_at,
            phase=str(state["phase"]),
            continuation_state=state,
        )
        return
    repository = media_stager if hasattr(media_stager, "enqueue_job") else JobRepository(context.session)
    digest = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    await repository.enqueue_job(
        job_type=job.job_type,
        payload=job_payload_copy(job),
        idempotency_key=f"telegram-route-poll-forward:{route_id}:{digest}",
        origin=JobOrigin.AUTOMATION,
    )


async def _persist_forward_progress(
    context: JobContext,
    media_stager: Any,
    *,
    route_id: UUID,
    job: JobExecution,
    state_key: str,
    state: dict[str, Any],
    last_scanned_id: int,
    required_status: str,
    activation_requested_at: str | None,
    deferred_until: datetime,
) -> dict[str, Any]:
    stored_state = dict(state)
    if activation_requested_at is not None:
        stored_state["activation_requested_at"] = activation_requested_at
    async with context.session.begin():
        locked, control = await _lock_route_and_control(context, route_id)
        pause_reason = _validate_locked_route(
            locked,
            control,
            required_status=required_status,
            activation_requested_at=activation_requested_at,
        )
        if pause_reason is not None:
            await _defer_route_job(
                context,
                media_stager,
                route=locked,
                job=job,
                scheduled_for=deferred_until,
            )
            return {
                "held": True,
                "reason": pause_reason,
                "deferred_until": deferred_until.isoformat(),
            }
        cursor_state = dict(locked.cursor_state or {})
        cursor_state[state_key] = stored_state
        locked.cursor_state = cursor_state
        await _enqueue_forward_continuation(
            context,
            media_stager,
            route_id=route_id,
            job=job,
            state=stored_state,
            last_scanned_id=last_scanned_id,
        )
    return {
        "route_id": str(route_id),
        "initialized": False,
        "continuation_enqueued": True,
    }


async def _fetch_forward_step(
    loaded: _LoadedRoute,
    *,
    after_id: int,
    page_budget: int,
    saved_state: dict[str, Any] | None,
) -> _ForwardStep:
    state = dict(saved_state or {})
    if state and int(state.get("base_after_id", -1)) != after_id:
        raise PermanentJobError(
            code="telegram_forward_state_invalid",
            message="Telegram forward continuation cursor changed",
        )
    phase = str(state.get("phase", "scan"))
    snapshot_token = state.get("snapshot_token")
    last_scanned_id = int(state.get("last_scanned_id", 0))

    if phase == "capture":
        page_tokens = list(state.get("page_tokens") or [])
        if len(page_tokens) != len({str(token) for token in page_tokens}):
            raise RetryableJobError(
                code="telegram_forward_token_repeated",
                message="Telegram forward continuation repeated a page token",
            )
        selected_tokens = page_tokens[:page_budget]
        pages = []
        seen_source_keys: set[str] = set()
        last_captured_id = int(state.get("last_captured_id", after_id))
        for page_token in selected_tokens:
            result = await loaded.adapter.fetch(
                _request(
                    loaded,
                    after_id=after_id,
                    limit=100,
                    snapshot_token=snapshot_token,
                    page_token=page_token,
                )
            )
            if result.snapshot_token != snapshot_token:
                raise RetryableJobError(
                    code="telegram_forward_snapshot_changed",
                    message="Telegram forward snapshot changed during capture replay",
                )
            page_keys = {item.source_key for item in result.envelopes}
            if not result.envelopes or seen_source_keys.intersection(page_keys):
                raise RetryableJobError(
                    code="telegram_forward_capture_no_progress",
                    message="Telegram forward capture replay made no unique progress",
                )
            page_minimum = min(item.anchor_message_id for item in result.envelopes)
            if page_minimum <= last_captured_id:
                raise RetryableJobError(
                    code="telegram_forward_capture_order_invalid",
                    message="Telegram forward capture replay did not advance",
                )
            last_captured_id = max(item.anchor_message_id for item in result.envelopes)
            seen_source_keys.update(page_keys)
            pages.append(tuple(result.envelopes))
        remaining = page_tokens[len(selected_tokens) :]
        next_state = None
        if remaining:
            next_state = {
                "phase": "capture",
                "base_after_id": after_id,
                "snapshot_token": snapshot_token,
                "page_tokens": remaining,
                "last_scanned_id": last_scanned_id,
                "last_captured_id": last_captured_id,
            }
        envelopes = {item.source_key: item for page in pages for item in page}
        ordered = tuple(sorted(envelopes.values(), key=_coordinate))
        return _ForwardStep(
            envelopes=ordered,
            state=next_state,
            complete=not remaining,
            last_scanned_id=max(
                (item.anchor_message_id for item in ordered),
                default=last_scanned_id,
            ),
        )

    if phase != "scan":
        raise PermanentJobError(
            code="telegram_forward_state_invalid",
            message="Telegram forward continuation phase is invalid",
        )
    prior_tokens = list(state.get("page_tokens") or [])
    next_page_token = state.get("next_page_token")
    if len(prior_tokens) != len({str(token) for token in prior_tokens}):
        raise RetryableJobError(
            code="telegram_forward_token_repeated",
            message="Telegram forward continuation repeated a page token",
        )
    if next_page_token in prior_tokens:
        raise RetryableJobError(
            code="telegram_forward_token_repeated",
            message="Telegram forward continuation reused a page token",
        )
    scanned_pages: list[tuple[TelegramEnvelope, ...]] = []
    scanned_tokens: list[str | None] = []
    for _ in range(page_budget):
        current_token = next_page_token
        result = await loaded.adapter.fetch(
            _request(
                loaded,
                after_id=after_id,
                limit=100,
                snapshot_token=snapshot_token,
                page_token=current_token,
            )
        )
        if snapshot_token is not None and result.snapshot_token != snapshot_token:
            raise RetryableJobError(
                code="telegram_forward_snapshot_changed",
                message="Telegram forward snapshot changed during pagination",
            )
        snapshot_token = result.snapshot_token
        scanned_tokens.append(current_token)
        scanned_pages.append(tuple(result.envelopes))
        if result.envelopes:
            page_minimum = min(item.anchor_message_id for item in result.envelopes)
            if last_scanned_id and page_minimum >= last_scanned_id:
                raise RetryableJobError(
                    code="telegram_forward_envelope_no_progress",
                    message="Telegram forward pages made no unique envelope progress",
                )
            last_scanned_id = min(last_scanned_id, page_minimum) if last_scanned_id else page_minimum
        if result.complete:
            remaining = list(reversed(prior_tokens))
            envelopes = {item.source_key: item for page in reversed(scanned_pages) for item in page}
            next_state = None
            if remaining:
                next_state = {
                    "phase": "capture",
                    "base_after_id": after_id,
                    "snapshot_token": snapshot_token,
                    "page_tokens": remaining,
                    "last_scanned_id": last_scanned_id,
                    "last_captured_id": max(
                        (item.anchor_message_id for item in envelopes.values()),
                        default=after_id,
                    ),
                }
            return _ForwardStep(
                envelopes=tuple(sorted(envelopes.values(), key=_coordinate)),
                state=next_state,
                complete=not remaining,
                last_scanned_id=last_scanned_id,
            )
        if not result.envelopes or result.next_page_token is None:
            raise RetryableJobError(
                code="telegram_forward_page_incomplete",
                message="Telegram source did not provide a progressing forward page",
            )
        if result.next_page_token == current_token or result.next_page_token in {
            *prior_tokens,
            *scanned_tokens,
        }:
            raise RetryableJobError(
                code="telegram_forward_token_repeated",
                message="Telegram forward pagination repeated a page token",
            )
        next_page_token = result.next_page_token

    return _ForwardStep(
        envelopes=(),
        state={
            "phase": "scan",
            "base_after_id": after_id,
            "snapshot_token": snapshot_token,
            "next_page_token": next_page_token,
            "page_tokens": [*prior_tokens, *scanned_tokens],
            "last_scanned_id": last_scanned_id,
        },
        complete=False,
        last_scanned_id=last_scanned_id,
    )


async def _fetch_bounded_backfill(
    loaded: _LoadedRoute,
    *,
    before_id: int,
    count: int | None,
    since: datetime | None,
) -> list[TelegramEnvelope]:
    target = count or 100
    snapshot_token = None
    page_token = None
    seen_tokens: set[str | None] = set()
    envelopes: dict[str, TelegramEnvelope] = {}
    for _ in range(100):
        current_token = page_token
        if current_token in seen_tokens:
            raise RetryableJobError(
                code="telegram_backfill_token_repeated",
                message="Telegram backfill repeated a page token",
            )
        seen_tokens.add(current_token)
        result = await loaded.adapter.fetch(
            _request(
                loaded,
                before_id=before_id,
                limit=min(target - len(envelopes), 100),
                since=since,
                snapshot_token=snapshot_token,
                page_token=page_token,
            )
        )
        if snapshot_token is not None and result.snapshot_token != snapshot_token:
            raise RetryableJobError(
                code="telegram_backfill_snapshot_changed",
                message="Telegram backfill snapshot changed during pagination",
            )
        previous_count = len(envelopes)
        envelopes.update((item.source_key, item) for item in result.envelopes)
        if result.complete or len(envelopes) >= target:
            break
        if len(envelopes) == previous_count or result.next_page_token is None:
            raise RetryableJobError(
                code="telegram_backfill_page_incomplete",
                message="Telegram source did not provide a progressing backfill page",
            )
        if result.next_page_token == current_token or result.next_page_token in seen_tokens:
            raise RetryableJobError(
                code="telegram_backfill_token_repeated",
                message="Telegram backfill repeated a page token",
            )
        snapshot_token = result.snapshot_token
        page_token = result.next_page_token
    else:
        raise RetryableJobError(
            code="telegram_backfill_page_limit",
            message="Telegram backfill exceeded its page limit",
        )
    ordered = sorted(envelopes.values(), key=_coordinate)
    return ordered[-target:]


async def _fetch_recent(loaded: _LoadedRoute, *, limit: int) -> list[TelegramEnvelope]:
    snapshot_token = None
    page_token = None
    seen_tokens: set[str | None] = set()
    envelopes: dict[str, TelegramEnvelope] = {}
    for _ in range(limit):
        current_token = page_token
        if current_token in seen_tokens:
            raise RetryableJobError(
                code="telegram_lookback_token_repeated",
                message="Telegram lookback repeated a page token",
            )
        seen_tokens.add(current_token)
        result = await loaded.adapter.fetch(
            _request(
                loaded,
                limit=limit - len(envelopes),
                snapshot_token=snapshot_token,
                page_token=page_token,
            )
        )
        if snapshot_token is not None and result.snapshot_token != snapshot_token:
            raise RetryableJobError(
                code="telegram_lookback_snapshot_changed",
                message="Telegram lookback snapshot changed during pagination",
            )
        previous_count = len(envelopes)
        envelopes.update((item.source_key, item) for item in result.envelopes)
        if result.complete or len(envelopes) >= limit:
            break
        if len(envelopes) == previous_count or result.next_page_token is None:
            raise RetryableJobError(
                code="telegram_lookback_page_incomplete",
                message="Telegram source did not provide a progressing lookback page",
            )
        if result.next_page_token == current_token or result.next_page_token in seen_tokens:
            raise RetryableJobError(
                code="telegram_lookback_token_repeated",
                message="Telegram lookback repeated a page token",
            )
        snapshot_token = result.snapshot_token
        page_token = result.next_page_token
    else:
        raise RetryableJobError(
            code="telegram_lookback_page_limit",
            message="Telegram lookback exceeded its page limit",
        )
    return sorted(envelopes.values(), key=_coordinate, reverse=True)[:limit]


def build_telegram_route_handlers(
    source_registry: TelegramSourceRegistry,
    media_stager: Any,
    *,
    page_budget: int = 10,
    clock: Callable[[], datetime] | None = None,
) -> TelegramRouteHandlers:
    if page_budget <= 0:
        raise ValueError("page_budget must be positive")
    now = clock or (lambda: datetime.now(UTC))

    async def defer_if_paused(
        job: JobExecution,
        context: JobContext,
        loaded: _LoadedRoute,
    ) -> dict[str, Any] | None:
        if not loaded.control.global_pause and loaded.route.paused_at is None:
            return None
        deferred_until = now() + timedelta(seconds=max(loaded.route.poll_interval_seconds, 30))
        await _defer_route_job(
            context,
            media_stager,
            route=loaded.route,
            job=job,
            scheduled_for=deferred_until,
        )
        await context.session.commit()
        return {
            "held": True,
            "reason": "global_pause" if loaded.control.global_pause else "route_pause",
            "deferred_until": deferred_until.isoformat(),
        }

    async def initialize_route(job: JobExecution, context: JobContext) -> dict[str, Any]:
        payload = _parse_payload(InitializeJobPayload, job_payload_copy(job))
        loaded = await _load_route(context, payload.route_id, source_registry)
        route = loaded.route
        deferred = await defer_if_paused(job, context, loaded)
        if deferred is not None:
            return deferred
        state = dict(route.cursor_state or {})
        requested_raw = state.get("activation_requested_at")
        if not requested_raw:
            raise PermanentJobError(
                code="activation_boundary_missing",
                message="Telegram route activation boundary is missing",
            )
        try:
            requested_at = datetime.fromisoformat(str(requested_raw).replace("Z", "+00:00"))
        except ValueError:
            raise PermanentJobError(
                code="activation_boundary_invalid",
                message="Telegram route activation boundary is invalid",
            ) from None
        if payload.activation_requested_at is not None and payload.activation_requested_at != requested_at:
            raise PermanentJobError(
                code="activation_changed",
                message="Telegram route activation does not match this initialization job",
            )
        if state.get("status") == "ready":
            return {
                "route_id": str(route.id),
                "cursor": state.get("last_message_id", 0),
                "captured": 0,
                "initialized": True,
            }
        expected_initialization_status = str(state.get("status"))
        if expected_initialization_status not in {"initializing", "catching_up"}:
            raise PermanentJobError(
                code="route_state_changed",
                message="Telegram route is not initializing",
            )
        boundary = requested_at.replace(microsecond=0)
        await context.session.commit()

        captured = 0
        predecessor = state.get("activation_message_id")
        initial_envelopes: list[TelegramEnvelope] = []
        if predecessor is None:
            snapshot_token = state.get("activation_snapshot_token")
            page_token = state.get("activation_page_token")
            seen_page_tokens = list(state.get("activation_seen_page_tokens") or [])
            last_scanned = int(state.get("activation_last_scanned_id") or 0)
            proven = False
            for _ in range(page_budget):
                current_page_token = page_token
                if current_page_token in seen_page_tokens:
                    raise RetryableJobError(
                        code="telegram_activation_token_repeated",
                        message="Telegram activation repeated a page token",
                    )
                result = await loaded.adapter.fetch(
                    _request(
                        loaded,
                        limit=100,
                        snapshot_token=snapshot_token,
                        page_token=page_token,
                    )
                )
                if snapshot_token is not None and result.snapshot_token != snapshot_token:
                    raise RetryableJobError(
                        code="telegram_activation_snapshot_changed",
                        message="Telegram activation snapshot changed during pagination",
                    )
                snapshot_token = result.snapshot_token
                seen_page_tokens.append(current_page_token)
                ordered = sorted(result.envelopes, key=_coordinate, reverse=True)
                if ordered:
                    page_minimum = min(item.anchor_message_id for item in ordered)
                    if last_scanned and page_minimum >= last_scanned:
                        raise RetryableJobError(
                            code="telegram_activation_envelope_no_progress",
                            message="Telegram activation pages made no unique progress",
                        )
                    last_scanned = page_minimum
                boundary_decision = classify_activation_page(
                    ordered,
                    boundary=boundary,
                    complete=result.complete,
                )
                initial_envelopes.extend(boundary_decision.newer)
                if boundary_decision.boundary_proven:
                    predecessor = boundary_decision.predecessor_id
                    proven = True
                    break
                if not ordered:
                    raise RetryableJobError(
                        code="telegram_activation_page_no_progress",
                        message="Telegram activation page made no progress",
                    )
                if result.next_page_token is None:
                    raise RetryableJobError(
                        code="telegram_activation_page_incomplete",
                        message="Telegram source did not provide a complete activation page",
                    )
                if result.next_page_token == current_page_token or result.next_page_token in seen_page_tokens:
                    raise RetryableJobError(
                        code="telegram_activation_token_repeated",
                        message="Telegram activation repeated a page token",
                    )
                page_token = result.next_page_token
            if not proven:
                async with context.session.begin():
                    locked, control = await _lock_route_and_control(context, route.id)
                    pause_reason = _validate_locked_route(
                        locked,
                        control,
                        required_status=expected_initialization_status,
                        activation_requested_at=str(requested_raw),
                    )
                    if pause_reason is not None:
                        deferred_until = now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
                        await _defer_route_job(
                            context,
                            media_stager,
                            route=locked,
                            job=job,
                            scheduled_for=deferred_until,
                        )
                        return {
                            "held": True,
                            "reason": pause_reason,
                            "deferred_until": deferred_until.isoformat(),
                        }
                    locked_state = dict(locked.cursor_state or {})
                    locked_state.update(
                        {
                            "status": "catching_up",
                            "activation_boundary_at": boundary.isoformat(),
                            "activation_snapshot_token": snapshot_token,
                            "activation_page_token": page_token,
                            "activation_seen_page_tokens": seen_page_tokens,
                            "activation_last_scanned_id": last_scanned,
                        }
                    )
                    locked.cursor_state = locked_state
                    await _enqueue_continuation(
                        context,
                        media_stager,
                        route_id=route.id,
                        last_scanned_id=last_scanned,
                        activation_requested_at=str(requested_raw),
                        phase="activation_scan",
                        continuation_state={
                            "activation_requested_at": str(requested_raw),
                            "snapshot_token": snapshot_token,
                            "page_token": page_token,
                            "last_scanned_id": last_scanned,
                        },
                    )
                return {
                    "route_id": str(route.id),
                    "captured": 0,
                    "initialized": False,
                    "continuation_enqueued": True,
                }

            async with context.session.begin():
                locked, control = await _lock_route_and_control(context, route.id)
                pause_reason = _validate_locked_route(
                    locked,
                    control,
                    required_status=expected_initialization_status,
                    activation_requested_at=str(requested_raw),
                )
                if pause_reason is not None:
                    deferred_until = now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
                    await _defer_route_job(
                        context,
                        media_stager,
                        route=locked,
                        job=job,
                        scheduled_for=deferred_until,
                    )
                    return {
                        "held": True,
                        "reason": pause_reason,
                        "deferred_until": deferred_until.isoformat(),
                    }
                locked_state = dict(locked.cursor_state or {})
                locked_state.update(
                    {
                        "status": "catching_up",
                        "activation_boundary_at": boundary.isoformat(),
                        "activation_message_id": int(predecessor),
                        "last_message_id": int(predecessor),
                    }
                )
                locked_state.pop("activation_snapshot_token", None)
                locked_state.pop("activation_page_token", None)
                locked_state.pop("activation_seen_page_tokens", None)
                locked_state.pop("activation_last_scanned_id", None)
                locked.cursor_state = locked_state

            unique_initial = {item.source_key: item for item in initial_envelopes}
            for envelope in sorted(unique_initial.values(), key=_coordinate):
                _, deferred = await _capture(
                    loaded=loaded,
                    envelope=envelope,
                    dispatch_kind="live",
                    job=job,
                    context=context,
                    media_stager=media_stager,
                    activation_requested_at=str(requested_raw),
                    required_status="catching_up",
                    deferred_until=now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
                )
                if deferred is not None:
                    return deferred
                captured += 1

        for _ in range(page_budget):
            cursor = int((route.cursor_state or {}).get("last_message_id") or 0)
            saved_forward = (route.cursor_state or {}).get("initialization_forward")
            base_cursor = int((saved_forward or {}).get("base_after_id", cursor))
            step = await _fetch_forward_step(
                loaded,
                after_id=base_cursor,
                page_budget=page_budget,
                saved_state=saved_forward,
            )
            for envelope in step.envelopes:
                _, deferred = await _capture(
                    loaded=loaded,
                    envelope=envelope,
                    dispatch_kind="live",
                    job=job,
                    context=context,
                    media_stager=media_stager,
                    activation_requested_at=str(requested_raw),
                    required_status="catching_up",
                    deferred_until=now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
                )
                if deferred is not None:
                    return deferred
                captured += 1
            if step.state is not None:
                progress = await _persist_forward_progress(
                    context,
                    media_stager,
                    route_id=route.id,
                    job=job,
                    state_key="initialization_forward",
                    state=step.state,
                    last_scanned_id=step.last_scanned_id,
                    required_status="catching_up",
                    activation_requested_at=str(requested_raw),
                    deferred_until=now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
                )
                progress["captured"] = captured
                return progress
            if not step.envelopes:
                async with context.session.begin():
                    locked, control = await _lock_route_and_control(context, route.id)
                    pause_reason = _validate_locked_route(
                        locked,
                        control,
                        required_status="catching_up",
                        activation_requested_at=str(requested_raw),
                    )
                    if pause_reason is not None:
                        deferred_until = now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
                        await _defer_route_job(
                            context,
                            media_stager,
                            route=locked,
                            job=job,
                            scheduled_for=deferred_until,
                        )
                        return {
                            "held": True,
                            "reason": pause_reason,
                            "deferred_until": deferred_until.isoformat(),
                        }
                    locked_state = dict(locked.cursor_state or {})
                    locked_state.pop("initialization_forward", None)
                    locked_state["status"] = "ready"
                    initialized_at = now()
                    locked_state["initialized_at"] = initialized_at.isoformat()
                    locked.cursor_state = locked_state
                    locked.next_poll_at = initialized_at
                cursor = int((route.cursor_state or {}).get("last_message_id") or 0)
                return {
                    "route_id": str(route.id),
                    "cursor": cursor,
                    "captured": captured,
                    "initialized": True,
                }
            if saved_forward is not None:
                async with context.session.begin():
                    locked, control = await _lock_route_and_control(context, route.id)
                    pause_reason = _validate_locked_route(
                        locked,
                        control,
                        required_status="catching_up",
                        activation_requested_at=str(requested_raw),
                    )
                    if pause_reason is not None:
                        deferred_until = now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
                        await _defer_route_job(
                            context,
                            media_stager,
                            route=locked,
                            job=job,
                            scheduled_for=deferred_until,
                        )
                        return {
                            "held": True,
                            "reason": pause_reason,
                            "deferred_until": deferred_until.isoformat(),
                        }
                    locked_state = dict(locked.cursor_state or {})
                    locked_state.pop("initialization_forward", None)
                    locked.cursor_state = locked_state
        cursor = int((route.cursor_state or {}).get("last_message_id") or 0)
        async with context.session.begin():
            locked, control = await _lock_route_and_control(context, route.id)
            pause_reason = _validate_locked_route(
                locked,
                control,
                required_status="catching_up",
                activation_requested_at=str(requested_raw),
            )
            if pause_reason is not None:
                deferred_until = now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
                await _defer_route_job(
                    context,
                    media_stager,
                    route=locked,
                    job=job,
                    scheduled_for=deferred_until,
                )
                return {
                    "held": True,
                    "reason": pause_reason,
                    "deferred_until": deferred_until.isoformat(),
                }
            await _enqueue_continuation(
                context,
                media_stager,
                route_id=route.id,
                last_scanned_id=cursor,
                activation_requested_at=str(requested_raw),
                phase="catch_up_cycle",
                continuation_state={
                    "activation_requested_at": str(requested_raw),
                    "cursor": cursor,
                    "phase": "catch_up_cycle",
                },
            )
        return {
            "route_id": str(route.id),
            "cursor": cursor,
            "captured": captured,
            "initialized": False,
            "continuation_enqueued": True,
        }

    async def poll_route(job: JobExecution, context: JobContext) -> dict[str, Any]:
        payload = _parse_payload(RouteJobPayload, job_payload_copy(job))
        loaded = await _load_route(context, payload.route_id, source_registry)
        route = loaded.route
        deferred = await defer_if_paused(job, context, loaded)
        if deferred is not None:
            return deferred
        state = dict(route.cursor_state or {})
        if not route.enabled or state.get("status") != "ready" or state.get("last_message_id") is None:
            raise PermanentJobError(
                code="route_not_ready",
                message="Telegram route is not ready for polling",
            )
        expected_activation = state.get("activation_requested_at")
        await context.session.commit()
        saved_forward = state.get("poll_forward")
        base_cursor = int((saved_forward or {}).get("base_after_id", state["last_message_id"]))
        step = await _fetch_forward_step(
            loaded,
            after_id=base_cursor,
            page_budget=page_budget,
            saved_state=saved_forward,
        )
        captured = 0
        filtered = 0
        if not step.envelopes and step.state is not None:
            progress = await _persist_forward_progress(
                context,
                media_stager,
                route_id=route.id,
                job=job,
                state_key="poll_forward",
                state=step.state,
                last_scanned_id=step.last_scanned_id,
                required_status="ready",
                activation_requested_at=expected_activation,
                deferred_until=now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
            )
            progress.update({"captured": captured, "source_edits": 0, "filtered": filtered})
            return progress

        recent = await _fetch_recent(loaded, limit=50)
        fingerprints = dict(state.get("recent_fingerprints") or {})
        edits = []
        for envelope in recent:
            previous = fingerprints.get(str(envelope.anchor_message_id))
            current = telegram_envelope_fingerprint(envelope)
            if previous is not None and previous != current:
                edits.append(envelope)
        source_edits = 0
        for envelope in sorted(edits, key=_coordinate):
            _, deferred = await _capture(
                loaded=loaded,
                envelope=envelope,
                dispatch_kind="source_edit",
                job=job,
                context=context,
                media_stager=media_stager,
                force_review=True,
                activation_requested_at=expected_activation,
                required_status="ready",
                deferred_until=now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
            )
            if deferred is not None:
                return deferred
            source_edits += 1
        for envelope in step.envelopes:
            decision = evaluate_content_filter(
                envelope.text,
                bool(envelope.media),
                route.content_filters or {},
            )
            observed_at = now()
            allowed_at = next_allowed_at(observed_at, route.quiet_hours or {})
            scheduled_for = allowed_at if allowed_at > observed_at else None
            _, deferred = await _capture(
                loaded=loaded,
                envelope=envelope,
                dispatch_kind="live",
                job=job,
                context=context,
                media_stager=media_stager,
                enqueue_process=decision.accepted,
                scheduled_for=scheduled_for,
                filter_reason=decision.reason,
                activation_requested_at=expected_activation,
                required_status="ready",
                deferred_until=now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
            )
            if deferred is not None:
                return deferred
            if decision.accepted:
                captured += 1
            else:
                filtered += 1
        if step.state is not None:
            progress = await _persist_forward_progress(
                context,
                media_stager,
                route_id=route.id,
                job=job,
                state_key="poll_forward",
                state=step.state,
                last_scanned_id=step.last_scanned_id,
                required_status="ready",
                activation_requested_at=expected_activation,
                deferred_until=now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
            )
            progress.update(
                {
                    "captured": captured,
                    "source_edits": source_edits,
                    "filtered": filtered,
                }
            )
            return progress
        async with context.session.begin():
            locked, control = await _lock_route_and_control(context, route.id)
            pause_reason = _validate_locked_route(
                locked,
                control,
                required_status="ready",
                activation_requested_at=expected_activation,
            )
            if pause_reason is not None:
                deferred_until = now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
                await _defer_route_job(
                    context,
                    media_stager,
                    route=locked,
                    job=job,
                    scheduled_for=deferred_until,
                )
                return {
                    "held": True,
                    "reason": pause_reason,
                    "deferred_until": deferred_until.isoformat(),
                }
            locked_state = dict(locked.cursor_state or {})
            locked_state.pop("poll_forward", None)
            locked.cursor_state = locked_state
            locked.last_polled_at = now()
            locked.next_poll_at = locked.last_polled_at + timedelta(seconds=locked.poll_interval_seconds)
        return {"captured": captured, "source_edits": source_edits, "filtered": filtered}

    async def backfill_route(job: JobExecution, context: JobContext) -> dict[str, Any]:
        payload = _parse_payload(BackfillJobPayload, job_payload_copy(job))
        loaded = await _load_route(context, payload.route_id, source_registry)
        deferred = await defer_if_paused(job, context, loaded)
        if deferred is not None:
            return deferred
        cursor = (loaded.route.cursor_state or {}).get("last_message_id")
        expected_activation = (loaded.route.cursor_state or {}).get("activation_requested_at")
        eligibility = evaluate_backfill_eligibility(
            enabled=loaded.route.enabled,
            route_status=(loaded.route.cursor_state or {}).get("status"),
            cursor=int(cursor) if cursor is not None else None,
            since=payload.since,
            now=now(),
        )
        if eligibility.reason == "route_not_initialized":
            raise PermanentJobError(
                code="route_not_initialized",
                message="Telegram route must be initialized before backfill",
            )
        if eligibility.reason == "backfill_since_out_of_range":
            raise PermanentJobError(
                code="backfill_since_out_of_range",
                message="Telegram backfill since must be within the previous 30 days",
            )
        await context.session.commit()
        envelopes = await _fetch_bounded_backfill(
            loaded,
            before_id=int(cursor),
            count=payload.count,
            since=payload.since,
        )
        for envelope in envelopes:
            _, deferred = await _capture(
                loaded=loaded,
                envelope=envelope,
                dispatch_kind="backfill",
                job=job,
                context=context,
                media_stager=media_stager,
                force_review=True,
                activation_requested_at=expected_activation,
                required_status="ready",
                deferred_until=now() + timedelta(seconds=max(loaded.route.poll_interval_seconds, 30)),
            )
            if deferred is not None:
                return deferred
        return {"route_id": str(loaded.route.id), "captured": len(envelopes), "force_review": True}

    async def dry_run_route(job: JobExecution, context: JobContext) -> dict[str, Any]:
        payload = _parse_payload(DryRunJobPayload, job_payload_copy(job))
        loaded = await _load_route(context, payload.route_id, source_registry)
        deferred = await defer_if_paused(job, context, loaded)
        if deferred is not None:
            return deferred
        if not loaded.route.enabled or (loaded.route.cursor_state or {}).get("status") != "ready":
            raise PermanentJobError(
                code="route_not_ready",
                message="Telegram route is not ready for dry run",
            )
        await context.session.commit()
        requested_id = payload.source_message_id
        expected_activation = (loaded.route.cursor_state or {}).get("activation_requested_at")
        result = await loaded.adapter.fetch(
            _request(
                loaded,
                after_id=requested_id - 1 if requested_id is not None else None,
                before_id=requested_id + 1 if requested_id is not None else None,
                limit=1,
            )
        )
        envelope = next(
            (item for item in result.envelopes if requested_id is None or item.anchor_message_id == requested_id),
            None,
        )
        if envelope is None:
            raise PermanentJobError(
                code="dry_run_source_missing",
                message="Telegram dry-run source message was not found",
            )
        dispatch, deferred = await _capture(
            loaded=loaded,
            envelope=envelope,
            dispatch_kind="dry_run",
            job=job,
            context=context,
            media_stager=media_stager,
            force_review=True,
            activation_requested_at=expected_activation,
            required_status="ready",
            dry_run_identity_id=payload.defer_root_job_id or job.id,
            deferred_until=now() + timedelta(seconds=max(loaded.route.poll_interval_seconds, 30)),
        )
        if deferred is not None:
            return deferred
        return {
            "route_id": str(loaded.route.id),
            "dispatch_id": str(dispatch.id),
            "force_review": True,
        }

    return TelegramRouteHandlers(
        initialize=initialize_route,
        poll=poll_route,
        backfill=backfill_route,
        dry_run=dry_run_route,
    )


async def enqueue_telegram_publish_intent(
    session: Any,
    *,
    revision: PlatformVariantRevision,
    destination: Destination,
    dispatch: AutomationDispatch | None = None,
) -> PublishJob:
    """Create the durable publish intent without contacting Telegram.

    Until Task 8 renders destination-specific operations, ``payload_hash`` is the
    exact revision content/evidence hash. Task 9 replaces it with the verified
    rendered-plan hash before any remote dispatch.
    """

    try:
        validate_approvable_revision(revision)
    except RevisionValidationError as exc:
        raise NeedsReviewJobError(
            code="telegram_revision_validation_invalid",
            message=str(exc),
        ) from None

    idempotency_key = f"telegram-publish:{destination.id}:{revision.id}:{revision.content_hash}"
    publish_job = await session.scalar(
        select(PublishJob).where(PublishJob.idempotency_key == idempotency_key).with_for_update()
    )
    if publish_job is None:
        publish_job = PublishJob(
            destination_id=destination.id,
            platform_variant_revision_id=revision.id,
            status="queued",
            idempotency_key=idempotency_key,
            payload_hash=revision.content_hash,
        )
        try:
            async with session.begin_nested():
                session.add(publish_job)
                await session.flush()
        except IntegrityError:
            publish_job = await session.scalar(
                select(PublishJob).where(PublishJob.idempotency_key == idempotency_key).with_for_update()
            )
            if publish_job is None:  # pragma: no cover - unique conflict guarantees it
                raise
    enqueue = await JobRepository(session).enqueue_job(
        job_type="telegram.publish",
        payload={"publish_job_id": str(publish_job.id)},
        idempotency_key=idempotency_key,
        origin=JobOrigin.AUTOMATION,
        pause_sensitive=True,
    )
    publish_job.workflow_job_id = enqueue.job.id
    if dispatch is not None:
        dispatch.publish_job_id = publish_job.id
    session.add(
        WorkflowEvent(
            workflow_job_id=enqueue.job.id,
            event_type="telegram.publish.requested",
            actor="automation",
            event_data=redact_event_data(
                {
                    "publish_job_id": str(publish_job.id),
                    "destination_id": str(destination.id),
                    "revision_id": str(revision.id),
                    "content_hash": revision.content_hash,
                }
            ),
        )
    )
    await session.flush()
    return publish_job


async def _exact_dispatch_evidence(
    session: Any,
    story_revision_id: UUID,
) -> StoryEvidenceSnapshot:
    links = list(
        await session.scalars(
            select(StoryEvidenceLink).where(
                StoryEvidenceLink.story_revision_id == story_revision_id,
                StoryEvidenceLink.claim_key == "telegram.source",
            )
        )
    )
    if len(links) != 1:
        raise NeedsReviewJobError(
            code="telegram_evidence_ambiguous",
            message="Captured Telegram evidence is missing or ambiguous",
        )
    snapshot = await session.get(StoryEvidenceSnapshot, links[0].evidence_snapshot_id)
    if snapshot is None:
        raise NeedsReviewJobError(
            code="telegram_evidence_missing",
            message="Captured Telegram evidence is missing",
        )
    try:
        validate_evidence_snapshot(snapshot)
    except ValueError as exc:
        raise NeedsReviewJobError(
            code="telegram_evidence_invalid",
            message=str(exc),
        ) from None
    return snapshot


async def _dispatch_media(
    session: Any,
    source_item: SourceItem,
    *,
    lock_for_revision: bool = True,
) -> tuple[ContentItem, tuple[MediaAsset, ...]]:
    if source_item.content_item_id is None:
        raise NeedsReviewJobError(
            code="telegram_content_missing",
            message="Captured Telegram content item is missing",
        )
    content_item = await session.get(ContentItem, source_item.content_item_id)
    if content_item is None:
        raise NeedsReviewJobError(
            code="telegram_content_missing",
            message="Captured Telegram content item is missing",
        )
    media_statement = (
        select(MediaAsset)
        .join(ItemMedia, ItemMedia.media_asset_id == MediaAsset.id)
        .where(ItemMedia.content_item_id == content_item.id)
        .order_by(ItemMedia.sort_order, MediaAsset.created_at, MediaAsset.id)
    )
    if lock_for_revision:
        await fence_platform_revision_media_write(session)
        media_statement = media_statement.with_for_update(of=MediaAsset).execution_options(populate_existing=True)
    media = tuple(await session.scalars(media_statement))
    return content_item, media


def _media_decision(route: AutomationRoute, media: tuple[MediaAsset, ...]) -> tuple[list[UUID], bool, str | None]:
    decision = evaluate_media_policy(route.media_policy, media)
    if decision.terminal_reason == "media_expired":
        raise NeedsReviewJobError(
            code="telegram_media_expired",
            message="Captured Telegram media expired before revision persistence",
        )
    return list(decision.media_asset_ids), decision.ready, decision.reason


async def _route_parent_revision(
    session: Any,
    *,
    dispatch: AutomationDispatch,
    story_id: UUID,
) -> PlatformVariantRevision | None:
    return await session.scalar(
        select(PlatformVariantRevision)
        .join(
            AutomationDispatch,
            AutomationDispatch.variant_revision_id == PlatformVariantRevision.id,
        )
        .join(StoryRevision, StoryRevision.id == AutomationDispatch.story_revision_id)
        .where(
            AutomationDispatch.route_id == dispatch.route_id,
            AutomationDispatch.id != dispatch.id,
            AutomationDispatch.variant_revision_id.is_not(None),
            StoryRevision.story_id == story_id,
            AutomationDispatch.creation_sequence < dispatch.creation_sequence,
        )
        .order_by(
            AutomationDispatch.creation_sequence.desc(),
            PlatformVariantRevision.revision_number.desc(),
        )
        .limit(1)
        .execution_options(populate_existing=True)
    )


async def _content_pack_and_variant(
    session: Any,
    *,
    dispatch: AutomationDispatch,
    route: AutomationRoute,
    story_revision: StoryRevision,
    parent: PlatformVariantRevision | None,
) -> tuple[ContentPack, PlatformVariant]:
    if parent is not None:
        variant = await session.scalar(
            select(PlatformVariant).where(PlatformVariant.id == parent.platform_variant_id).with_for_update()
        )
        if variant is None:
            raise NeedsReviewJobError(
                code="telegram_lineage_invalid",
                message="Telegram revision lineage is invalid",
            )
        pack = await session.get(ContentPack, variant.content_pack_id)
        if pack is None:
            raise NeedsReviewJobError(
                code="telegram_lineage_invalid",
                message="Telegram content pack is missing",
            )
        return pack, variant

    pack = await session.scalar(
        select(ContentPack)
        .where(
            ContentPack.story_revision_id == story_revision.id,
            ContentPack.brand_profile_id == route.brand_profile_id,
        )
        .with_for_update()
    )
    if pack is None:
        candidate = ContentPack(
            story_revision_id=story_revision.id,
            brand_profile_id=route.brand_profile_id,
            status="draft",
        )
        try:
            async with session.begin_nested():
                session.add(candidate)
                await session.flush()
            pack = candidate
        except IntegrityError:
            pack = await session.scalar(
                select(ContentPack)
                .where(
                    ContentPack.story_revision_id == story_revision.id,
                    ContentPack.brand_profile_id == route.brand_profile_id,
                )
                .with_for_update()
            )
            if pack is None:  # pragma: no cover
                raise
    variant = await session.scalar(
        select(PlatformVariant)
        .where(
            PlatformVariant.content_pack_id == pack.id,
            PlatformVariant.platform == "telegram",
        )
        .with_for_update()
    )
    if variant is None:
        candidate_variant = PlatformVariant(content_pack_id=pack.id, platform="telegram")
        try:
            async with session.begin_nested():
                session.add(candidate_variant)
                await session.flush()
            variant = candidate_variant
        except IntegrityError:
            variant = await session.scalar(
                select(PlatformVariant)
                .where(
                    PlatformVariant.content_pack_id == pack.id,
                    PlatformVariant.platform == "telegram",
                )
                .with_for_update()
            )
            if variant is None:  # pragma: no cover
                raise
    variant = await session.scalar(select(PlatformVariant).where(PlatformVariant.id == variant.id).with_for_update())
    if variant is None:  # pragma: no cover
        raise RuntimeError("Telegram variant disappeared during allocation")
    return pack, variant


async def _require_automation_variant_write_allowed(session: Any, variant_id: UUID) -> None:
    try:
        await require_revision_write_allowed(session, variant_id=variant_id)
    except RegenerationFenceConflict:
        raise RetryableJobError(
            code="telegram_variant_regeneration_in_progress",
            message="Telegram variant regeneration is in progress",
        ) from None


def _generation_error(exc: Exception, route: AutomationRoute, job: JobExecution) -> Exception:
    if isinstance(exc, OpenRouterRetryableError):
        scheduled = retry_at(
            route.retry_policy or {},
            attempt_number=max(1, job.attempt_count),
            now=datetime.now(UTC),
        )
        if scheduled is None:
            return NeedsReviewJobError(
                code="telegram_generation_retries_exhausted",
                message="Telegram generation requires operator attention",
            )
        return RetryableJobError(code=exc.code, message=str(exc), retry_at=scheduled)
    if isinstance(exc, OpenRouterNeedsReviewError):
        return NeedsReviewJobError(code=exc.code, message=str(exc))
    if isinstance(exc, ValidationError):
        return NeedsReviewJobError(
            code="telegram_generation_output_invalid",
            message="Generated Telegram output failed validation",
        )
    if isinstance(exc, (OpenRouterPermanentError, ProviderProfileConfigurationError)):
        return PermanentJobError(
            code=getattr(exc, "code", "telegram_provider_configuration_invalid"),
            message=str(exc),
        )
    return exc


async def _resolve_process_prompt(
    session: Any,
    *,
    route: AutomationRoute,
    payload: ProcessDispatchPayload,
    workflow_job_id: UUID,
) -> PromptTemplateVersion:
    if payload.prompt_template_version_id is not None:
        prompt = await session.get(
            PromptTemplateVersion,
            payload.prompt_template_version_id,
        )
        if (
            prompt is None
            or prompt.checksum_sha256 != payload.prompt_checksum
            or (route.prompt_policy != "follow_active" and prompt.id != route.prompt_template_version_id)
        ):
            raise NeedsReviewJobError(
                code="telegram_prompt_snapshot_invalid",
                message="Telegram prompt snapshot is missing or changed",
            )
    elif route.prompt_policy == "follow_active":
        templates = list(
            await session.scalars(select(PromptTemplate).where(PromptTemplate.purpose_key == "telegram_rewrite"))
        )
        template_ids = {item.id for item in templates}
        candidates = list(
            await session.scalars(
                select(PromptTemplateVersion).where(
                    PromptTemplateVersion.prompt_template_id.in_(template_ids),
                    PromptTemplateVersion.is_active.is_(True),
                )
            )
        )
        active = [item for item in candidates if item.prompt_template_id in template_ids and item.is_active]
        if len(active) != 1:
            raise NeedsReviewJobError(
                code="telegram_active_prompt_invalid",
                message="Telegram active prompt configuration is invalid",
            )
        prompt = active[0]
    else:
        prompt = await session.get(
            PromptTemplateVersion,
            route.prompt_template_version_id,
        )
        if prompt is None:
            raise PermanentJobError(
                code="telegram_prompt_missing",
                message="Pinned Telegram prompt version was not found",
            )

    if payload.prompt_template_version_id is None:
        stored_job = await session.get(WorkflowJob, workflow_job_id)
        if stored_job is not None:
            stored_job.payload = {
                **dict(stored_job.payload or {}),
                "prompt_template_version_id": str(prompt.id),
                "prompt_checksum": prompt.checksum_sha256,
            }
    return prompt


def build_telegram_process_handler(
    profile_resolver: Any,
    *,
    fault_injector: FaultInjector | None = None,
) -> JobHandler:
    injector = fault_injector if fault_injector is not None else NoopFaultInjector()

    async def _process_route_dispatch(job: JobExecution, context: JobContext) -> dict[str, Any]:
        payload = _parse_payload(ProcessDispatchPayload, job_payload_copy(job))
        workflow_job_id = job.id
        workflow_attempt_count = job.attempt_count
        session = context.session
        provider = None
        provider_request = None
        active_attempt_id: UUID | None = None
        durable_output: dict[str, Any] | None = None

        async with session.begin():
            dispatch = await session.scalar(
                select(AutomationDispatch).where(AutomationDispatch.id == payload.dispatch_id).with_for_update()
            )
            if dispatch is None:
                raise PermanentJobError(
                    code="telegram_dispatch_missing",
                    message="Telegram automation dispatch was not found",
                )
            if dispatch.variant_revision_id is not None:
                return {
                    "dispatch_id": str(dispatch.id),
                    "revision_id": str(dispatch.variant_revision_id),
                    "publish_job_id": str(dispatch.publish_job_id) if dispatch.publish_job_id else None,
                    "idempotent": True,
                }
            route = await session.get(AutomationRoute, dispatch.route_id)
            story_revision = await session.get(StoryRevision, dispatch.story_revision_id)
            source_item = await session.get(SourceItem, dispatch.source_item_id)
            if route is None or story_revision is None or source_item is None:
                raise PermanentJobError(
                    code="telegram_dispatch_context_missing",
                    message="Telegram dispatch context is incomplete",
                )
            if payload.completed_research_run_id is not None:
                from app.research.models import ResearchRun

                completed_run = await session.get(ResearchRun, payload.completed_research_run_id)
                if (
                    completed_run is None
                    or completed_run.status != "succeeded"
                    or completed_run.story_id != story_revision.story_id
                    or completed_run.result_story_revision_id != story_revision.id
                ):
                    raise NeedsReviewJobError(
                        code="telegram_research_continuation_invalid",
                        message="Completed research continuation is invalid",
                    )
            if payload.completed_research_run_id is None and route.research_mode == "manual":
                from app.research.models import ResearchRun

                profile_value = (route.content_filters or {}).get("research_provider_profile_id")
                try:
                    research_profile_id = UUID(str(profile_value))
                except TypeError, ValueError:
                    raise PermanentJobError(
                        code="telegram_research_profile_invalid",
                        message="Telegram research provider profile is invalid",
                    ) from None
                manual_run = await session.scalar(
                    select(ResearchRun)
                    .where(
                        ResearchRun.story_id == story_revision.story_id,
                        ResearchRun.provider_profile_id == research_profile_id,
                        ResearchRun.requested_mode == "manual",
                        ResearchRun.status == "succeeded",
                        ResearchRun.result_story_revision_id.is_not(None),
                        ResearchRun.created_at >= dispatch.created_at,
                    )
                    .order_by(ResearchRun.finished_at.desc(), ResearchRun.id.desc())
                    .limit(1)
                )
                if manual_run is None:
                    dispatch.status = "needs_review"
                    dispatch.error_code = "telegram_manual_research_required"
                    dispatch.error_message = "Manual research is required before generation"
                    session.add(
                        WorkflowEvent(
                            workflow_job_id=job.id,
                            event_type="telegram.research.review_required",
                            actor="automation",
                            event_data=redact_event_data(
                                {
                                    "dispatch_id": str(dispatch.id),
                                    "story_id": str(story_revision.story_id),
                                }
                            ),
                        )
                    )
                    raise NeedsReviewJobError(
                        code="telegram_manual_research_required",
                        message="Manual research is required before generation",
                    )
                selected_revision = await session.get(StoryRevision, manual_run.result_story_revision_id)
                if selected_revision is None or selected_revision.story_id != story_revision.story_id:
                    raise NeedsReviewJobError(
                        code="telegram_manual_research_result_invalid",
                        message="Manual research result revision is invalid",
                    )
                dispatch.story_revision_id = selected_revision.id
                dispatch.status = "captured"
                dispatch.error_code = None
                dispatch.error_message = None
                story_revision = selected_revision
            prompt = await _resolve_process_prompt(
                session,
                route=route,
                payload=payload,
                workflow_job_id=workflow_job_id,
            )
            if payload.completed_research_run_id is None and route.research_mode == "auto_if_incomplete":
                from app.research.service import ResearchRequestError, ResearchService

                profile_value = (route.content_filters or {}).get("research_provider_profile_id")
                try:
                    profile_id = UUID(str(profile_value))
                except TypeError, ValueError:
                    raise PermanentJobError(
                        code="telegram_research_profile_invalid",
                        message="Telegram research provider profile is invalid",
                    ) from None
                continuation = {
                    "job_type": "telegram.route.process",
                    "payload": {
                        "dispatch_id": str(dispatch.id),
                        "force_review": payload.force_review,
                        "prompt_template_version_id": str(prompt.id),
                        "prompt_checksum": prompt.checksum_sha256,
                    },
                    "idempotency_prefix": (f"telegram-route-process-after-research:{dispatch.id}"),
                    "subscriber_id": f"telegram-dispatch:{dispatch.id}",
                    "expected_route_id": str(route.id),
                    "expected_story_id": str(story_revision.story_id),
                    "expected_story_revision_id": str(story_revision.id),
                    "expected_provider_profile_id": str(profile_id),
                    "expected_research_mode": "auto_if_incomplete",
                }
                try:
                    research = await ResearchService(session).request(
                        story_id=story_revision.story_id,
                        mode="auto_if_incomplete",
                        depth="standard",
                        provider_profile_id=profile_id,
                        query_hint=None,
                        continuation=continuation,
                    )
                except ResearchRequestError as exc:
                    raise PermanentJobError(
                        code="telegram_research_request_invalid",
                        message=str(exc),
                    ) from None
                if research.disposition == "enqueued":
                    dispatch.status = "researching"
                    dispatch.error_code = None
                    dispatch.error_message = None
                    return {
                        "dispatch_id": str(dispatch.id),
                        "research_run_id": str(research.run_id),
                        "research_job_id": str(research.job_id),
                    }
            snapshot = await _exact_dispatch_evidence(session, story_revision.id)
            content_item, media = await _dispatch_media(
                session,
                source_item,
                lock_for_revision=False,
            )
            brand = await session.get(BrandProfile, route.brand_profile_id)
            profile = await session.get(AIProviderProfile, route.ai_provider_profile_id)
            destination = await session.get(Destination, route.destination_id)
            if prompt is None or brand is None or profile is None or destination is None:
                raise PermanentJobError(
                    code="telegram_route_configuration_missing",
                    message="Telegram route configuration is incomplete",
                )

            run = (
                await session.get(GenerationRun, dispatch.generation_run_id)
                if dispatch.generation_run_id is not None
                else None
            )
            if run is not None and run.status == "completed" and run.output_payload:
                if generation_input_hash(dict(run.request_payload or {})) != run.input_hash:
                    raise NeedsReviewJobError(
                        code="telegram_generation_input_drift",
                        message="Durable generation input no longer matches its hash",
                    )
                durable_output = dict(run.output_payload)
            else:
                if run is not None and run.status == "running":
                    active_claim = int(
                        ((run.request_payload or {}).get("execution") or {}).get("active_workflow_attempt", 0)
                    )
                    if active_claim == workflow_attempt_count:
                        return {
                            "dispatch_id": str(dispatch.id),
                            "generation_run_id": str(run.id),
                            "already_in_progress": True,
                        }
                    attempts = list(
                        await session.scalars(
                            select(GenerationAttempt)
                            .where(GenerationAttempt.generation_run_id == run.id)
                            .order_by(GenerationAttempt.attempt_number)
                            .with_for_update()
                        )
                    )
                    for stale in attempts:
                        if stale.status == "running":
                            stale.status = "failed"
                            stale.error_class = "retryable"
                            stale.error_code = "stale_generation_attempt"
                            stale.error_message = "Generation attempt lease was superseded"
                            stale.finished_at = datetime.now(UTC)
                else:
                    attempts = (
                        list(
                            await session.scalars(
                                select(GenerationAttempt)
                                .where(GenerationAttempt.generation_run_id == run.id)
                                .order_by(GenerationAttempt.attempt_number)
                                .with_for_update()
                            )
                        )
                        if run is not None
                        else []
                    )

                model_override = (route.content_filters or {}).get("model")
                try:
                    resolved = await profile_resolver.resolve(profile, model_override)
                except Exception as exc:
                    mapped = _generation_error(exc, route, job)
                    if mapped is exc:
                        raise
                    raise mapped from None
                rewrite_input = TelegramRewriteInput(
                    source_text=snapshot.content_text,
                    source_url=snapshot.source_url,
                    source_channel=source_item.external_id_norm or str(route.source_id),
                    language=brand.output_language,
                    direction=content_item.direction or "ltr",
                    attribution_policy=route.attribution_policy,
                    custom_footer=route.custom_footer,
                )
                values = rewrite_input.model_dump(mode="json")
                try:
                    rendered_user = prompt.user_template.format(**values)
                except KeyError, ValueError:
                    raise PermanentJobError(
                        code="telegram_prompt_invalid",
                        message="Telegram prompt template cannot be rendered",
                    ) from None
                requested_model = model_override or profile.default_model
                semantic_request = {
                    "dispatch_id": str(dispatch.id),
                    "route_id": str(route.id),
                    "story_revision_id": str(story_revision.id),
                    "evidence_snapshot_id": str(snapshot.id),
                    "prompt_template_version_id": str(prompt.id),
                    "prompt_checksum": prompt.checksum_sha256,
                    "provider_profile_id": str(profile.id),
                    "requested_model": requested_model,
                    "selected_model": resolved.model,
                }
                request_payload = _redacted_dict(
                    {
                        "semantic": semantic_request,
                        "input": values,
                        "execution": {
                            "active_workflow_job_id": str(workflow_job_id),
                            "active_workflow_attempt": workflow_attempt_count,
                        },
                    }
                )
                computed_input_hash = generation_input_hash(request_payload)
                if computed_input_hash is None:  # pragma: no cover - constructed above
                    raise RuntimeError("Generation input hash could not be computed")
                if run is None:
                    run = GenerationRun(
                        story_revision_id=story_revision.id,
                        provider_profile_id=profile.id,
                        prompt_template_version_id=prompt.id,
                        requested_model=(redact_string(requested_model) if requested_model is not None else None),
                        status="running",
                        input_hash=computed_input_hash,
                        request_payload=request_payload,
                        output_payload={},
                        started_at=datetime.now(UTC),
                    )
                    session.add(run)
                    await session.flush()
                    dispatch.generation_run_id = run.id
                else:
                    existing_hash = generation_input_hash(dict(run.request_payload or {}))
                    if existing_hash != run.input_hash or computed_input_hash != run.input_hash:
                        raise NeedsReviewJobError(
                            code="telegram_generation_input_drift",
                            message="Generation retry input differs from the durable request",
                        )
                    run.status = require_generation_run_transition(run.status, "running")
                    run.error_class = None
                    run.error_code = None
                    run.error_message = None
                    run.finished_at = None
                    if run.requested_model is not None:
                        run.requested_model = redact_string(run.requested_model)
                    run.request_payload = request_payload
                dispatch.status = "generating"
                dispatch.error_code = None
                dispatch.error_message = None
                attempt = GenerationAttempt(
                    generation_run_id=run.id,
                    attempt_number=max((item.attempt_number for item in attempts), default=0) + 1,
                    provider=resolved.provider_type,
                    requested_model=(redact_string(requested_model) if requested_model is not None else None),
                    prompt_snapshot=_redacted_dict(
                        {
                            "system": prompt.system_template,
                            "user": rendered_user,
                            "schema": prompt.output_schema,
                        }
                    ),
                    response_payload={},
                    usage={},
                    validation_errors=[],
                    status="running",
                    started_at=datetime.now(UTC),
                )
                session.add(attempt)
                await session.flush()
                run.request_payload = _redacted_dict(
                    {
                        **request_payload,
                        "execution": {
                            **request_payload["execution"],
                            "active_generation_attempt_id": str(attempt.id),
                        },
                    }
                )
                active_attempt_id = attempt.id
                provider = resolved.provider
                provider_request = GenerationProviderRequest(
                    run_id=run.id,
                    purpose="telegram_rewrite",
                    requested_model=resolved.model,
                    messages=(
                        ProviderMessage(role="system", content=prompt.system_template),
                        ProviderMessage(role="user", content=rendered_user),
                    ),
                    response_schema=dict(prompt.output_schema or {}),
                    metadata={
                        "dispatch_id": str(dispatch.id),
                        "route_id": str(route.id),
                        "evidence_snapshot_id": str(snapshot.id),
                        "provider_profile_id": str(profile.id),
                    },
                )

        if durable_output is None:
            if provider is None or provider_request is None or active_attempt_id is None:
                raise RuntimeError("Telegram generation attempt was not prepared")
            try:
                generated = await provider.generate(provider_request)
                await injector.hit(
                    "telegram_process.after_provider_before_persist",
                    {
                        "workflow_job_id": str(workflow_job_id),
                        "dispatch_id": str(payload.dispatch_id),
                        "generation_attempt_id": str(active_attempt_id),
                    },
                )
                parsed_output = TelegramRewriteOutput.model_validate(generated.output).model_dump(mode="json")
                durable_output = _redacted_dict(
                    {
                        "provider": generated.provider,
                        "requested_model": generated.requested_model,
                        "resolved_model": generated.resolved_model,
                        "output": parsed_output,
                        "raw_text": generated.raw_text,
                        "usage": generated.usage,
                        "finish_reason": generated.finish_reason,
                    }
                )
            except Exception as exc:
                async with session.begin():
                    current_dispatch = await session.scalar(
                        select(AutomationDispatch)
                        .where(AutomationDispatch.id == payload.dispatch_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    current_run = (
                        await session.scalar(
                            select(GenerationRun)
                            .where(GenerationRun.id == current_dispatch.generation_run_id)
                            .with_for_update()
                            .execution_options(populate_existing=True)
                        )
                        if current_dispatch is not None and current_dispatch.generation_run_id
                        else None
                    )
                    current_attempt = await session.scalar(
                        select(GenerationAttempt)
                        .where(GenerationAttempt.id == active_attempt_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if current_run is not None and current_attempt is not None:
                        if current_dispatch.variant_revision_id is not None or (
                            (current_run.request_payload or {}).get("execution") or {}
                        ).get("active_generation_attempt_id") != str(active_attempt_id):
                            return {
                                "dispatch_id": str(payload.dispatch_id),
                                "generation_run_id": str(current_run.id),
                                "superseded": True,
                            }
                        mapped = _generation_error(exc, route, job)
                        error_class = (
                            "retryable"
                            if isinstance(mapped, RetryableJobError)
                            else "needs_review"
                            if isinstance(mapped, NeedsReviewJobError)
                            else "permanent"
                        )
                        durable_error_code = redact_string(str(getattr(mapped, "code", "generation_failed")))
                        durable_error_message = redact_string(str(mapped))
                        current_attempt.status = "failed"
                        current_attempt.error_class = error_class
                        current_attempt.error_code = durable_error_code
                        current_attempt.error_message = durable_error_message
                        if isinstance(exc, ValidationError):
                            current_attempt.validation_errors = _redacted_list(
                                [
                                    {
                                        "type": item["type"],
                                        "loc": [str(part) for part in item["loc"]],
                                        "message": item["msg"],
                                    }
                                    for item in exc.errors(
                                        include_input=False,
                                        include_url=False,
                                    )
                                ]
                            )
                        current_attempt.finished_at = datetime.now(UTC)
                        current_run.status = require_generation_run_transition(current_run.status, "failed")
                        current_run.error_class = error_class
                        current_run.error_code = durable_error_code
                        current_run.error_message = durable_error_message
                        current_run.finished_at = datetime.now(UTC)
                        if current_dispatch is not None:
                            current_dispatch.status = "needs_review" if error_class == "needs_review" else "failed"
                mapped = _generation_error(exc, route, job)
                if mapped is exc:
                    raise
                raise mapped from None

            async with session.begin():
                current_run = await session.scalar(
                    select(GenerationRun)
                    .where(GenerationRun.id == provider_request.run_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                current_attempt = await session.scalar(
                    select(GenerationAttempt)
                    .where(GenerationAttempt.id == active_attempt_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if current_run is None or current_attempt is None:
                    raise RetryableJobError(
                        code="generation_attempt_missing",
                        message="Generation attempt disappeared before persistence",
                    )
                if ((current_run.request_payload or {}).get("execution") or {}).get(
                    "active_generation_attempt_id"
                ) != str(active_attempt_id):
                    return {
                        "dispatch_id": str(payload.dispatch_id),
                        "generation_run_id": str(current_run.id),
                        "superseded": True,
                    }
                current_attempt.response_payload = _redacted_dict(durable_output)
                current_attempt.resolved_model = durable_output["resolved_model"]
                current_attempt.usage = _redacted_dict(durable_output["usage"])
                current_attempt.validation_errors = []
                current_attempt.status = "completed"
                current_attempt.finished_at = datetime.now(UTC)
                current_run.output_payload = _redacted_dict(durable_output)
                current_run.status = require_generation_run_transition(current_run.status, "completed")
                current_run.finished_at = datetime.now(UTC)
                current_run.error_class = None
                current_run.error_code = None
                current_run.error_message = None
                session.add(
                    WorkflowEvent(
                        workflow_job_id=workflow_job_id,
                        event_type="telegram.generation.completed",
                        actor="automation",
                        event_data=redact_event_data(
                            {
                                "dispatch_id": str(payload.dispatch_id),
                                "generation_run_id": str(current_run.id),
                                "generation_attempt_id": str(current_attempt.id),
                                "resolved_model": current_attempt.resolved_model,
                                "usage": current_attempt.usage,
                            }
                        ),
                    )
                )

        async with session.begin():
            session.expire_all()
            dispatch = await session.scalar(
                select(AutomationDispatch)
                .where(AutomationDispatch.id == payload.dispatch_id)
                .execution_options(populate_existing=True)
            )
            if dispatch is None:
                raise PermanentJobError(
                    code="telegram_dispatch_missing",
                    message="Telegram automation dispatch was not found",
                )
            if dispatch.variant_revision_id is not None:
                return {
                    "dispatch_id": str(dispatch.id),
                    "revision_id": str(dispatch.variant_revision_id),
                    "publish_job_id": str(dispatch.publish_job_id) if dispatch.publish_job_id else None,
                    "idempotent": True,
                }
            run = await session.scalar(
                select(GenerationRun)
                .where(GenerationRun.id == dispatch.generation_run_id)
                .execution_options(populate_existing=True)
            )
            if run is None or run.status != "completed" or not run.output_payload:
                raise RetryableJobError(
                    code="generation_output_not_durable",
                    message="Generation output is not yet durable",
                )
            attempt = await session.scalar(
                select(GenerationAttempt)
                .where(
                    GenerationAttempt.generation_run_id == run.id,
                    GenerationAttempt.status == "completed",
                )
                .order_by(GenerationAttempt.attempt_number.desc())
                .limit(1)
            )
            if attempt is None:
                raise RetryableJobError(
                    code="generation_attempt_not_durable",
                    message="Generation attempt is not yet durable",
                )
            route = await session.scalar(
                select(AutomationRoute)
                .where(AutomationRoute.id == dispatch.route_id)
                .execution_options(populate_existing=True)
            )
            story_revision = await session.get(StoryRevision, dispatch.story_revision_id)
            source_item = await session.get(SourceItem, dispatch.source_item_id)
            if route is None or story_revision is None or source_item is None:
                raise PermanentJobError(
                    code="telegram_dispatch_context_missing",
                    message="Telegram dispatch context is incomplete",
                )
            provisional_dispatch_identity = (
                dispatch.route_id,
                dispatch.story_revision_id,
                dispatch.source_item_id,
                dispatch.generation_run_id,
                dispatch.creation_sequence,
                dispatch.dispatch_kind,
            )
            provisional_route_brand_profile_id = route.brand_profile_id
            unresolved_earlier = await session.scalar(
                select(AutomationDispatch)
                .join(StoryRevision, StoryRevision.id == AutomationDispatch.story_revision_id)
                .where(
                    AutomationDispatch.route_id == dispatch.route_id,
                    AutomationDispatch.id != dispatch.id,
                    AutomationDispatch.creation_sequence < dispatch.creation_sequence,
                    AutomationDispatch.variant_revision_id.is_(None),
                    AutomationDispatch.status.in_(("captured", "researching", "generating", "retryable")),
                    StoryRevision.story_id == story_revision.story_id,
                )
                .order_by(AutomationDispatch.creation_sequence)
                .limit(1)
            )
            if unresolved_earlier is not None:
                scheduled = retry_at(
                    route.retry_policy or {},
                    attempt_number=max(1, workflow_attempt_count),
                    now=datetime.now(UTC),
                )
                if scheduled is None:
                    raise NeedsReviewJobError(
                        code="telegram_route_lineage_blocked",
                        message="An earlier route dispatch requires operator attention",
                    )
                raise RetryableJobError(
                    code="telegram_route_lineage_waiting",
                    message="Waiting for an earlier route dispatch revision",
                    retry_at=scheduled,
                )
            parent = await _route_parent_revision(
                session,
                dispatch=dispatch,
                story_id=story_revision.story_id,
            )
            _, variant = await _content_pack_and_variant(
                session,
                dispatch=dispatch,
                route=route,
                story_revision=story_revision,
                parent=parent,
            )
            locked_dispatch = await session.scalar(
                select(AutomationDispatch)
                .where(AutomationDispatch.id == payload.dispatch_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if locked_dispatch is None:
                raise PermanentJobError(
                    code="telegram_dispatch_missing",
                    message="Telegram automation dispatch was not found",
                )
            if locked_dispatch.variant_revision_id is not None:
                return {
                    "dispatch_id": str(locked_dispatch.id),
                    "revision_id": str(locked_dispatch.variant_revision_id),
                    "publish_job_id": (str(locked_dispatch.publish_job_id) if locked_dispatch.publish_job_id else None),
                    "idempotent": True,
                }
            if (
                locked_dispatch.route_id,
                locked_dispatch.story_revision_id,
                locked_dispatch.source_item_id,
                locked_dispatch.generation_run_id,
                locked_dispatch.creation_sequence,
                locked_dispatch.dispatch_kind,
            ) != provisional_dispatch_identity:
                raise NeedsReviewJobError(
                    code="telegram_dispatch_identity_drift",
                    message="Telegram dispatch identity changed before revision persistence",
                )
            dispatch = locked_dispatch
            locked_route = await session.scalar(
                select(AutomationRoute)
                .where(AutomationRoute.id == dispatch.route_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if locked_route is None:
                raise PermanentJobError(
                    code="telegram_route_missing",
                    message="Telegram automation route was not found",
                )
            if locked_route.brand_profile_id != provisional_route_brand_profile_id:
                raise NeedsReviewJobError(
                    code="telegram_route_identity_drift",
                    message="Telegram route identity changed before revision persistence",
                )
            route = locked_route
            refreshed_parent = await _route_parent_revision(
                session,
                dispatch=dispatch,
                story_id=story_revision.story_id,
            )
            if refreshed_parent is not None and refreshed_parent.platform_variant_id != variant.id:
                raise RetryableJobError(
                    code="telegram_route_lineage_changed",
                    message="Telegram route lineage changed before revision persistence",
                )
            if refreshed_parent is None and parent is not None:
                raise NeedsReviewJobError(
                    code="telegram_route_lineage_invalid",
                    message="Telegram route lineage disappeared before revision persistence",
                )
            parent = refreshed_parent
            control = await session.scalar(
                select(AutomationControl)
                .where(AutomationControl.id == "global")
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            destination = await session.scalar(
                select(Destination)
                .where(Destination.id == route.destination_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if destination is None:
                raise PermanentJobError(
                    code="telegram_destination_missing",
                    message="Telegram destination was not found",
                )
            snapshot = await _exact_dispatch_evidence(session, story_revision.id)
            evidence_map = build_evidence_map(snapshot)
            content_item, media = await _dispatch_media(session, source_item)
            media_ids, media_ready, media_reason = _media_decision(route, media)
            output = TelegramRewriteOutput.model_validate(run.output_payload["output"])
            content = TelegramVariantContent(
                body=output.body,
                parse_mode=output.parse_mode,
                buttons=output.buttons,
                source_item_id=dispatch.source_item_id,
                source_url=source_item.source_url,
                media_policy=route.media_policy,
                media_asset_ids=media_ids if route.media_policy == "preserve" else [],
                direction=content_item.direction or "ltr",
                dry_run=dispatch.dispatch_kind == "dry_run",
            ).model_dump(mode="json")
            validation_results = [
                {"gate": "telegram_schema", "ok": True, "reason": None},
                {"gate": "evidence", "ok": True, "reason": None},
                {"gate": "media", "ok": media_ready, "reason": media_reason},
            ]
            await _require_automation_variant_write_allowed(session, variant.id)
            revision_number = (
                int(
                    await session.scalar(
                        select(func.coalesce(func.max(PlatformVariantRevision.revision_number), 0)).where(
                            PlatformVariantRevision.platform_variant_id == variant.id
                        )
                    )
                    or 0
                )
                + 1
            )
            gate = evaluate_auto_publish(
                global_pause=bool(control and control.global_pause),
                global_dry_run=bool(control and control.dry_run),
                route_paused=route.paused_at is not None,
                destination_enabled=destination.enabled,
                destination_health=destination.health_status,
                validation_ok=True,
                evidence_ready=True,
                media_ready=media_ready,
            )
            review = evaluate_review_policy(
                publishing_policy=route.publishing_policy,
                explicit_force_review=payload.force_review,
                dispatch_kind=dispatch.dispatch_kind,
                media_policy=route.media_policy,
                auto_publish_allowed=gate.allowed,
                auto_publish_reason=gate.reason,
            )
            revision = PlatformVariantRevision(
                platform_variant_id=variant.id,
                parent_revision_id=parent.id if parent is not None else None,
                generation_attempt_id=attempt.id,
                revision_number=revision_number,
                content=content,
                content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
                evidence_map=evidence_map,
                validation_results=validation_results,
                approval_state="approved" if review.approved else "pending_review",
                approval_note=review.note,
                approved_at=datetime.now(UTC) if review.approved else None,
                created_by=f"automation:{route.id}",
            )
            session.add(revision)
            await session.flush()
            dispatch.variant_revision_id = revision.id
            dispatch.status = "approved" if review.approved else "pending_review"
            dispatch.error_code = None
            dispatch.error_message = None
            publish_job = None
            if review.approved:
                publish_job = await enqueue_telegram_publish_intent(
                    session,
                    revision=revision,
                    destination=destination,
                    dispatch=dispatch,
                )
            session.add(
                WorkflowEvent(
                    workflow_job_id=workflow_job_id,
                    event_type=(
                        "telegram.revision.auto_approved"
                        if review.approved
                        else "telegram.revision.review_required"
                    ),
                    actor="automation",
                    event_data=redact_event_data(
                        {
                            "route_id": str(route.id),
                            "dispatch_id": str(dispatch.id),
                            "revision_id": str(revision.id),
                            "content_hash": revision.content_hash,
                            "reason": None if review.approved else revision.approval_note,
                        }
                    ),
                )
            )
            if dispatch.dispatch_kind == "source_edit":
                session.add(
                    WorkflowEvent(
                        workflow_job_id=workflow_job_id,
                        event_type="telegram.source_edit.revision_created",
                        actor="automation",
                        event_data=redact_event_data(
                            {
                                "route_id": str(route.id),
                                "dispatch_id": str(dispatch.id),
                                "revision_id": str(revision.id),
                                "parent_revision_id": (
                                    str(revision.parent_revision_id) if revision.parent_revision_id else None
                                ),
                            }
                        ),
                    )
                )
            await session.flush()
            return {
                "dispatch_id": str(dispatch.id),
                "generation_run_id": str(run.id),
                "revision_id": str(revision.id),
                "review_required": not review.approved,
                "publish_job_id": str(publish_job.id) if publish_job is not None else None,
            }

    async def process_route_dispatch(job: JobExecution, context: JobContext) -> dict[str, Any]:
        workflow_job_id = job.id
        failure_payload = job_payload_copy(job)
        try:
            return await _process_route_dispatch(job, context)
        except (RetryableJobError, NeedsReviewJobError, PermanentJobError) as exc:
            session = context.session
            if session.in_transaction():
                await session.rollback()
            try:
                payload = ProcessDispatchPayload.model_validate(failure_payload)
            except ValidationError:
                raise exc from None
            async with session.begin():
                dispatch = await session.scalar(
                    select(AutomationDispatch).where(AutomationDispatch.id == payload.dispatch_id).with_for_update()
                )
                if dispatch is not None and dispatch.variant_revision_id is None:
                    dispatch.status = (
                        "needs_review"
                        if isinstance(exc, NeedsReviewJobError)
                        else "retryable"
                        if isinstance(exc, RetryableJobError)
                        else "failed"
                    )
                    dispatch.error_code = redact_string(exc.code)
                    dispatch.error_message = redact_string(exc.message)
                    event_type = (
                        "telegram.process.deferred"
                        if exc.code == "telegram_route_lineage_waiting"
                        else "telegram.process.blocked"
                        if exc.code == "telegram_route_lineage_blocked"
                        else "telegram.generation.failed"
                    )
                    session.add(
                        WorkflowEvent(
                            workflow_job_id=workflow_job_id,
                            event_type=event_type,
                            actor="automation",
                            event_data=redact_event_data(
                                {
                                    "dispatch_id": str(dispatch.id),
                                    "error_class": (
                                        "needs_review"
                                        if isinstance(exc, NeedsReviewJobError)
                                        else "retryable"
                                        if isinstance(exc, RetryableJobError)
                                        else "permanent"
                                    ),
                                    "error_code": exc.code,
                                    "error_message": exc.message,
                                }
                            ),
                        )
                    )
            raise

    return process_route_dispatch


async def process_route_dispatch(
    job: JobExecution,
    context: JobContext,
    *,
    profile_resolver: Any,
) -> dict[str, Any]:
    """Direct-call facade used by tests and dependency-specific runtimes."""

    return await build_telegram_process_handler(profile_resolver)(job, context)
