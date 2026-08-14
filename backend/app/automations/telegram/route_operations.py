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
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, job_payload_copy

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramRouteDependencies:
    source_registry: TelegramSourceRegistry
    media_stager: Any
    page_budget: int
    clock: Callable[[], datetime]
    # Explicit queue writer for route continuations. ``None`` means the
    # helpers build one from the job's own session; tests inject a fake.
    job_repository: JobRepository | None = None

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
        repository=dependencies.job_repository,
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


@dataclass(frozen=True, slots=True)
class _ActivationScan:
    predecessor: int | None
    envelopes: tuple[TelegramEnvelope, ...]
    snapshot_token: str | None
    page_token: str | None
    seen_page_tokens: tuple[str | None, ...]
    last_scanned: int
    proven: bool


def _initialization_state(route: Any, payload: InitializeJobPayload) -> tuple[dict[str, Any], str, datetime, str]:
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
    expected_status = str(state.get("status"))
    if expected_status != "ready" and expected_status not in {"initializing", "catching_up"}:
        raise PermanentJobError(code="route_state_changed", message="Telegram route is not initializing")
    return state, str(requested_raw), requested_at, expected_status


async def _lock_validate_or_defer(
    job: JobExecution,
    context: JobContext,
    route_id: Any,
    *,
    dependencies: TelegramRouteDependencies,
    required_status: str,
    activation_requested_at: str | None,
) -> tuple[Any, dict[str, Any] | None]:
    locked, control = await _lock_route_and_control(context, route_id)
    pause_reason = _validate_locked_route(
        locked,
        control,
        required_status=required_status,
        activation_requested_at=activation_requested_at,
    )
    if pause_reason is None:
        return locked, None
    deferred_until = dependencies.now() + timedelta(seconds=max(locked.poll_interval_seconds, 30))
    await _defer_route_job(
        context,
        repository=dependencies.job_repository,
        route=locked,
        job=job,
        scheduled_for=deferred_until,
    )
    return locked, {"held": True, "reason": pause_reason, "deferred_until": deferred_until.isoformat()}


async def _scan_activation_pages(
    loaded: _LoadedRoute,
    state: dict[str, Any],
    boundary: datetime,
    *,
    page_budget: int,
) -> _ActivationScan:
    snapshot_token = state.get("activation_snapshot_token")
    page_token = state.get("activation_page_token")
    seen_page_tokens = list(state.get("activation_seen_page_tokens") or [])
    last_scanned = int(state.get("activation_last_scanned_id") or 0)
    initial_envelopes: list[TelegramEnvelope] = []
    for _ in range(page_budget):
        current_page_token = page_token
        if current_page_token in seen_page_tokens:
            raise RetryableJobError(
                code="telegram_activation_token_repeated",
                message="Telegram activation repeated a page token",
            )
        result = await loaded.adapter.fetch(
            _request(loaded, limit=100, snapshot_token=snapshot_token, page_token=page_token)
        )
        if snapshot_token is not None and result.snapshot_token != snapshot_token:
            raise RetryableJobError(
                code="telegram_activation_snapshot_changed",
                message="Telegram activation snapshot changed during pagination",
            )
        snapshot_token = result.snapshot_token
        seen_page_tokens.append(current_page_token)
        ordered = sorted(result.envelopes, key=_coordinate, reverse=True)
        last_scanned = _activation_page_progress(ordered, last_scanned)
        decision = classify_activation_page(ordered, boundary=boundary, complete=result.complete)
        initial_envelopes.extend(decision.newer)
        if decision.boundary_proven:
            return _ActivationScan(
                decision.predecessor_id,
                tuple(initial_envelopes),
                snapshot_token,
                page_token,
                tuple(seen_page_tokens),
                last_scanned,
                True,
            )
        page_token = _next_activation_page_token(result, current_page_token, seen_page_tokens, ordered)
    return _ActivationScan(
        None,
        tuple(initial_envelopes),
        snapshot_token,
        page_token,
        tuple(seen_page_tokens),
        last_scanned,
        False,
    )


def _activation_page_progress(ordered: list[TelegramEnvelope], last_scanned: int) -> int:
    if not ordered:
        return last_scanned
    page_minimum = min(item.anchor_message_id for item in ordered)
    if last_scanned and page_minimum >= last_scanned:
        raise RetryableJobError(
            code="telegram_activation_envelope_no_progress",
            message="Telegram activation pages made no unique progress",
        )
    return page_minimum


