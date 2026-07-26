from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.outbound_proxy import ProxyDiagnostics


class HealthState(StrEnum):
    HEALTHY = "healthy"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class RestartState(StrEnum):
    UNKNOWN = "unknown"
    STABLE = "stable"
    RECOVERED = "recovered"
    CRASH_LOOP = "crash_loop"


STATE_DEFINITIONS: dict[str, str] = {
    HealthState.HEALTHY: "The required observation is fresh and no hard operational anomaly is present.",
    HealthState.STALE: "The last trustworthy observation or progress is older than the warning threshold.",
    HealthState.UNAVAILABLE: "A required dependency or compatible execution path cannot currently serve work.",
    HealthState.UNKNOWN: "No trustworthy observation is available, or its timestamp/shape is invalid.",
}


class DependencyHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: HealthState
    code: str
    observed_at: datetime
    latency_ms: int = Field(ge=0)
    message: str
    runbook_url: str


class ComponentOperationalHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str
    component_type: str
    state: HealthState
    code: str
    observed_at: datetime | None
    last_success_at: datetime | None
    heartbeat_age_seconds: float | None = Field(default=None, ge=0)
    last_success_age_seconds: float | None = Field(default=None, ge=0)
    capabilities: tuple[str, ...] = ()
    activity: str
    active_work_type: str | None = None
    active_work_age_seconds: float | None = Field(default=None, ge=0)
    process_started_at: datetime | None = None
    restart_state: RestartState
    restart_count_window: int = Field(ge=0)
    restart_window_seconds: int = Field(ge=60)
    last_restart_at: datetime | None = None
    message: str
    runbook_url: str


class QueueOperationalHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: str
    state: HealthState
    code: str
    due_count: int = Field(ge=0)
    oldest_due_at: datetime | None
    oldest_due_age_seconds: float | None = Field(default=None, ge=0)
    running_count: int = Field(ge=0)
    expired_lease_count: int = Field(ge=0)
    stale_running_count: int = Field(ge=0)
    overdue_running_count: int = Field(ge=0)
    excessive_retry_count: int = Field(ge=0)
    exhausted_active_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    needs_review_count: int = Field(ge=0)
    healthy_compatible_workers: int = Field(ge=0)
    message: str
    runbook_url: str


class OperationalAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    state: HealthState
    scope: str
    message: str
    runbook_url: str


class JobRecoveryOperationalHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    job_type: str
    state: HealthState
    code: str
    recovery_count: int = Field(ge=1)
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    status: str
    last_recovered_at: datetime
    message: str
    runbook_url: str


class OperationalHealthSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    state: HealthState
    state_definitions: dict[str, str]
    dependencies: dict[str, DependencyHealth]
    components: dict[str, ComponentOperationalHealth]
    queues: list[QueueOperationalHealth]
    recoveries: list[JobRecoveryOperationalHealth]
    alerts: list[OperationalAlert]
    metrics: dict[str, int | float]
    outbound_proxy: ProxyDiagnostics


class ReadinessSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    generated_at: datetime
    checks: dict[str, DependencyHealth]
    required_capabilities: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


class Clock(Protocol):
    def __call__(self) -> datetime: ...


class StorageProbe(Protocol):
    async def __call__(self, name: str, path: Path, observed_at: datetime) -> DependencyHealth: ...


def normalize_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def snapshot_high_water(*values: datetime) -> datetime:
    if not values:
        raise ValueError("at least one snapshot timestamp is required")
    return max(normalize_utc(value, field="snapshot timestamp") for value in values)
