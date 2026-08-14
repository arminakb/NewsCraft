from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from app.core.config import READINESS_CAPABILITIES, Settings
from app.core.redaction import redact_string
from app.jobs.models import RuntimeHeartbeat
from app.operations.health_schemas import (
    ComponentOperationalHealth,
    HealthState,
    RestartState,
    normalize_utc,
)

RUNBOOK_ROOT = "/docs/operations/readiness-and-health"
SAFE_JOB_TYPE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
SAFE_COMPONENT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
SECRET_REFERENCE = re.compile(
    r"(?:^|_)(?:api_?(?:id|hash|key)|authorization|credential|password|secret|session|token)(?:_|$)",
    re.IGNORECASE,
)


def _latest_heartbeats(heartbeats: Sequence[RuntimeHeartbeat]) -> dict[str, RuntimeHeartbeat]:
    latest: dict[str, RuntimeHeartbeat] = {}
    for heartbeat in sorted(
        heartbeats,
        key=lambda row: normalize_utc(row.observed_at, field="heartbeat observed_at"),
        reverse=True,
    ):
        latest.setdefault(str(heartbeat.component_id), heartbeat)
    return latest


def _missing_component(raw_id: str, component_id: str, config: Settings) -> ComponentOperationalHealth:
    component_type = "scheduler" if "scheduler" in raw_id.casefold() else "worker"
    return ComponentOperationalHealth(
        component_id=component_id,
        component_type=component_type,
        state=HealthState.UNKNOWN,
        code="heartbeat_missing",
        observed_at=None,
        last_success_at=None,
        capabilities=(),
        activity="unknown",
        restart_state=RestartState.UNKNOWN,
        restart_count_window=0,
        restart_window_seconds=config.restart_warning_window_seconds,
        message="No trustworthy heartbeat has been observed",
        runbook_url=f"{RUNBOOK_ROOT}#heartbeat-missing-or-stale",
    )


def _restart_details(
    metadata: Mapping[str, object],
    *,
    reference_time: datetime,
    database_reference: datetime,
    config: Settings,
) -> tuple[datetime | None, tuple[datetime, ...], RestartState]:
    process_started_at = _metadata_timestamp(metadata, "process_started_at")
    restart_times = _metadata_timestamps(metadata, "restart_observed_at")
    restart_window_start = reference_time - timedelta(seconds=config.restart_warning_window_seconds)
    recent_restarts = tuple(
        value for value in restart_times if restart_window_start <= value <= database_reference + timedelta(seconds=1)
    )
    if process_started_at is None:
        restart_state = RestartState.UNKNOWN
    elif len(recent_restarts) >= config.restart_warning_count:
        restart_state = RestartState.CRASH_LOOP
    elif recent_restarts:
        restart_state = RestartState.RECOVERED
    else:
        restart_state = RestartState.STABLE
    return process_started_at, recent_restarts, restart_state


def _heartbeat_state(
    *,
    observed_at: datetime,
    database_reference: datetime,
    heartbeat_age: float,
    component_type: str,
    active_age: float | None,
    restart_state: RestartState,
    config: Settings,
) -> tuple[HealthState, str, str]:
    if observed_at > database_reference + timedelta(seconds=1):
        return (
            HealthState.UNKNOWN,
            "heartbeat_clock_skew",
            "Heartbeat timestamp is outside the trusted database clock boundary",
        )
    fresh_seconds, unavailable_seconds = _component_thresholds(component_type, config)
    if heartbeat_age <= fresh_seconds:
        state, code, message = HealthState.HEALTHY, "heartbeat_fresh", "Heartbeat is fresh"
    elif heartbeat_age <= unavailable_seconds:
        state, code, message = HealthState.STALE, "heartbeat_stale", "Heartbeat is stale"
    else:
        state, code, message = (
            HealthState.UNAVAILABLE,
            "heartbeat_unavailable",
            "Heartbeat is older than the unavailable threshold",
        )
    if state == HealthState.HEALTHY and active_age is not None and active_age > config.job_stuck_seconds:
        return (
            HealthState.STALE,
            "active_work_overdue",
            "Runtime heartbeat is fresh but active work has exceeded its progress threshold",
        )
    if state == HealthState.HEALTHY and restart_state == RestartState.CRASH_LOOP:
        return (
            HealthState.STALE,
            "restart_rate_high",
            "Process restart rate exceeds the configured warning threshold",
        )
    return state, code, message


