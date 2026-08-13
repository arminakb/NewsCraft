from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import READINESS_CAPABILITIES, Settings, settings
from app.core.outbound_proxy import safe_proxy_diagnostics
from app.core.redaction import redact_string
from app.db.schema import SCHEMA_HEAD
from app.jobs.models import RuntimeHeartbeat, WorkflowEvent, WorkflowJob
from app.jobs.runtime import RuntimeHeartbeatService
from app.jobs.types import JobStatus
from app.operations.health_schemas import (
    STATE_DEFINITIONS,
    Clock,
    ComponentOperationalHealth,
    DependencyHealth,
    HealthState,
    JobRecoveryOperationalHealth,
    OperationalAlert,
    OperationalHealthSnapshot,
    QueueOperationalHealth,
    ReadinessSnapshot,
    RestartState,
    StorageProbe,
    normalize_utc,
    snapshot_high_water,
)
from app.security.secret_store import SecretStoreRuntime

RUNBOOK_ROOT = "/docs/operations/readiness-and-health"
SAFE_JOB_TYPE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
SAFE_COMPONENT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
SECRET_REFERENCE = re.compile(
    r"(?:^|_)(?:api_?(?:id|hash|key)|authorization|credential|password|secret|session|token)(?:_|$)",
    re.IGNORECASE,
)


async def database_time(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime):
        raise RuntimeError("database clock did not return a timestamp")
    return normalize_utc(value, field="database clock")


async def probe_storage_directory(
    name: str,
    path: Path,
    observed_at: datetime,
    *,
    timeout_seconds: float = settings.health_storage_timeout_seconds,
) -> DependencyHealth:
    started = time.monotonic()

    def inspect() -> bool:
        if not path.is_dir():
            return False
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fstat(descriptor)
            with os.scandir(path) as entries:
                next(entries, None)
        finally:
            os.close(descriptor)
        return True

    try:
        async with asyncio.timeout(timeout_seconds):
            available = await asyncio.to_thread(inspect)
    except OSError, TimeoutError:
        available = False
    latency_ms = max(0, int((time.monotonic() - started) * 1_000))
    if available:
        return DependencyHealth(
            state=HealthState.HEALTHY,
            code=f"{name}_accessible",
            observed_at=observed_at,
            latency_ms=latency_ms,
            message=f"Required {name.replace('_', ' ')} is readable and traversable",
            runbook_url=f"{RUNBOOK_ROOT}#storage-unavailable",
        )
    return DependencyHealth(
        state=HealthState.UNAVAILABLE,
        code=f"{name}_unavailable",
        observed_at=observed_at,
        latency_ms=latency_ms,
        message=f"Required {name.replace('_', ' ')} is unavailable",
        runbook_url=f"{RUNBOOK_ROOT}#storage-unavailable",
    )


def _database_dependency(*, connected: bool, observed_at: datetime, latency_ms: int) -> DependencyHealth:
    """The single "database" dependency entry every readiness surface reports."""
    if connected:
        return DependencyHealth(
            state=HealthState.HEALTHY,
            code="database_connected",
            observed_at=observed_at,
            latency_ms=latency_ms,
            message="Database connectivity is available",
            runbook_url=f"{RUNBOOK_ROOT}#database-unavailable",
        )
    return DependencyHealth(
        state=HealthState.UNAVAILABLE,
        code="database_unavailable",
        observed_at=observed_at,
        latency_ms=latency_ms,
        message="Database connectivity is unavailable",
        runbook_url=f"{RUNBOOK_ROOT}#database-unavailable",
    )


def _database_dependencies(
    *,
    observed_at: datetime,
    latency_ms: int,
    schema_revision: object,
) -> dict[str, DependencyHealth]:
    """The ("database", "schema") pair for a database that answered its probes."""
    current = schema_revision == SCHEMA_HEAD
    return {
        "database": _database_dependency(connected=True, observed_at=observed_at, latency_ms=latency_ms),
        "schema": DependencyHealth(
            state=HealthState.HEALTHY if current else HealthState.UNAVAILABLE,
            code="schema_current" if current else "schema_mismatch",
            observed_at=observed_at,
            latency_ms=latency_ms,
            message="Database schema is current" if current else "Database schema is not current",
            runbook_url=f"{RUNBOOK_ROOT}#schema-mismatch",
        ),
    }


def _unreachable_database_dependencies(*, observed_at: datetime, latency_ms: int) -> dict[str, DependencyHealth]:
    """The ("database", "schema") pair for a database that failed its probes."""
    return {
        "database": _database_dependency(connected=False, observed_at=observed_at, latency_ms=latency_ms),
        "schema": DependencyHealth(
            state=HealthState.UNKNOWN,
            code="schema_unknown",
            observed_at=observed_at,
            latency_ms=latency_ms,
            message="Database schema state could not be verified",
            runbook_url=f"{RUNBOOK_ROOT}#schema-mismatch",
        ),
    }


