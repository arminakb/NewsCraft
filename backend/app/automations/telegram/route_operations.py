from __future__ import annotations

# ruff: noqa: F401
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
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
from app.automations.telegram.handler_contracts import (
    BackfillJobPayload,
    DryRunJobPayload,
    InitializeJobPayload,
    ProcessDispatchPayload,
    RouteJobPayload,
    TelegramRouteHandlers,
    _ForwardStep,
    _LoadedRoute,
    _parse_payload,
    _redacted_dict,
    _redacted_list,
    build_evidence_map,
    generation_input_hash,
    sha256_canonical,
    validate_evidence_snapshot,
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


@dataclass(frozen=True, slots=True)
class TelegramRouteDependencies:
    source_registry: TelegramSourceRegistry
    media_stager: Any
    page_budget: int
    clock: Callable[[], datetime]

    def now(self) -> datetime:
        return self.clock()


async def _defer_if_paused(
    job: JobExecution,
    context: JobContext,
    loaded: _LoadedRoute,
    *,
    dependencies: TelegramRouteDependencies,
) -> dict[str, Any] | None:
    if not loaded.control.global_pause and loaded.route.paused_at is None:
        return None
    deferred_until = dependencies.now() + timedelta(seconds=max(loaded.route.poll_interval_seconds, 30))
    await _defer_route_job(
        context,
        dependencies.media_stager,
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


async def initialize_route(
    job: JobExecution,
    context: JobContext,
    *,
    dependencies: TelegramRouteDependencies,
) -> dict[str, Any]:
    payload = _parse_payload(InitializeJobPayload, job_payload_copy(job))
    loaded = await _load_route(context, payload.route_id, dependencies.source_registry)
    route = loaded.route
    deferred = await _defer_if_paused(
        job, context, loaded, dependencies=dependencies
    )
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
        for _ in range(dependencies.page_budget):
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
                    deferred_until = dependencies.now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
                    await _defer_route_job(
                        context,
                        dependencies.media_stager,
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
                    dependencies.media_stager,
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
                deferred_until = dependencies.now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
                await _defer_route_job(
                    context,
                    dependencies.media_stager,
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
                media_stager=dependencies.media_stager,
                activation_requested_at=str(requested_raw),
                required_status="catching_up",
                deferred_until=dependencies.now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
            )
            if deferred is not None:
                return deferred
            captured += 1

    for _ in range(dependencies.page_budget):
        cursor = int((route.cursor_state or {}).get("last_message_id") or 0)
        saved_forward = (route.cursor_state or {}).get("initialization_forward")
        base_cursor = int((saved_forward or {}).get("base_after_id", cursor))
        step = await _fetch_forward_step(
            loaded,
            after_id=base_cursor,
            page_budget=dependencies.page_budget,
            saved_state=saved_forward,
        )
        for envelope in step.envelopes:
            _, deferred = await _capture(
                loaded=loaded,
                envelope=envelope,
                dispatch_kind="live",
                job=job,
                context=context,
                media_stager=dependencies.media_stager,
                activation_requested_at=str(requested_raw),
                required_status="catching_up",
                deferred_until=dependencies.now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
            )
            if deferred is not None:
                return deferred
            captured += 1
        if step.state is not None:
            progress = await _persist_forward_progress(
                context,
                dependencies.media_stager,
                route_id=route.id,
                job=job,
                state_key="initialization_forward",
                state=step.state,
                last_scanned_id=step.last_scanned_id,
                required_status="catching_up",
                activation_requested_at=str(requested_raw),
                deferred_until=dependencies.now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
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
                    deferred_until = dependencies.now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
                    await _defer_route_job(
                        context,
                        dependencies.media_stager,
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
                initialized_at = dependencies.now()
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
                    deferred_until = dependencies.now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
                    await _defer_route_job(
                        context,
                        dependencies.media_stager,
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
            deferred_until = dependencies.now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
            await _defer_route_job(
                context,
                dependencies.media_stager,
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
            dependencies.media_stager,
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


async def poll_route(
    job: JobExecution,
    context: JobContext,
    *,
    dependencies: TelegramRouteDependencies,
) -> dict[str, Any]:
    payload = _parse_payload(RouteJobPayload, job_payload_copy(job))
    loaded = await _load_route(context, payload.route_id, dependencies.source_registry)
    route = loaded.route
    deferred = await _defer_if_paused(
        job, context, loaded, dependencies=dependencies
    )
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
        page_budget=dependencies.page_budget,
        saved_state=saved_forward,
    )
    captured = 0
    filtered = 0
    if not step.envelopes and step.state is not None:
        progress = await _persist_forward_progress(
            context,
            dependencies.media_stager,
            route_id=route.id,
            job=job,
            state_key="poll_forward",
            state=step.state,
            last_scanned_id=step.last_scanned_id,
            required_status="ready",
            activation_requested_at=expected_activation,
            deferred_until=dependencies.now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
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
            media_stager=dependencies.media_stager,
            force_review=True,
            activation_requested_at=expected_activation,
            required_status="ready",
            deferred_until=dependencies.now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
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
        observed_at = dependencies.now()
        allowed_at = next_allowed_at(observed_at, route.quiet_hours or {})
        scheduled_for = allowed_at if allowed_at > observed_at else None
        _, deferred = await _capture(
            loaded=loaded,
            envelope=envelope,
            dispatch_kind="live",
            job=job,
            context=context,
            media_stager=dependencies.media_stager,
            enqueue_process=decision.accepted,
            scheduled_for=scheduled_for,
            filter_reason=decision.reason,
            activation_requested_at=expected_activation,
            required_status="ready",
            deferred_until=dependencies.now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
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
            dependencies.media_stager,
            route_id=route.id,
            job=job,
            state_key="poll_forward",
            state=step.state,
            last_scanned_id=step.last_scanned_id,
            required_status="ready",
            activation_requested_at=expected_activation,
            deferred_until=dependencies.now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
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
            deferred_until = dependencies.now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
            await _defer_route_job(
                context,
                dependencies.media_stager,
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
        locked.last_polled_at = dependencies.now()
        locked.next_poll_at = locked.last_polled_at + timedelta(seconds=locked.poll_interval_seconds)
    return {"captured": captured, "source_edits": source_edits, "filtered": filtered}


async def backfill_route(
    job: JobExecution,
    context: JobContext,
    *,
    dependencies: TelegramRouteDependencies,
) -> dict[str, Any]:
    payload = _parse_payload(BackfillJobPayload, job_payload_copy(job))
    loaded = await _load_route(context, payload.route_id, dependencies.source_registry)
    deferred = await _defer_if_paused(
        job, context, loaded, dependencies=dependencies
    )
    if deferred is not None:
        return deferred
    cursor = (loaded.route.cursor_state or {}).get("last_message_id")
    expected_activation = (loaded.route.cursor_state or {}).get("activation_requested_at")
    eligibility = evaluate_backfill_eligibility(
        enabled=loaded.route.enabled,
        route_status=(loaded.route.cursor_state or {}).get("status"),
        cursor=int(cursor) if cursor is not None else None,
        since=payload.since,
        now=dependencies.now(),
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
            media_stager=dependencies.media_stager,
            force_review=True,
            activation_requested_at=expected_activation,
            required_status="ready",
            deferred_until=dependencies.now() + timedelta(seconds=max(loaded.route.poll_interval_seconds, 30)),
        )
        if deferred is not None:
            return deferred
    return {"route_id": str(loaded.route.id), "captured": len(envelopes), "force_review": True}


async def dry_run_route(
    job: JobExecution,
    context: JobContext,
    *,
    dependencies: TelegramRouteDependencies,
) -> dict[str, Any]:
    payload = _parse_payload(DryRunJobPayload, job_payload_copy(job))
    loaded = await _load_route(context, payload.route_id, dependencies.source_registry)
    deferred = await _defer_if_paused(
        job, context, loaded, dependencies=dependencies
    )
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
        media_stager=dependencies.media_stager,
        force_review=True,
        activation_requested_at=expected_activation,
        required_status="ready",
        dry_run_identity_id=payload.defer_root_job_id or job.id,
        deferred_until=dependencies.now() + timedelta(seconds=max(loaded.route.poll_interval_seconds, 30)),
    )
    if deferred is not None:
        return deferred
    return {
        "route_id": str(loaded.route.id),
        "dispatch_id": str(dispatch.id),
        "force_review": True,
    }


def _bound_handler(operation: Callable[..., Any], dependencies: TelegramRouteDependencies) -> JobHandler:
    handler = partial(operation, dependencies=dependencies)
    handler.__annotations__ = {
        "job": JobExecution,
        "context": JobContext,
        "return": dict[str, Any],
    }
    return handler


def build_telegram_route_handlers(
    source_registry: TelegramSourceRegistry,
    media_stager: Any,
    *,
    page_budget: int = 10,
    clock: Callable[[], datetime] | None = None,
) -> TelegramRouteHandlers:
    if page_budget <= 0:
        raise ValueError("page_budget must be positive")
    dependencies = TelegramRouteDependencies(
        source_registry=source_registry,
        media_stager=media_stager,
        page_budget=page_budget,
        clock=clock or (lambda: datetime.now(UTC)),
    )
    return TelegramRouteHandlers(
        initialize=_bound_handler(initialize_route, dependencies),
        poll=_bound_handler(poll_route, dependencies),
        backfill=_bound_handler(backfill_route, dependencies),
        dry_run=_bound_handler(dry_run_route, dependencies),
    )