def _next_activation_page_token(
    result: Any,
    current_page_token: str | None,
    seen_page_tokens: list[str | None],
    ordered: list[TelegramEnvelope],
) -> str:
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
    return result.next_page_token


async def _persist_activation_scan(
    job: JobExecution,
    context: JobContext,
    route: Any,
    scan: _ActivationScan,
    *,
    dependencies: TelegramRouteDependencies,
    expected_status: str,
    requested_raw: str,
    boundary: datetime,
) -> dict[str, Any]:
    async with context.session.begin():
        locked, deferred = await _lock_validate_or_defer(
            job,
            context,
            route.id,
            dependencies=dependencies,
            required_status=expected_status,
            activation_requested_at=requested_raw,
        )
        if deferred is not None:
            return deferred
        locked_state = dict(locked.cursor_state or {})
        locked_state.update(
            {
                "status": "catching_up",
                "activation_boundary_at": boundary.isoformat(),
                "activation_snapshot_token": scan.snapshot_token,
                "activation_page_token": scan.page_token,
                "activation_seen_page_tokens": list(scan.seen_page_tokens),
                "activation_last_scanned_id": scan.last_scanned,
            }
        )
        locked.cursor_state = locked_state
        await _enqueue_continuation(
            context,
            repository=dependencies.job_repository,
            route_id=route.id,
            last_scanned_id=scan.last_scanned,
            activation_requested_at=requested_raw,
            phase="activation_scan",
            continuation_state={
                "activation_requested_at": requested_raw,
                "snapshot_token": scan.snapshot_token,
                "page_token": scan.page_token,
                "last_scanned_id": scan.last_scanned,
            },
        )
    return {"route_id": str(route.id), "captured": 0, "initialized": False, "continuation_enqueued": True}


async def _persist_activation_boundary(
    job: JobExecution,
    context: JobContext,
    route: Any,
    predecessor: int | None,
    *,
    dependencies: TelegramRouteDependencies,
    expected_status: str,
    requested_raw: str,
    boundary: datetime,
) -> dict[str, Any] | None:
    async with context.session.begin():
        locked, deferred = await _lock_validate_or_defer(
            job,
            context,
            route.id,
            dependencies=dependencies,
            required_status=expected_status,
            activation_requested_at=requested_raw,
        )
        if deferred is not None:
            return deferred
        predecessor = predecessor if predecessor is not None else 0
        locked_state = dict(locked.cursor_state or {})
        locked_state.update(
            {
                "status": "catching_up",
                "activation_boundary_at": boundary.isoformat(),
                "activation_message_id": int(predecessor),
                "last_message_id": int(predecessor),
            }
        )
        for key in (
            "activation_snapshot_token",
            "activation_page_token",
            "activation_seen_page_tokens",
            "activation_last_scanned_id",
        ):
            locked_state.pop(key, None)
        locked.cursor_state = locked_state
    return None


async def _capture_initial_envelopes(
    job: JobExecution,
    context: JobContext,
    loaded: _LoadedRoute,
    envelopes: tuple[TelegramEnvelope, ...],
    *,
    dependencies: TelegramRouteDependencies,
    requested_raw: str,
) -> tuple[int, dict[str, Any] | None]:
    captured = 0
    unique = {item.source_key: item for item in envelopes}
    for envelope in sorted(unique.values(), key=_coordinate):
        _, deferred = await _capture(
            loaded=loaded,
            envelope=envelope,
            dispatch_kind="live",
            job=job,
            context=context,
            media_stager=dependencies.media_stager,
            repository=dependencies.job_repository,
            activation_requested_at=requested_raw,
            required_status="catching_up",
            deferred_until=dependencies.now() + timedelta(seconds=max(loaded.route.poll_interval_seconds, 30)),
        )
        if deferred is not None:
            return captured, deferred
        captured += 1
    return captured, None


async def _capture_catch_up_envelopes(
    job: JobExecution,
    context: JobContext,
    loaded: _LoadedRoute,
    envelopes: tuple[TelegramEnvelope, ...],
    *,
    dependencies: TelegramRouteDependencies,
    requested_raw: str,
) -> tuple[int, dict[str, Any] | None]:
    captured = 0
    for envelope in envelopes:
        _, deferred = await _capture(
            loaded=loaded,
            envelope=envelope,
            dispatch_kind="live",
            job=job,
            context=context,
            media_stager=dependencies.media_stager,
            repository=dependencies.job_repository,
            activation_requested_at=requested_raw,
            required_status="catching_up",
            deferred_until=dependencies.now() + timedelta(seconds=max(loaded.route.poll_interval_seconds, 30)),
        )
        if deferred is not None:
            return captured, deferred
        captured += 1
    return captured, None