def _default_storage_probe(config: Settings) -> StorageProbe:
    """The storage probe every health surface uses when none is injected."""

    async def probe(name: str, path: Path, observed_at: datetime) -> DependencyHealth:
        return await probe_storage_directory(
            name,
            path,
            observed_at,
            timeout_seconds=config.health_storage_timeout_seconds,
        )

    return probe


async def _storage_dependencies(
    probe: StorageProbe,
    config: Settings,
    observed_at: datetime,
) -> dict[str, DependencyHealth]:
    """The ("media_storage", "export_storage") pair, probed concurrently."""
    names = ("media_storage", "export_storage")
    results = await asyncio.gather(
        probe(names[0], Path(config.media_root), observed_at),
        probe(names[1], Path(config.export_root), observed_at),
    )
    return dict(zip(names, results, strict=True))


class ReadinessService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        config: Settings = settings,
        clock: Clock | None = None,
        storage_probe: StorageProbe | None = None,
    ) -> None:
        self.session = session
        self.config = config
        self.clock = clock or (lambda: datetime.now(UTC))
        self.storage_probe = storage_probe or _default_storage_probe(config)

    async def snapshot(self) -> ReadinessSnapshot:
        fallback_time = normalize_utc(self.clock(), field="readiness clock")
        checks: dict[str, DependencyHealth] = {}
        required_capabilities = _configured_capabilities(self.config.readiness_required_capabilities)

        checks.update(await _storage_dependencies(self.storage_probe, self.config, fallback_time))

        started = time.monotonic()
        heartbeats: list[RuntimeHeartbeat] = []
        try:
            async with asyncio.timeout(self.config.readiness_timeout_seconds):
                one = await self.session.scalar(text("SELECT 1"))
                if one != 1:
                    raise RuntimeError("database connectivity probe failed")
                schema_revision = await self.session.scalar(text("SELECT version_num FROM alembic_version"))
                if required_capabilities:
                    heartbeats = await RuntimeHeartbeatService(self.session).list_recent(limit=10_000)
                # Read the clock only AFTER every projected row, so a heartbeat
                # committed while we were reading cannot postdate the database
                # reference and be misread as clock skew. See the ordering rule in
                # app/operations/diagnostics.py and OperationalHealthService.snapshot.
                observed_at = await database_time(self.session)
        except Exception:  # noqa: BLE001 - readiness returns a safe constant code
            latency_ms = max(0, int((time.monotonic() - started) * 1_000))
            checks.update(_unreachable_database_dependencies(observed_at=fallback_time, latency_ms=latency_ms))
            for capability in required_capabilities:
                checks[f"capability:{capability}"] = _capability_dependency(
                    capability,
                    available=False,
                    observed_at=fallback_time,
                    unknown=True,
                )
            return _readiness_snapshot(fallback_time, checks, required_capabilities)

        latency_ms = max(0, int((time.monotonic() - started) * 1_000))
        checks.update(
            _database_dependencies(
                observed_at=observed_at,
                latency_ms=latency_ms,
                schema_revision=schema_revision,
            )
        )

        generated_at = snapshot_high_water(
            fallback_time,
            observed_at,
            *(row.observed_at for row in heartbeats),
        )
        components, _coverage = build_component_health(
            heartbeats,
            reference_time=generated_at,
            database_time_value=observed_at,
            config=self.config,
        )
        for capability in required_capabilities:
            available = any(
                component.state == HealthState.HEALTHY and capability in component.capabilities
                for component in components.values()
            )
            checks[f"capability:{capability}"] = _capability_dependency(
                capability,
                available=available,
                observed_at=observed_at,
            )
        return _readiness_snapshot(generated_at, checks, required_capabilities)


