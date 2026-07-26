from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from app.automations.telegram.contracts import (
    TelegramEnvelope,
    telegram_envelope_fingerprint,
)
from app.automations.telegram.decisions import (
    classify_activation_page,
    evaluate_backfill_eligibility,
)
from app.automations.telegram.handler_contracts import (
    BackfillJobPayload,
    DryRunJobPayload,
    InitializeJobPayload,
    RouteJobPayload,
    TelegramRouteHandlers,
    _LoadedRoute,
    _parse_payload,
)
from app.automations.telegram.registry import TelegramSourceRegistry
from app.automations.telegram.route_fetch import (
    _capture,
    _coordinate,
    _defer_route_job,
    _enqueue_continuation,
    _fetch_bounded_backfill,
    _fetch_forward_step,
    _fetch_recent,
    _load_route,
    _lock_route_and_control,
    _persist_forward_progress,
    _request,
    _validate_locked_route,
)
from app.automations.telegram.route_policy import evaluate_content_filter, next_allowed_at
from app.jobs.errors import PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext, JobHandler
from app.jobs.types import JobExecution, job_payload_copy

logger = logging.getLogger(__name__)


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
    deferred = await _defer_if_paused(job, context, loaded, dependencies=dependencies)
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
            if predecessor is None:
                predecessor = 0
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
    deferred = await _defer_if_paused(job, context, loaded, dependencies=dependencies)
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
    saved_forward_value = state.get("poll_forward")
    saved_forward = saved_forward_value if isinstance(saved_forward_value, dict) else None
    base_cursor_value = (saved_forward or {}).get("base_after_id", state["last_message_id"])
    if not isinstance(base_cursor_value, int):
        raise PermanentJobError(code="route_cursor_invalid", message="Telegram route cursor is invalid")
    base_cursor = base_cursor_value
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
    deferred = await _defer_if_paused(job, context, loaded, dependencies=dependencies)
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
    if cursor is None:
        raise PermanentJobError(
            code="route_not_initialized",
            message="Telegram route must be initialized before backfill",
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
    deferred = await _defer_if_paused(job, context, loaded, dependencies=dependencies)
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