def _observed_component(
    component_id: str,
    heartbeat: RuntimeHeartbeat,
    *,
    reference_time: datetime,
    database_reference: datetime,
    config: Settings,
) -> tuple[ComponentOperationalHealth, tuple[str, ...]]:
    component_type = _safe_component_type(getattr(heartbeat, "component_type", "unknown"))
    capabilities = _safe_capabilities(getattr(heartbeat, "capabilities", ()))
    observed_at = normalize_utc(heartbeat.observed_at, field="heartbeat observed_at")
    raw_metadata = getattr(heartbeat, "runtime_metadata", None)
    metadata = raw_metadata if isinstance(raw_metadata, Mapping) else {}
    last_success_at = _metadata_timestamp(metadata, "last_success_at")
    active_started_at = _metadata_timestamp(metadata, "active_work_started_at")
    activity = str(metadata.get("state", "unknown"))
    if activity not in {"idle", "working", "ticking"}:
        activity = "unknown"
    active_work_type = _safe_job_type(metadata.get("active_work_type"))
    process_started_at, recent_restarts, restart_state = _restart_details(
        metadata,
        reference_time=reference_time,
        database_reference=database_reference,
        config=config,
    )
    heartbeat_age = max(0.0, (reference_time - observed_at).total_seconds())
    success_age = max(0.0, (reference_time - last_success_at).total_seconds()) if last_success_at is not None else None
    active_age = (
        max(0.0, (reference_time - active_started_at).total_seconds()) if active_started_at is not None else None
    )
    state, code, message = _heartbeat_state(
        observed_at=observed_at,
        database_reference=database_reference,
        heartbeat_age=heartbeat_age,
        component_type=component_type,
        active_age=active_age,
        restart_state=restart_state,
        config=config,
    )
    component = ComponentOperationalHealth(
        component_id=component_id,
        component_type=component_type,
        state=state,
        code=code,
        observed_at=observed_at,
        last_success_at=last_success_at,
        heartbeat_age_seconds=heartbeat_age,
        last_success_age_seconds=success_age,
        capabilities=capabilities,
        activity=activity,
        active_work_type=active_work_type,
        active_work_age_seconds=active_age,
        process_started_at=process_started_at,
        restart_state=restart_state,
        restart_count_window=len(recent_restarts),
        restart_window_seconds=config.restart_warning_window_seconds,
        last_restart_at=recent_restarts[-1] if recent_restarts else None,
        message=message,
        runbook_url=f"{RUNBOOK_ROOT}#heartbeat-missing-or-stale",
    )
    return component, _safe_job_types(metadata.get("job_types"))


def build_component_health(
    heartbeats: Sequence[RuntimeHeartbeat],
    *,
    reference_time: datetime,
    config: Settings,
    database_time_value: datetime | None = None,
    expected_component_ids: str = "",
) -> tuple[dict[str, ComponentOperationalHealth], dict[str, int]]:
    reference_time = normalize_utc(reference_time, field="component reference time")
    database_reference = normalize_utc(database_time_value or reference_time, field="database reference time")
    expected = {value.strip() for value in (expected_component_ids or "").split(",") if value.strip()}
    latest = _latest_heartbeats(heartbeats)
    components: dict[str, ComponentOperationalHealth] = {}
    healthy_job_coverage: dict[str, int] = {}
    for raw_id in sorted(expected | set(latest)):
        component_id = _safe_component_id(raw_id)
        heartbeat = latest.get(raw_id)
        if heartbeat is None:
            components[component_id] = _missing_component(raw_id, component_id, config)
            continue
        component, job_types = _observed_component(
            component_id,
            heartbeat,
            reference_time=reference_time,
            database_reference=database_reference,
            config=config,
        )
        components[component_id] = component
        if component.state == HealthState.HEALTHY:
            for job_type in job_types:
                healthy_job_coverage[job_type] = healthy_job_coverage.get(job_type, 0) + 1
    return components, healthy_job_coverage


def _component_thresholds(component_type: str, config: Settings) -> tuple[int, int]:
    if component_type == "scheduler":
        return config.scheduler_health_fresh_seconds, config.scheduler_health_unavailable_seconds
    return config.worker_health_fresh_seconds, config.worker_health_unavailable_seconds


def _safe_component_id(value: object) -> str:
    raw = str(value)
    sanitized = redact_string(raw)
    if sanitized == raw and SAFE_COMPONENT_ID.fullmatch(raw) and not SECRET_REFERENCE.search(raw):
        return raw
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"component-{digest}"


def _safe_component_type(value: object) -> str:
    normalized = str(value).casefold()
    return normalized if normalized in {"worker", "scheduler"} else "unknown"


def _safe_capabilities(values: object) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return ()
    return tuple(sorted({str(value).casefold() for value in values if str(value).casefold() in READINESS_CAPABILITIES}))


def _safe_job_types(values: object) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return ()
    safe = {_safe_job_type(value) for value in values}
    return tuple(sorted(value for value in safe if value is not None))


def _safe_job_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.casefold()
    if (
        SAFE_JOB_TYPE.fullmatch(normalized)
        and not SECRET_REFERENCE.search(normalized)
        and redact_string(normalized) == normalized
    ):
        return normalized
    return None


def _metadata_timestamp(metadata: Mapping[str, object], key: str) -> datetime | None:
    value = metadata.get(key)
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return normalize_utc(parsed, field=key)
    except ValueError:
        return None


def _metadata_timestamps(metadata: Mapping[str, object], key: str) -> tuple[datetime, ...]:
    values = metadata.get(key)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return ()
    parsed = {
        timestamp
        for value in values[-32:]
        if isinstance(value, str)
        and len(value) <= 64
        and (timestamp := _metadata_timestamp({key: value}, key)) is not None
    }
    return tuple(sorted(parsed))
