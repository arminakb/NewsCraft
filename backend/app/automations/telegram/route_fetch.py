from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.automations.models import AutomationRoute, TelegramSourceConfig
from app.automations.telegram.contracts import (
    TelegramEnvelope,
    TelegramFetchRequest,
)
from app.automations.telegram.handler_contracts import (
    _ForwardStep,
    _LoadedRoute,
)
from app.automations.telegram.registry import TelegramSourceRegistry
from app.db.models import Source
from app.jobs.errors import PermanentJobError, RetryableJobError
from app.jobs.models import AutomationControl
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin, job_payload_copy

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
    repository: JobRepository | None = None,
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
                    repository=repository,
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
                    automation_run_id=job.automation_run_id,
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


def _job_repository(context: JobContext, repository: JobRepository | None) -> JobRepository:
    """Resolve the queue writer for route continuations.

    Callers pass the repository explicitly; ``None`` means "use the one that
    belongs to this job's session".
    """

    return repository if repository is not None else JobRepository(context.session)


async def _enqueue_continuation(
    context: JobContext,
    *,
    repository: JobRepository | None = None,
    route_id: UUID,
    last_scanned_id: int,
    activation_requested_at: str,
    phase: str,
    continuation_state: dict[str, Any],
):
    repository = _job_repository(context, repository)
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
    *,
    repository: JobRepository | None = None,
    route: AutomationRoute,
    job: JobExecution,
    scheduled_for: datetime,
) -> None:
    repository = _job_repository(context, repository)
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
    *,
    repository: JobRepository | None = None,
    route_id: UUID,
    job: JobExecution,
    state: dict[str, Any],
    last_scanned_id: int,
) -> None:
    if job.job_type == "telegram.route.initialize":
        activation_requested_at = str(state["activation_requested_at"])
        await _enqueue_continuation(
            context,
            repository=repository,
            route_id=route_id,
            last_scanned_id=last_scanned_id,
            activation_requested_at=activation_requested_at,
            phase=str(state["phase"]),
            continuation_state=state,
        )
        return
    repository = _job_repository(context, repository)
    digest = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    await repository.enqueue_job(
        job_type=job.job_type,
        payload=job_payload_copy(job),
        idempotency_key=f"telegram-route-poll-forward:{route_id}:{digest}",
        origin=JobOrigin.AUTOMATION,
    )


async def _persist_forward_progress(
    context: JobContext,
    *,
    repository: JobRepository | None = None,
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
                repository=repository,
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
            repository=repository,
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
        current_token: str | None = page_token
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
        current_token: str | None = page_token
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
