from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.jobs.errors import JobCapabilityUnavailable
from app.jobs.models import RuntimeHeartbeat, WorkflowJob
from app.jobs.types import JobStatus
from app.operations.health import build_component_health, normalize_utc

API_CAPABILITY_GATE_SESSION_KEY = "enforce_api_capability_gate"
API_CAPABILITY_GATE_SNAPSHOT_KEY = "api_capability_gate_snapshot"
SAFE_GATE_JOB_TYPE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
SAFE_GATE_CODES = frozenset(
    {
        "job_capability_unavailable",
        "job_capability_unknown",
        "job_queue_capacity_exceeded",
    }
)


def api_capability_gate_enabled(session: AsyncSession) -> bool:
    info = getattr(session, "info", None)
    return isinstance(info, dict) and info.get(API_CAPABILITY_GATE_SESSION_KEY) is True


@dataclass(frozen=True, slots=True)
class _CapabilityGateSnapshot:
    config: Settings
    coverage: dict[str, int]


async def _request_snapshot(session: AsyncSession, config: Settings) -> _CapabilityGateSnapshot:
    info = getattr(session, "info", None)
    if isinstance(info, dict):
        cached = info.get(API_CAPABILITY_GATE_SNAPSHOT_KEY)
        if isinstance(cached, _CapabilityGateSnapshot) and cached.config is config:
            return cached

    database_now = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(database_now, datetime):
        raise RuntimeError("database clock unavailable")
    database_now = normalize_utc(database_now, field="capability gate database clock")
    heartbeats = list(
        await session.scalars(
            select(RuntimeHeartbeat)
            .where(RuntimeHeartbeat.component_type == "worker")
            .order_by(RuntimeHeartbeat.observed_at.desc())
            .limit(10_000)
        )
    )
    _components, coverage = build_component_health(
        heartbeats,
        reference_time=database_now,
        database_time_value=database_now,
        config=config,
        expected_component_ids="",
    )
    snapshot = _CapabilityGateSnapshot(config=config, coverage=coverage)
    if isinstance(info, dict):
        info[API_CAPABILITY_GATE_SNAPSHOT_KEY] = snapshot
    return snapshot


async def require_available_job_type(
    session: AsyncSession,
    job_type: str,
    *,
    config: Settings = settings,
) -> None:
    """Reject impossible API work without exposing heartbeat metadata or errors."""
    if not api_capability_gate_enabled(session):
        return

    retry_after = config.capability_retry_after_seconds
    try:
        snapshot = await _request_snapshot(session, config)
        active_count = int(
            await session.scalar(
                select(func.count())
                .select_from(WorkflowJob)
                .where(
                    WorkflowJob.job_type == job_type,
                    WorkflowJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
                )
            )
            or 0
        )
    except JobCapabilityUnavailable:
        raise
    except Exception:  # noqa: BLE001 - fail closed with a constant public code
        raise JobCapabilityUnavailable(
            code="job_capability_unknown",
            job_type=job_type,
            retry_after_seconds=retry_after,
        ) from None

    if snapshot.coverage.get(job_type, 0) < 1:
        raise JobCapabilityUnavailable(
            code="job_capability_unavailable",
            job_type=job_type,
            retry_after_seconds=retry_after,
        )
    if active_count >= config.capability_queue_ceiling:
        raise JobCapabilityUnavailable(
            code="job_queue_capacity_exceeded",
            job_type=job_type,
            retry_after_seconds=retry_after,
        )


def safe_gate_job_type(job_type: str) -> str:
    return job_type if SAFE_GATE_JOB_TYPE.fullmatch(job_type) else "unknown"


def safe_gate_code(code: str) -> str:
    return code if code in SAFE_GATE_CODES else "job_capability_unknown"