async def _finalize_initialization(
    job: JobExecution,
    context: JobContext,
    route: Any,
    captured: int,
    *,
    dependencies: TelegramRouteDependencies,
    requested_raw: str,
) -> dict[str, Any]:
    async with context.session.begin():
        locked, deferred = await _lock_validate_or_defer(
            job,
            context,
            route.id,
            dependencies=dependencies,
            required_status="catching_up",
            activation_requested_at=requested_raw,
        )
        if deferred is not None:
            return deferred
        locked_state = dict(locked.cursor_state or {})
        locked_state.pop("initialization_forward", None)
        locked_state["status"] = "ready"
        initialized_at = dependencies.now()
        locked_state["initialized_at"] = initialized_at.isoformat()
        locked.cursor_state = locked_state
        locked.next_poll_at = initialized_at
    cursor = int((route.cursor_state or {}).get("last_message_id") or 0)
    return {"route_id": str(route.id), "cursor": cursor, "captured": captured, "initialized": True}


async def _clear_initialization_forward(
    job: JobExecution,
    context: JobContext,
    route: Any,
    *,
    dependencies: TelegramRouteDependencies,
    requested_raw: str,
) -> dict[str, Any] | None:
    async with context.session.begin():
        locked, deferred = await _lock_validate_or_defer(
            job,
            context,
            route.id,
            dependencies=dependencies,
            required_status="catching_up",
            activation_requested_at=requested_raw,
        )
        if deferred is not None:
            return deferred
        locked_state = dict(locked.cursor_state or {})
        locked_state.pop("initialization_forward", None)
        locked.cursor_state = locked_state
    return None