class SecretReadinessService:
    """Readiness for encrypted-secret mutations without gating unrelated API reads."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        runtime: SecretStoreRuntime | None,
        config: Settings = settings,
        clock: Clock | None = None,
    ) -> None:
        self.session = session
        self.runtime = runtime
        self.config = config
        self.clock = clock or (lambda: datetime.now(UTC))

    async def snapshot(self) -> ReadinessSnapshot:
        fallback_time = normalize_utc(self.clock(), field="secret readiness clock")
        checks: dict[str, DependencyHealth] = {}
        configuration_valid = self.runtime is not None and self.runtime.configuration_valid
        initialized = self.runtime is not None and self.runtime.initialized
        checks["encryption_configuration"] = DependencyHealth(
            state=HealthState.HEALTHY if configuration_valid else HealthState.UNAVAILABLE,
            code=(
                "secret_store_configuration_valid"
                if configuration_valid
                else "secret_store_configuration_invalid"
            ),
            observed_at=fallback_time,
            latency_ms=0,
            message=(
                "Encrypted secret configuration is valid"
                if configuration_valid
                else "Encrypted secret configuration is invalid"
            ),
            runbook_url=f"{RUNBOOK_ROOT}#secret-store-unavailable",
        )
        checks["secret_store"] = DependencyHealth(
            state=HealthState.HEALTHY if initialized else HealthState.UNAVAILABLE,
            code="secret_store_initialized" if initialized else "secret_store_unavailable",
            observed_at=fallback_time,
            latency_ms=0,
            message="Secret Store is initialized" if initialized else "Secret Store is unavailable",
            runbook_url=f"{RUNBOOK_ROOT}#secret-store-unavailable",
        )

        started = time.monotonic()
        try:
            async with asyncio.timeout(self.config.readiness_timeout_seconds):
                if await self.session.scalar(text("SELECT 1")) != 1:
                    raise RuntimeError("database connectivity probe failed")
                relation = await self.session.scalar(text("SELECT to_regclass('public.encrypted_secrets')"))
                observed_at = await database_time(self.session)
        except Exception:  # noqa: BLE001 - readiness exposes safe constants only
            latency_ms = max(0, int((time.monotonic() - started) * 1_000))
            checks["database"] = _database_dependency(
                connected=False, observed_at=fallback_time, latency_ms=latency_ms
            )
            checks["secret_schema"] = DependencyHealth(
                state=HealthState.UNKNOWN,
                code="secret_schema_unknown",
                observed_at=fallback_time,
                latency_ms=latency_ms,
                message="Encrypted secret schema state could not be verified",
                runbook_url=f"{RUNBOOK_ROOT}#schema-mismatch",
            )
            return _readiness_snapshot(fallback_time, checks, ())

        latency_ms = max(0, int((time.monotonic() - started) * 1_000))
        checks["database"] = _database_dependency(connected=True, observed_at=observed_at, latency_ms=latency_ms)
        schema_available = relation is not None
        checks["secret_schema"] = DependencyHealth(
            state=HealthState.HEALTHY if schema_available else HealthState.UNAVAILABLE,
            code="secret_schema_available" if schema_available else "secret_schema_unavailable",
            observed_at=observed_at,
            latency_ms=latency_ms,
            message=(
                "Encrypted secret schema is available"
                if schema_available
                else "Encrypted secret schema is unavailable"
            ),
            runbook_url=f"{RUNBOOK_ROOT}#schema-mismatch",
        )
        return _readiness_snapshot(observed_at, checks, ())


class OperationalHealthService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        config: Settings = settings,
        clock: Clock | None = None,
        storage_probe: StorageProbe | None = None,
    ) -> None:
        self.session = session
        self.config = config
        self.clock = clock or (lambda: datetime.now(UTC))
        self.storage_probe = storage_probe or _default_storage_probe(config)

    async def snapshot(self) -> OperationalHealthSnapshot:
        fallback_time = normalize_utc(self.clock(), field="operations health clock")
        dependencies = await _storage_dependencies(self.storage_probe, self.config, fallback_time)
        # Started outside the try so a probe that fails or times out still reports
        # what it cost, the way ReadinessService.snapshot does.
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.config.readiness_timeout_seconds):
                if await self.session.scalar(text("SELECT 1")) != 1:
                    raise RuntimeError("database connectivity probe failed")
                schema_revision = await self.session.scalar(text("SELECT version_num FROM alembic_version"))
                query_time = await database_time(self.session)
                heartbeats = await RuntimeHeartbeatService(self.session).list_recent(limit=10_000)
                queue_rows = await self._queue_rows(query_time)
                recovery_rows = await self._recovery_rows(query_time)
                database_observed_at = await database_time(self.session)
                database_latency_ms = max(0, int((time.monotonic() - started) * 1_000))
        except Exception:  # noqa: BLE001 - operational output is fail-closed and sanitized
            latency_ms = max(0, int((time.monotonic() - started) * 1_000))
            dependencies.update(_unreachable_database_dependencies(observed_at=fallback_time, latency_ms=latency_ms))
            components, _coverage = build_component_health(
                [],
                reference_time=fallback_time,
                config=self.config,
                expected_component_ids=self.config.expected_runtime_component_ids,
            )
            return _operational_snapshot(fallback_time, dependencies, components, [], [])

        generated_at = snapshot_high_water(
            fallback_time,
            query_time,
            database_observed_at,
            *(row.observed_at for row in heartbeats),
        )
        dependencies.update(
            _database_dependencies(
                observed_at=database_observed_at,
                latency_ms=database_latency_ms,
                schema_revision=schema_revision,
            )
        )
        components, coverage = build_component_health(
            heartbeats,
            reference_time=generated_at,
            database_time_value=database_observed_at,
            config=self.config,
            expected_component_ids=self.config.expected_runtime_component_ids,
        )
        queues = build_queue_health(
            queue_rows,
            generated_at=generated_at,
            healthy_job_coverage=coverage,
            config=self.config,
        )
        recoveries = build_recovery_health(
            recovery_rows,
            config=self.config,
        )
        return _operational_snapshot(
            generated_at,
            dependencies,
            components,
            queues,
            recoveries,
        )

    async def _queue_rows(self, observed_at: datetime) -> list[Mapping[str, Any]]:
        due_at = func.coalesce(WorkflowJob.scheduled_for, WorkflowJob.created_at)
        queued_due = and_(WorkflowJob.status == JobStatus.QUEUED, due_at <= observed_at)
        running = WorkflowJob.status == JobStatus.RUNNING
        active = WorkflowJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING))
        stale_before = observed_at - timedelta(seconds=self.config.worker_health_fresh_seconds)
        stuck_before = observed_at - timedelta(seconds=self.config.job_stuck_seconds)
        retry_pressure = and_(
            active,
            WorkflowJob.attempt_count >= func.greatest(WorkflowJob.max_attempts - 1, 1),
        )
        statement = (
            select(
                WorkflowJob.job_type.label("job_type"),
                func.count().filter(queued_due).label("due_count"),
                func.min(due_at).filter(queued_due).label("oldest_due_at"),
                func.count().filter(running).label("running_count"),
                func.count()
                .filter(
                    and_(
                        running,
                        WorkflowJob.lease_expires_at.is_not(None),
                        WorkflowJob.lease_expires_at <= observed_at,
                    )
                )
                .label("expired_lease_count"),
                func.count()
                .filter(
                    and_(
                        running,
                        or_(WorkflowJob.heartbeat_at.is_(None), WorkflowJob.heartbeat_at < stale_before),
                    )
                )
                .label("stale_running_count"),
                func.count()
                .filter(
                    and_(
                        running,
                        or_(WorkflowJob.started_at.is_(None), WorkflowJob.started_at < stuck_before),
                    )
                )
                .label("overdue_running_count"),
                func.count().filter(retry_pressure).label("excessive_retry_count"),
                func.count()
                .filter(and_(active, WorkflowJob.attempt_count >= WorkflowJob.max_attempts))
                .label("exhausted_active_count"),
                func.count().filter(WorkflowJob.status == JobStatus.FAILED).label("failed_count"),
                func.count().filter(WorkflowJob.status == JobStatus.NEEDS_REVIEW).label("needs_review_count"),
            )
            .where(
                WorkflowJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.FAILED, JobStatus.NEEDS_REVIEW))
            )
            .group_by(WorkflowJob.job_type)
            .order_by(WorkflowJob.job_type)
        )
        result = await self.session.execute(statement)
        return [dict(row) for row in result.mappings()]

    async def _recovery_rows(self, observed_at: datetime) -> list[Mapping[str, Any]]:
        cutoff = observed_at - timedelta(seconds=self.config.recovery_observation_window_seconds)
        recovery_count = func.count(WorkflowEvent.id)
        last_recovered_at = func.max(WorkflowEvent.created_at)
        statement = (
            select(
                WorkflowEvent.workflow_job_id.label("job_id"),
                WorkflowJob.job_type.label("job_type"),
                WorkflowJob.status.label("status"),
                WorkflowJob.attempt_count.label("attempt_count"),
                WorkflowJob.max_attempts.label("max_attempts"),
                WorkflowJob.error_code.label("error_code"),
                recovery_count.label("recovery_count"),
                last_recovered_at.label("last_recovered_at"),
            )
            .join(WorkflowJob, WorkflowJob.id == WorkflowEvent.workflow_job_id)
            .where(
                WorkflowEvent.event_type == "job.lease_expired",
                WorkflowEvent.created_at >= cutoff,
                WorkflowEvent.workflow_job_id.is_not(None),
            )
            .group_by(
                WorkflowEvent.workflow_job_id,
                WorkflowJob.job_type,
                WorkflowJob.status,
                WorkflowJob.attempt_count,
                WorkflowJob.max_attempts,
                WorkflowJob.error_code,
            )
            .order_by(last_recovered_at.desc())
            .limit(25)
        )
        result = await self.session.execute(statement)
        return [dict(row) for row in result.mappings()]


def build_component_health(
    heartbeats: Sequence[RuntimeHeartbeat],
    *,
    reference_time: datetime,
    config: Settings,
    database_time_value: datetime | None = None,
    expected_component_ids: str = "",
) -> tuple[dict[str, ComponentOperationalHealth], dict[str, int]]:
    reference_time = normalize_utc(reference_time, field="component reference time")
    database_reference = normalize_utc(
        database_time_value or reference_time,
        field="database reference time",
    )
    expected = {value.strip() for value in (expected_component_ids or "").split(",") if value.strip()}
    latest: dict[str, RuntimeHeartbeat] = {}
    for heartbeat in sorted(
        heartbeats,
        key=lambda row: normalize_utc(row.observed_at, field="heartbeat observed_at"),
        reverse=True,
    ):
        latest.setdefault(str(heartbeat.component_id), heartbeat)

    components: dict[str, ComponentOperationalHealth] = {}
    healthy_job_coverage: dict[str, int] = {}
    for raw_id in sorted(expected | set(latest)):
        current_heartbeat = latest.get(raw_id)
        component_id = _safe_component_id(raw_id)
        if current_heartbeat is None:
            component_type = "scheduler" if "scheduler" in raw_id.casefold() else "worker"
            components[component_id] = ComponentOperationalHealth(
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
            continue

        component_type = _safe_component_type(getattr(current_heartbeat, "component_type", "unknown"))
        capabilities = _safe_capabilities(getattr(current_heartbeat, "capabilities", ()))
        observed_at = normalize_utc(current_heartbeat.observed_at, field="heartbeat observed_at")
        metadata = getattr(current_heartbeat, "runtime_metadata", None)
        metadata = metadata if isinstance(metadata, Mapping) else {}
        last_success_at = _metadata_timestamp(metadata, "last_success_at")
        active_started_at = _metadata_timestamp(metadata, "active_work_started_at")
        activity = str(metadata.get("state", "unknown"))
        if activity not in {"idle", "working", "ticking"}:
            activity = "unknown"
        active_work_type = _safe_job_type(metadata.get("active_work_type"))
        process_started_at = _metadata_timestamp(metadata, "process_started_at")
        restart_times = _metadata_timestamps(metadata, "restart_observed_at")
        restart_window_start = reference_time - timedelta(seconds=config.restart_warning_window_seconds)
        recent_restarts = tuple(
            value
            for value in restart_times
            if restart_window_start <= value <= database_reference + timedelta(seconds=1)
        )
        if process_started_at is None:
            restart_state = RestartState.UNKNOWN
        elif len(recent_restarts) >= config.restart_warning_count:
            restart_state = RestartState.CRASH_LOOP
        elif recent_restarts:
            restart_state = RestartState.RECOVERED
        else:
            restart_state = RestartState.STABLE
        heartbeat_age = max(0.0, (reference_time - observed_at).total_seconds())
        success_age = (
            max(0.0, (reference_time - last_success_at).total_seconds()) if last_success_at is not None else None
        )
        active_age = (
            max(0.0, (reference_time - active_started_at).total_seconds()) if active_started_at is not None else None
        )

        if observed_at > database_reference + timedelta(seconds=1):
            state = HealthState.UNKNOWN
            code = "heartbeat_clock_skew"
            message = "Heartbeat timestamp is outside the trusted database clock boundary"
        else:
            fresh_seconds, unavailable_seconds = _component_thresholds(component_type, config)
            if heartbeat_age <= fresh_seconds:
                state = HealthState.HEALTHY
                code = "heartbeat_fresh"
                message = "Heartbeat is fresh"
            elif heartbeat_age <= unavailable_seconds:
                state = HealthState.STALE
                code = "heartbeat_stale"
                message = "Heartbeat is stale"
            else:
                state = HealthState.UNAVAILABLE
                code = "heartbeat_unavailable"
                message = "Heartbeat is older than the unavailable threshold"
            if state == HealthState.HEALTHY and active_age is not None and active_age > config.job_stuck_seconds:
                state = HealthState.STALE
                code = "active_work_overdue"
                message = "Runtime heartbeat is fresh but active work has exceeded its progress threshold"
            if state == HealthState.HEALTHY and restart_state == RestartState.CRASH_LOOP:
                state = HealthState.STALE
                code = "restart_rate_high"
                message = "Process restart rate exceeds the configured warning threshold"

        job_types = _safe_job_types(metadata.get("job_types"))
        if state == HealthState.HEALTHY:
            for job_type in job_types:
                healthy_job_coverage[job_type] = healthy_job_coverage.get(job_type, 0) + 1
        components[component_id] = ComponentOperationalHealth(
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
    return components, healthy_job_coverage


def build_queue_health(
    rows: Sequence[Mapping[str, Any]],
    *,
    generated_at: datetime,
    healthy_job_coverage: Mapping[str, int],
    config: Settings,
) -> list[QueueOperationalHealth]:
    generated_at = normalize_utc(generated_at, field="queue generated_at")
    queues: list[QueueOperationalHealth] = []
    for row in rows:
        job_type = _safe_job_type(row.get("job_type")) or "unknown"
        due_count = int(row.get("due_count") or 0)
        oldest_due_at = row.get("oldest_due_at")
        if isinstance(oldest_due_at, datetime):
            oldest_due_at = normalize_utc(oldest_due_at, field="oldest_due_at")
            oldest_due_age = max(0.0, (generated_at - oldest_due_at).total_seconds())
        else:
            oldest_due_at = None
            oldest_due_age = None
        running_count = int(row.get("running_count") or 0)
        expired_lease_count = int(row.get("expired_lease_count") or 0)
        stale_running_count = int(row.get("stale_running_count") or 0)
        overdue_running_count = int(row.get("overdue_running_count") or 0)
        excessive_retry_count = int(row.get("excessive_retry_count") or 0)
        exhausted_active_count = int(row.get("exhausted_active_count") or 0)
        failed_count = int(row.get("failed_count") or 0)
        needs_review_count = int(row.get("needs_review_count") or 0)
        healthy_workers = int(healthy_job_coverage.get(job_type, 0))
        warning_seconds, unavailable_seconds = _queue_thresholds(job_type)

        state = HealthState.HEALTHY
        code = "queue_healthy"
        message = "No queue execution anomaly is present"
        if exhausted_active_count:
            state, code, message = (
                HealthState.UNAVAILABLE,
                "active_retry_exhausted",
                "Active jobs have exhausted their configured attempts",
            )
        elif expired_lease_count:
            state, code, message = (
                HealthState.UNAVAILABLE,
                "expired_running_lease",
                "A running job has an expired lease",
            )
        elif due_count and healthy_workers == 0:
            state, code, message = (
                HealthState.UNAVAILABLE,
                "no_compatible_worker",
                "Due work has no fresh compatible worker",
            )
        elif oldest_due_age is not None and oldest_due_age > unavailable_seconds:
            state, code, message = (
                HealthState.UNAVAILABLE,
                "due_work_overdue",
                "Oldest due work exceeds the unavailable queue threshold",
            )
        elif stale_running_count or overdue_running_count:
            state, code, message = (
                HealthState.STALE,
                "running_work_stale",
                "Running work has stale lease progress or excessive duration",
            )
        elif oldest_due_age is not None and oldest_due_age > warning_seconds:
            state, code, message = (
                HealthState.STALE,
                "due_work_stale",
                "Oldest due work exceeds the warning queue threshold",
            )
        elif excessive_retry_count:
            state, code, message = (
                HealthState.STALE,
                "retry_pressure",
                "Active work is near its configured retry limit",
            )
        queues.append(
            QueueOperationalHealth(
                job_type=job_type,
                state=state,
                code=code,
                due_count=due_count,
                oldest_due_at=oldest_due_at,
                oldest_due_age_seconds=oldest_due_age,
                running_count=running_count,
                expired_lease_count=expired_lease_count,
                stale_running_count=stale_running_count,
                overdue_running_count=overdue_running_count,
                excessive_retry_count=excessive_retry_count,
                exhausted_active_count=exhausted_active_count,
                failed_count=failed_count,
                needs_review_count=needs_review_count,
                healthy_compatible_workers=healthy_workers,
                message=message,
                runbook_url=f"{RUNBOOK_ROOT}#queue-and-lease-anomalies",
            )
        )
    return queues


def build_recovery_health(
    rows: Sequence[Mapping[str, Any]],
    *,
    config: Settings,
) -> list[JobRecoveryOperationalHealth]:
    recoveries: list[JobRecoveryOperationalHealth] = []
    for row in rows:
        last_recovered_at = row.get("last_recovered_at")
        if not isinstance(last_recovered_at, datetime):
            continue
        job_id = _safe_job_id(row.get("job_id"))
        job_type = _safe_job_type(row.get("job_type")) or "unknown"
        status = str(row.get("status") or "unknown").casefold()
        recovery_count = max(1, int(row.get("recovery_count") or 0))
        attempt_count = max(0, int(row.get("attempt_count") or 0))
        max_attempts = max(1, int(row.get("max_attempts") or 1))
        error_code = str(row.get("error_code") or "")
        if status == JobStatus.FAILED and error_code == "worker_lease_expired":
            state = HealthState.UNAVAILABLE
            code = "poison_job_terminal"
            message = "A process-interrupted job exhausted its bounded attempts"
        elif status == JobStatus.NEEDS_REVIEW:
            state = HealthState.UNAVAILABLE
            code = "recovery_requires_review"
            message = "A recovered job requires operator review before further execution"
        elif recovery_count >= config.recovery_warning_count:
            state = HealthState.STALE
            code = "repeated_lease_recovery"
            message = "A job has required repeated lease recovery"
        else:
            state = HealthState.HEALTHY
            code = "lease_recovered"
            message = "A job lease was recovered within its bounded attempt policy"
        recoveries.append(
            JobRecoveryOperationalHealth(
                job_id=job_id,
                job_type=job_type,
                state=state,
                code=code,
                recovery_count=recovery_count,
                attempt_count=attempt_count,
                max_attempts=max_attempts,
                status=status,
                last_recovered_at=normalize_utc(
                    last_recovered_at,
                    field="last_recovered_at",
                ),
                message=message,
                runbook_url=f"{RUNBOOK_ROOT}#poison-and-repeated-recovery",
            )
        )
    return recoveries


def _operational_snapshot(
    generated_at: datetime,
    dependencies: dict[str, DependencyHealth],
    components: dict[str, ComponentOperationalHealth],
    queues: list[QueueOperationalHealth],
    recoveries: list[JobRecoveryOperationalHealth],
) -> OperationalHealthSnapshot:
    alerts: list[OperationalAlert] = []
    for name, dependency in sorted(dependencies.items()):
        if dependency.state != HealthState.HEALTHY:
            alerts.append(
                OperationalAlert(
                    code=dependency.code,
                    state=dependency.state,
                    scope=f"dependency:{name}",
                    message=dependency.message,
                    runbook_url=dependency.runbook_url,
                )
            )
    for component in components.values():
        if component.state != HealthState.HEALTHY:
            alerts.append(
                OperationalAlert(
                    code=component.code,
                    state=component.state,
                    scope=f"component:{component.component_id}",
                    message=component.message,
                    runbook_url=component.runbook_url,
                )
            )
    for queue in queues:
        if queue.state != HealthState.HEALTHY:
            alerts.append(
                OperationalAlert(
                    code=queue.code,
                    state=queue.state,
                    scope=f"queue:{queue.job_type}",
                    message=queue.message,
                    runbook_url=queue.runbook_url,
                )
            )
    for recovery in recoveries:
        if recovery.state != HealthState.HEALTHY:
            alerts.append(
                OperationalAlert(
                    code=recovery.code,
                    state=recovery.state,
                    scope=f"job:{recovery.job_id}",
                    message=recovery.message,
                    runbook_url=recovery.runbook_url,
                )
            )
    states = [item.state for item in dependencies.values()]
    states.extend(item.state for item in components.values())
    states.extend(item.state for item in queues)
    states.extend(item.state for item in recoveries)
    state = _worst_state(states)
    metrics: dict[str, int | float] = {
        "dependencies_unavailable": sum(item.state == HealthState.UNAVAILABLE for item in dependencies.values()),
        "components_stale": sum(item.state == HealthState.STALE for item in components.values()),
        "components_unavailable": sum(item.state == HealthState.UNAVAILABLE for item in components.values()),
        "components_unknown": sum(item.state == HealthState.UNKNOWN for item in components.values()),
        "due_jobs": sum(item.due_count for item in queues),
        "expired_leases": sum(item.expired_lease_count for item in queues),
        "stale_running_jobs": sum(item.stale_running_count + item.overdue_running_count for item in queues),
        "retry_pressure_jobs": sum(item.excessive_retry_count for item in queues),
        "workerless_due_job_types": sum(item.code == "no_compatible_worker" for item in queues),
        "component_restarts_window": sum(item.restart_count_window for item in components.values()),
        "crash_loop_components": sum(item.restart_state == RestartState.CRASH_LOOP for item in components.values()),
        "lease_recoveries_recent": sum(item.recovery_count for item in recoveries),
        "repeated_recovery_jobs": sum(item.code == "repeated_lease_recovery" for item in recoveries),
        "poison_jobs_terminal": sum(item.code == "poison_job_terminal" for item in recoveries),
    }
    return OperationalHealthSnapshot(
        generated_at=generated_at,
        state=state,
        state_definitions=dict(STATE_DEFINITIONS),
        dependencies=dependencies,
        components=components,
        queues=queues,
        recoveries=recoveries,
        alerts=alerts,
        metrics=metrics,
        outbound_proxy=safe_proxy_diagnostics(),
    )


def _readiness_snapshot(
    generated_at: datetime,
    checks: dict[str, DependencyHealth],
    required_capabilities: tuple[str, ...],
) -> ReadinessSnapshot:
    ready = all(check.state == HealthState.HEALTHY for check in checks.values())
    return ReadinessSnapshot(
        status="ready" if ready else "unavailable",
        generated_at=generated_at,
        checks=checks,
        required_capabilities=required_capabilities,
    )


def _capability_dependency(
    capability: str,
    *,
    available: bool,
    observed_at: datetime,
    unknown: bool = False,
) -> DependencyHealth:
    state = HealthState.UNKNOWN if unknown else HealthState.HEALTHY if available else HealthState.UNAVAILABLE
    code = "capability_unknown" if unknown else "capability_available" if available else "capability_unavailable"
    message = (
        "Capability state could not be verified"
        if unknown
        else "A fresh worker provides the required capability"
        if available
        else "No fresh worker provides the required capability"
    )
    return DependencyHealth(
        state=state,
        code=code,
        observed_at=observed_at,
        latency_ms=0,
        message=message,
        runbook_url=f"{RUNBOOK_ROOT}#capability-unavailable",
    )


def _component_thresholds(component_type: str, config: Settings) -> tuple[int, int]:
    if component_type == "scheduler":
        return config.scheduler_health_fresh_seconds, config.scheduler_health_unavailable_seconds
    return config.worker_health_fresh_seconds, config.worker_health_unavailable_seconds


def _queue_thresholds(job_type: str) -> tuple[int, int]:
    normalized = job_type.casefold()
    if "publish" in normalized or normalized == "manual_intake":
        return 120, 300
    if any(value in normalized for value in ("source", "ingest", "generation", "content_pack", "research", "route")):
        return 300, 900
    return 600, 1_800


def _configured_capabilities(value: str) -> tuple[str, ...]:
    """Split the value the settings validator already casefolded, sorted and vetted."""
    return tuple(part for part in value.split(",") if part)


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
    return tuple(
        sorted({str(value).casefold() for value in values if str(value).casefold() in READINESS_CAPABILITIES})
    )


def _safe_job_types(values: object) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return ()
    safe: set[str] = set()
    for value in values:
        candidate = _safe_job_type(value)
        if candidate is not None:
            safe.add(candidate)
    return tuple(sorted(safe))


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


def _metadata_timestamps(
    metadata: Mapping[str, object],
    key: str,
) -> tuple[datetime, ...]:
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


def _safe_job_id(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except TypeError, ValueError, AttributeError:
        digest = hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:12]
        return f"job-{digest}"


def _worst_state(states: Sequence[HealthState]) -> HealthState:
    for state in (HealthState.UNAVAILABLE, HealthState.STALE, HealthState.UNKNOWN):
        if state in states:
            return state
    return HealthState.HEALTHY


def render_prometheus_metrics(snapshot: OperationalHealthSnapshot) -> str:
    """Render fixed-name, sanitized operational gauges without payload/error labels."""
    lines = [
        "# TYPE newscraft_health_state gauge",
        f'newscraft_health_state{{state="{snapshot.state.value}"}} 1',
    ]
    for name, value in sorted(snapshot.metrics.items()):
        lines.append(f"# TYPE newscraft_{name} gauge")
        lines.append(f"newscraft_{name} {value}")
    for component in snapshot.components.values():
        labels = f'component="{component.component_id}",type="{component.component_type}"'
        if component.heartbeat_age_seconds is not None:
            lines.append(f"newscraft_component_heartbeat_age_seconds{{{labels}}} {component.heartbeat_age_seconds}")
        if component.last_success_age_seconds is not None:
            lines.append(
                f"newscraft_component_last_success_age_seconds{{{labels}}} {component.last_success_age_seconds}"
            )
        lines.append(f"newscraft_component_restarts_window{{{labels}}} {component.restart_count_window}")
    for queue in snapshot.queues:
        label = f'job_type="{queue.job_type}"'
        lines.append(f"newscraft_queue_due_jobs{{{label}}} {queue.due_count}")
        lines.append(f"newscraft_queue_running_jobs{{{label}}} {queue.running_count}")
        lines.append(f"newscraft_queue_expired_leases{{{label}}} {queue.expired_lease_count}")
        if queue.oldest_due_age_seconds is not None:
            lines.append(f"newscraft_queue_oldest_due_age_seconds{{{label}}} {queue.oldest_due_age_seconds}")
    return "\n".join(lines) + "\n"