async def _enqueue_catch_up_cycle(
    job: JobExecution,
    context: JobContext,
    route: Any,
    cursor: int,
    captured: int,
    *,
    dependencies: TelegramRouteDependencies,
    requested_raw: str,
) -> dict[str, Any]:
    async with context.session.begin():
        _, deferred = await _lock_validate_or_defer(
            job,
            context,
            route.id,
            dependencies=dependencies,
            required_status="catching_up",
            activation_requested_at=requested_raw,
        )
        if deferred is not None:
            return deferred
        await _enqueue_continuation(
            context,
            repository=dependencies.job_repository,
            route_id=route.id,
            last_scanned_id=cursor,
            activation_requested_at=requested_raw,
            phase="catch_up_cycle",
            continuation_state={
                "activation_requested_at": requested_raw,
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


async def _run_initialization_catch_up(
    job: JobExecution,
    context: JobContext,
    loaded: _LoadedRoute,
    captured: int,
    *,
    dependencies: TelegramRouteDependencies,
    requested_raw: str,
) -> dict[str, Any]:
    route = loaded.route
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
        captured_now, deferred = await _capture_catch_up_envelopes(
            job,
            context,
            loaded,
            step.envelopes,
            dependencies=dependencies,
            requested_raw=requested_raw,
        )
        captured += captured_now
        if deferred is not None:
            return deferred
        if step.state is not None:
            progress = await _persist_forward_progress(
                context,
                repository=dependencies.job_repository,
                route_id=route.id,
                job=job,
                state_key="initialization_forward",
                state=step.state,
                last_scanned_id=step.last_scanned_id,
                required_status="catching_up",
                activation_requested_at=requested_raw,
                deferred_until=dependencies.now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
            )
            progress["captured"] = captured
            return progress
        if not step.envelopes:
            return await _finalize_initialization(
                job,
                context,
                route,
                captured,
                dependencies=dependencies,
                requested_raw=requested_raw,
            )
        if saved_forward is not None:
            deferred = await _clear_initialization_forward(
                job,
                context,
                route,
                dependencies=dependencies,
                requested_raw=requested_raw,
            )
            if deferred is not None:
                return deferred
    cursor = int((route.cursor_state or {}).get("last_message_id") or 0)
    return await _enqueue_catch_up_cycle(
        job,
        context,
        route,
        cursor,
        captured,
        dependencies=dependencies,
        requested_raw=requested_raw,
    )


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
    state, requested_raw, requested_at, expected_status = _initialization_state(route, payload)
    if expected_status == "ready":
        return {
            "route_id": str(route.id),
            "cursor": state.get("last_message_id", 0),
            "captured": 0,
            "initialized": True,
        }
    await context.session.commit()
    captured = 0
    predecessor = state.get("activation_message_id")
    if predecessor is None:
        boundary = requested_at.replace(microsecond=0)
        scan = await _scan_activation_pages(
            loaded,
            state,
            boundary,
            page_budget=dependencies.page_budget,
        )
        if not scan.proven:
            return await _persist_activation_scan(
                job,
                context,
                route,
                scan,
                dependencies=dependencies,
                expected_status=expected_status,
                requested_raw=requested_raw,
                boundary=boundary,
            )
        deferred = await _persist_activation_boundary(
            job,
            context,
            route,
            scan.predecessor,
            dependencies=dependencies,
            expected_status=expected_status,
            requested_raw=requested_raw,
            boundary=boundary,
        )
        if deferred is not None:
            return deferred
        captured, deferred = await _capture_initial_envelopes(
            job,
            context,
            loaded,
            scan.envelopes,
            dependencies=dependencies,
            requested_raw=requested_raw,
        )
        if deferred is not None:
            return deferred
    return await _run_initialization_catch_up(
        job,
        context,
        loaded,
        captured,
        dependencies=dependencies,
        requested_raw=requested_raw,
    )


def _poll_state(route: Any) -> tuple[dict[str, Any], str | None, dict[str, Any] | None, int]:
    state = dict(route.cursor_state or {})
    if not route.enabled or state.get("status") != "ready" or state.get("last_message_id") is None:
        raise PermanentJobError(code="route_not_ready", message="Telegram route is not ready for polling")
    saved_value = state.get("poll_forward")
    saved_forward = saved_value if isinstance(saved_value, dict) else None
    base_cursor = (saved_forward or {}).get("base_after_id", state["last_message_id"])
    if not isinstance(base_cursor, int):
        raise PermanentJobError(code="route_cursor_invalid", message="Telegram route cursor is invalid")
    return state, state.get("activation_requested_at"), saved_forward, base_cursor


async def _capture_source_edits(
    job: JobExecution,
    context: JobContext,
    loaded: _LoadedRoute,
    state: dict[str, Any],
    *,
    dependencies: TelegramRouteDependencies,
    expected_activation: str | None,
) -> tuple[int, dict[str, Any] | None]:
    recent = await _fetch_recent(loaded, limit=50)
    fingerprints = dict(state.get("recent_fingerprints") or {})
    edits = [
        envelope
        for envelope in recent
        if fingerprints.get(str(envelope.anchor_message_id)) is not None
        and fingerprints[str(envelope.anchor_message_id)] != telegram_envelope_fingerprint(envelope)
    ]
    count = 0
    for envelope in sorted(edits, key=_coordinate):
        _, deferred = await _capture(
            loaded=loaded,
            envelope=envelope,
            dispatch_kind="source_edit",
            job=job,
            context=context,
            media_stager=dependencies.media_stager,
            repository=dependencies.job_repository,
            force_review=True,
            activation_requested_at=expected_activation,
            required_status="ready",
            deferred_until=dependencies.now() + timedelta(seconds=max(loaded.route.poll_interval_seconds, 30)),
        )
        if deferred is not None:
            return count, deferred
        count += 1
    return count, None


async def _capture_poll_envelopes(
    job: JobExecution,
    context: JobContext,
    loaded: _LoadedRoute,
    envelopes: tuple[TelegramEnvelope, ...],
    *,
    dependencies: TelegramRouteDependencies,
    expected_activation: str | None,
) -> tuple[int, int, dict[str, Any] | None]:
    captured = 0
    filtered = 0
    for envelope in envelopes:
        decision = evaluate_content_filter(envelope.text, bool(envelope.media), loaded.route.content_filters or {})
        observed_at = dependencies.now()
        allowed_at = next_allowed_at(observed_at, loaded.route.quiet_hours or {})
        _, deferred = await _capture(
            loaded=loaded,
            envelope=envelope,
            dispatch_kind="live",
            job=job,
            context=context,
            media_stager=dependencies.media_stager,
            repository=dependencies.job_repository,
            enqueue_process=decision.accepted,
            scheduled_for=allowed_at if allowed_at > observed_at else None,
            filter_reason=decision.reason,
            activation_requested_at=expected_activation,
            required_status="ready",
            deferred_until=dependencies.now() + timedelta(seconds=max(loaded.route.poll_interval_seconds, 30)),
        )
        if deferred is not None:
            return captured, filtered, deferred
        captured += int(decision.accepted)
        filtered += int(not decision.accepted)
    return captured, filtered, None


async def _persist_poll_progress(
    job: JobExecution,
    context: JobContext,
    route: Any,
    step: Any,
    *,
    dependencies: TelegramRouteDependencies,
    expected_activation: str | None,
    captured: int,
    source_edits: int,
    filtered: int,
) -> dict[str, Any]:
    progress = await _persist_forward_progress(
        context,
        repository=dependencies.job_repository,
        route_id=route.id,
        job=job,
        state_key="poll_forward",
        state=step.state,
        last_scanned_id=step.last_scanned_id,
        required_status="ready",
        activation_requested_at=expected_activation,
        deferred_until=dependencies.now() + timedelta(seconds=max(route.poll_interval_seconds, 30)),
    )
    progress.update({"captured": captured, "source_edits": source_edits, "filtered": filtered})
    return progress


async def _finish_poll(
    job: JobExecution,
    context: JobContext,
    route: Any,
    *,
    dependencies: TelegramRouteDependencies,
    expected_activation: str | None,
    captured: int,
    source_edits: int,
    filtered: int,
) -> dict[str, Any]:
    async with context.session.begin():
        locked, deferred = await _lock_validate_or_defer(
            job,
            context,
            route.id,
            dependencies=dependencies,
            required_status="ready",
            activation_requested_at=expected_activation,
        )
        if deferred is not None:
            return deferred
        locked_state = dict(locked.cursor_state or {})
        locked_state.pop("poll_forward", None)
        locked.cursor_state = locked_state
        locked.last_polled_at = dependencies.now()
        locked.next_poll_at = locked.last_polled_at + timedelta(seconds=locked.poll_interval_seconds)
    return {"captured": captured, "source_edits": source_edits, "filtered": filtered}


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
    state, expected_activation, saved_forward, base_cursor = _poll_state(route)
    await context.session.commit()
    step = await _fetch_forward_step(
        loaded,
        after_id=base_cursor,
        page_budget=dependencies.page_budget,
        saved_state=saved_forward,
    )
    if not step.envelopes and step.state is not None:
        return await _persist_poll_progress(
            job,
            context,
            route,
            step,
            dependencies=dependencies,
            expected_activation=expected_activation,
            captured=0,
            source_edits=0,
            filtered=0,
        )
    source_edits, deferred = await _capture_source_edits(
        job,
        context,
        loaded,
        state,
        dependencies=dependencies,
        expected_activation=expected_activation,
    )
    if deferred is not None:
        return deferred
    captured, filtered, deferred = await _capture_poll_envelopes(
        job,
        context,
        loaded,
        step.envelopes,
        dependencies=dependencies,
        expected_activation=expected_activation,
    )
    if deferred is not None:
        return deferred
    if step.state is not None:
        return await _persist_poll_progress(
            job,
            context,
            route,
            step,
            dependencies=dependencies,
            expected_activation=expected_activation,
            captured=captured,
            source_edits=source_edits,
            filtered=filtered,
        )
    return await _finish_poll(
        job,
        context,
        route,
        dependencies=dependencies,
        expected_activation=expected_activation,
        captured=captured,
        source_edits=source_edits,
        filtered=filtered,
    )


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
            repository=dependencies.job_repository,
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
        repository=dependencies.job_repository,
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
    job_repository: JobRepository | None = None,
) -> TelegramRouteHandlers:
    if page_budget <= 0:
        raise ValueError("page_budget must be positive")
    dependencies = TelegramRouteDependencies(
        source_registry=source_registry,
        media_stager=media_stager,
        page_budget=page_budget,
        clock=clock or (lambda: datetime.now(UTC)),
        job_repository=job_repository,
    )
    return TelegramRouteHandlers(
        initialize=_bound_handler(initialize_route, dependencies),
        poll=_bound_handler(poll_route, dependencies),
        backfill=_bound_handler(backfill_route, dependencies),
        dry_run=_bound_handler(dry_run_route, dependencies),
    )
