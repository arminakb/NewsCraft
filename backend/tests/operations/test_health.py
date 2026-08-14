from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.operations.health as health_module
from app.core.config import Settings
from app.db.schema import SCHEMA_HEAD
from app.operations.health import (
    DependencyHealth,
    HealthState,
    ReadinessService,
    RestartState,
    SecretReadinessService,
    build_component_health,
    build_queue_health,
    build_recovery_health,
    normalize_utc,
    probe_storage_directory,
    render_prometheus_metrics,
    snapshot_high_water,
)
from app.security.secret_store import SecretStoreRuntime

NOW = datetime(2026, 7, 17, 8, 30, 0, 654321, tzinfo=UTC)


class Rows:
    def __init__(self, values):
        self.values = list(values)

    def __iter__(self):
        return iter(self.values)


@pytest.mark.asyncio
async def test_storage_probe_resolves_default_timeout_at_call_time(tmp_path, monkeypatch):
    observed: dict[str, float] = {}

    class Deadline:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    def timeout(seconds: float):
        observed["seconds"] = seconds
        return Deadline()

    async def to_thread(_function):
        return True

    monkeypatch.setattr(
        health_module,
        "settings",
        SimpleNamespace(health_storage_timeout_seconds=1.25),
    )
    monkeypatch.setattr(health_module.asyncio, "timeout", timeout)
    monkeypatch.setattr(health_module.asyncio, "to_thread", to_thread)

    result = await probe_storage_directory("media_storage", tmp_path, NOW)

    assert result.state == HealthState.HEALTHY
    assert observed == {"seconds": 1.25}


class ReadinessSession:
    def __init__(
        self,
        *,
        heartbeats=(),
        failure: Exception | None = None,
        schema=SCHEMA_HEAD,
        secret_relation="encrypted_secrets",
    ):
        self.heartbeats = list(heartbeats)
        self.failure = failure
        self.schema = schema
        self.secret_relation = secret_relation

    async def scalar(self, statement):
        if self.failure is not None:
            raise self.failure
        sql = str(statement)
        if sql == "SELECT 1":
            return 1
        if "alembic_version" in sql:
            return self.schema
        if "clock_timestamp" in sql:
            return NOW
        if "to_regclass" in sql:
            return self.secret_relation
        raise AssertionError(f"unexpected scalar query: {sql}")

    async def scalars(self, statement):
        assert "runtime_heartbeats" in str(statement)
        return Rows(self.heartbeats)


def _heartbeat(
    component_id: str,
    observed_at: datetime,
    *,
    component_type: str = "worker",
    capabilities=("source",),
    metadata=None,
):
    return SimpleNamespace(
        component_id=component_id,
        component_type=component_type,
        capabilities=list(capabilities),
        observed_at=observed_at,
        runtime_metadata=metadata
        or {
            "job_types": ["ingest.collect"],
            "state": "idle",
            "last_success_at": observed_at.isoformat(),
            "active_work_started_at": None,
            "active_work_type": None,
        },
    )


def _config(tmp_path, **changes) -> Settings:
    values = {
        "media_root": str(tmp_path / "media"),
        "export_root": str(tmp_path / "exports"),
        "expected_runtime_component_ids": "",
    }
    values.update(changes)
    return Settings(**values)


def _master_key(byte: int = 2) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


def _dependency(name: str, state: HealthState, observed_at: datetime) -> DependencyHealth:
    return DependencyHealth(
        state=state,
        code=f"{name}_{state}",
        observed_at=observed_at,
        latency_ms=0,
        message=f"{name} {state}",
        runbook_url="/docs/operations/readiness-and-health",
    )


@pytest.mark.asyncio
async def test_readiness_succeeds_for_database_schema_storage_and_required_capability(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "exports").mkdir()
    session = ReadinessSession(heartbeats=[_heartbeat("worker-source-generation", NOW)])

    snapshot = await ReadinessService(
        session,
        config=_config(tmp_path, readiness_required_capabilities="source"),
        clock=lambda: NOW - timedelta(microseconds=1),
    ).snapshot()

    assert snapshot.status == "ready"
    assert snapshot.generated_at == NOW
    assert set(snapshot.checks) == {
        "database",
        "schema",
        "media_storage",
        "export_storage",
        "capability:source",
    }
    assert all(check.state == HealthState.HEALTHY for check in snapshot.checks.values())


class ConcurrentHeartbeatSession(ReadinessSession):
    """clock_timestamp() advances while a worker commits a heartbeat mid-request.

    Models READ COMMITTED reality: the heartbeat row lands after the request
    starts, so it legitimately postdates any clock read taken before the
    heartbeat query.
    """

    def __init__(self, *, clock_before, clock_after, **kwargs):
        super().__init__(**kwargs)
        self.clock_before = clock_before
        self.clock_after = clock_after
        self.heartbeats_read = False

    async def scalar(self, statement):
        if "clock_timestamp" in str(statement):
            return self.clock_after if self.heartbeats_read else self.clock_before
        return await super().scalar(statement)

    async def scalars(self, statement):
        rows = await super().scalars(statement)
        self.heartbeats_read = True
        return rows


@pytest.mark.asyncio
async def test_readiness_reads_the_database_clock_after_heartbeats(tmp_path):
    """A heartbeat committed during the request must not read as clock skew.

    Regression: readiness used to read database_time() BEFORE list_recent and
    pass it as reference_time with no database_time_value, the inverse of
    OperationalHealthService, so a heartbeat committed in between exceeded the
    1s tolerance and turned the capability check into a 503.
    """

    (tmp_path / "media").mkdir()
    (tmp_path / "exports").mkdir()
    session = ConcurrentHeartbeatSession(
        clock_before=NOW,
        clock_after=NOW + timedelta(seconds=3),
        heartbeats=[_heartbeat("worker-source-generation", NOW + timedelta(seconds=2))],
    )

    snapshot = await ReadinessService(
        session,
        config=_config(tmp_path, readiness_required_capabilities="source"),
        clock=lambda: NOW,
    ).snapshot()

    assert session.heartbeats_read is True
    assert snapshot.status == "ready"
    assert snapshot.checks["capability:source"].state == HealthState.HEALTHY
    assert snapshot.checks["capability:source"].code == "capability_available"


@pytest.mark.asyncio
async def test_readiness_fails_when_configured_required_capability_has_no_fresh_worker(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "exports").mkdir()
    session = ReadinessSession(heartbeats=[_heartbeat("worker-source-generation", NOW - timedelta(seconds=61))])

    snapshot = await ReadinessService(
        session,
        config=_config(tmp_path, readiness_required_capabilities="source"),
        clock=lambda: NOW,
    ).snapshot()

    assert snapshot.status == "unavailable"
    assert snapshot.checks["capability:source"].state == HealthState.UNAVAILABLE
    assert snapshot.checks["capability:source"].code == "capability_unavailable"


@pytest.mark.asyncio
async def test_readiness_fails_closed_on_database_failure_without_exposing_exception(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "exports").mkdir()
    snapshot = await ReadinessService(
        ReadinessSession(failure=RuntimeError("postgresql://user:password@host/db?token=db-canary")),
        config=_config(tmp_path),
        clock=lambda: NOW,
    ).snapshot()

    rendered = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True)
    assert snapshot.status == "unavailable"
    assert snapshot.checks["database"].state == HealthState.UNAVAILABLE
    assert snapshot.checks["schema"].state == HealthState.UNKNOWN
    assert "db-canary" not in rendered
    assert "password" not in rendered


@pytest.mark.asyncio
async def test_readiness_reports_unavailable_required_storage(tmp_path):
    (tmp_path / "media").mkdir()
    snapshot = await ReadinessService(
        ReadinessSession(),
        config=_config(tmp_path),
        clock=lambda: NOW,
    ).snapshot()

    assert snapshot.status == "unavailable"
    assert snapshot.checks["media_storage"].state == HealthState.HEALTHY
    assert snapshot.checks["export_storage"].state == HealthState.UNAVAILABLE


@pytest.mark.asyncio
async def test_readiness_reports_schema_mismatch_as_unavailable(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "exports").mkdir()
    snapshot = await ReadinessService(
        ReadinessSession(schema="outdated-revision"),
        config=_config(tmp_path),
        clock=lambda: NOW,
    ).snapshot()

    assert snapshot.status == "unavailable"
    assert snapshot.checks["database"].state == HealthState.HEALTHY
    assert snapshot.checks["schema"].state == HealthState.UNAVAILABLE
    assert snapshot.checks["schema"].code == "schema_mismatch"


@pytest.mark.asyncio
async def test_secret_readiness_distinguishes_database_schema_configuration_and_initialization(tmp_path):
    config = _config(tmp_path, secret_master_key=_master_key())
    runtime = SecretStoreRuntime.from_settings(config)

    snapshot = await SecretReadinessService(
        ReadinessSession(),
        runtime=runtime,
        config=config,
        clock=lambda: NOW,
    ).snapshot()

    assert snapshot.status == "ready"
    assert set(snapshot.checks) == {
        "database",
        "secret_schema",
        "encryption_configuration",
        "secret_store",
    }
    assert snapshot.checks["database"].code == "database_connected"
    assert snapshot.checks["secret_schema"].code == "secret_schema_available"
    assert snapshot.checks["encryption_configuration"].code == "secret_store_configuration_valid"
    assert snapshot.checks["secret_store"].code == "secret_store_initialized"


@pytest.mark.asyncio
async def test_secret_readiness_reports_missing_key_and_missing_table_separately(tmp_path):
    config = _config(tmp_path, secret_master_key=None)

    snapshot = await SecretReadinessService(
        ReadinessSession(secret_relation=None),
        runtime=SecretStoreRuntime.from_settings(config),
        config=config,
        clock=lambda: NOW,
    ).snapshot()

    assert snapshot.status == "unavailable"
    assert snapshot.checks["database"].state == HealthState.HEALTHY
    assert snapshot.checks["secret_schema"].code == "secret_schema_unavailable"
    assert snapshot.checks["encryption_configuration"].code == "secret_store_configuration_invalid"
    assert snapshot.checks["secret_store"].code == "secret_store_unavailable"


@pytest.mark.asyncio
async def test_storage_probe_checks_directory_read_and_traverse_access(tmp_path):
    available = tmp_path / "available"
    available.mkdir()
    assert (await probe_storage_directory("media_storage", available, NOW)).state == HealthState.HEALTHY
    assert (await probe_storage_directory("media_storage", tmp_path / "missing", NOW)).state == HealthState.UNAVAILABLE


def test_worker_heartbeat_fresh_stale_unavailable_and_unknown_boundaries(tmp_path):
    config = _config(tmp_path)
    heartbeats = [
        _heartbeat("fresh", NOW - timedelta(seconds=60)),
        _heartbeat("stale", NOW - timedelta(seconds=60, microseconds=1)),
        _heartbeat("stale-edge", NOW - timedelta(seconds=120)),
        _heartbeat("unavailable", NOW - timedelta(seconds=120, microseconds=1)),
    ]

    components, coverage = build_component_health(
        heartbeats,
        reference_time=NOW,
        config=config,
        expected_component_ids="missing",
    )

    assert components["fresh"].state == HealthState.HEALTHY
    assert components["stale"].state == HealthState.STALE
    assert components["stale-edge"].state == HealthState.STALE
    assert components["unavailable"].state == HealthState.UNAVAILABLE
    assert components["missing"].state == HealthState.UNKNOWN
    assert coverage == {"ingest.collect": 1}


def test_scheduler_heartbeat_uses_scheduler_specific_boundaries(tmp_path):
    config = _config(tmp_path)
    heartbeats = [
        _heartbeat("fresh", NOW - timedelta(seconds=45), component_type="scheduler", capabilities=("scheduling",)),
        _heartbeat(
            "stale",
            NOW - timedelta(seconds=45, microseconds=1),
            component_type="scheduler",
            capabilities=("scheduling",),
        ),
        _heartbeat(
            "unavailable",
            NOW - timedelta(seconds=90, microseconds=1),
            component_type="scheduler",
            capabilities=("scheduling",),
        ),
    ]

    components, _coverage = build_component_health(heartbeats, reference_time=NOW, config=config)

    assert components["fresh"].state == HealthState.HEALTHY
    assert components["stale"].state == HealthState.STALE
    assert components["unavailable"].state == HealthState.UNAVAILABLE


def test_process_restart_history_reports_recovery_and_crash_loop_rate(tmp_path):
    config = _config(tmp_path, restart_warning_count=3)
    recovered = _heartbeat(
        "worker-recovered",
        NOW,
        metadata={
            "job_types": ["ingest.collect"],
            "state": "idle",
            "last_success_at": NOW.isoformat(),
            "process_started_at": (NOW - timedelta(minutes=2)).isoformat(),
            "process_instance_id": "must-not-be-projected",
            "restart_observed_at": [(NOW - timedelta(minutes=2)).isoformat()],
        },
    )
    crash_loop = _heartbeat(
        "worker-crash-loop",
        NOW,
        metadata={
            "job_types": ["ingest.collect"],
            "state": "idle",
            "last_success_at": NOW.isoformat(),
            "process_started_at": (NOW - timedelta(seconds=30)).isoformat(),
            "process_instance_id": "restart-canary-secret",
            "restart_observed_at": [
                (NOW - timedelta(minutes=3)).isoformat(),
                (NOW - timedelta(minutes=2)).isoformat(),
                (NOW - timedelta(minutes=1)).isoformat(),
            ],
        },
    )

    components, coverage = build_component_health(
        [recovered, crash_loop],
        reference_time=NOW,
        config=config,
    )

    assert components["worker-recovered"].restart_state == RestartState.RECOVERED
    assert components["worker-recovered"].restart_count_window == 1
    assert components["worker-recovered"].state == HealthState.HEALTHY
    assert components["worker-crash-loop"].restart_state == RestartState.CRASH_LOOP
    assert components["worker-crash-loop"].restart_count_window == 3
    assert components["worker-crash-loop"].state == HealthState.STALE
    assert components["worker-crash-loop"].code == "restart_rate_high"
    assert coverage == {"ingest.collect": 1}
    assert "canary" not in json.dumps({key: value.model_dump(mode="json") for key, value in components.items()})


def test_fresh_runtime_heartbeat_exposes_overdue_active_work_as_stale(tmp_path):
    heartbeat = _heartbeat(
        "worker-source-generation",
        NOW,
        metadata={
            "job_types": ["ingest.collect"],
            "state": "working",
            "active_work_type": "ingest.collect",
            "active_work_started_at": (NOW - timedelta(seconds=901)).isoformat(),
            "last_success_at": (NOW - timedelta(seconds=901)).isoformat(),
        },
    )

    components, coverage = build_component_health(
        [heartbeat],
        reference_time=NOW,
        config=_config(tmp_path),
    )

    assert components["worker-source-generation"].state == HealthState.STALE
    assert components["worker-source-generation"].code == "active_work_overdue"
    assert coverage == {}


def test_due_job_without_fresh_compatible_worker_is_immediately_unavailable(tmp_path):
    queues = build_queue_health(
        [_queue_row(job_type="ingest.collect", due_count=1, oldest_due_at=NOW)],
        generated_at=NOW,
        healthy_job_coverage={"telegram.publish": 1},
        config=_config(tmp_path),
    )

    assert queues[0].state == HealthState.UNAVAILABLE
    assert queues[0].code == "no_compatible_worker"
    assert queues[0].healthy_compatible_workers == 0


@pytest.mark.parametrize(
    ("changes", "state", "code"),
    [
        ({"expired_lease_count": 1}, HealthState.UNAVAILABLE, "expired_running_lease"),
        ({"overdue_running_count": 1}, HealthState.STALE, "running_work_stale"),
        ({"excessive_retry_count": 1}, HealthState.STALE, "retry_pressure"),
        ({"exhausted_active_count": 1}, HealthState.UNAVAILABLE, "active_retry_exhausted"),
    ],
)
def test_stuck_and_excessively_retried_jobs_are_explicit(tmp_path, changes, state, code):
    queues = build_queue_health(
        [_queue_row(**changes)],
        generated_at=NOW,
        healthy_job_coverage={"build_export": 1},
        config=_config(tmp_path),
    )
    assert queues[0].state == state
    assert queues[0].code == code


def test_due_age_warning_and_unavailable_boundaries_are_deterministic(tmp_path):
    config = _config(tmp_path)
    warning = build_queue_health(
        [_queue_row(due_count=1, oldest_due_at=NOW - timedelta(seconds=601))],
        generated_at=NOW,
        healthy_job_coverage={"build_export": 1},
        config=config,
    )[0]
    unavailable = build_queue_health(
        [_queue_row(due_count=1, oldest_due_at=NOW - timedelta(seconds=1801))],
        generated_at=NOW,
        healthy_job_coverage={"build_export": 1},
        config=config,
    )[0]

    assert (warning.state, warning.code) == (HealthState.STALE, "due_work_stale")
    assert (unavailable.state, unavailable.code) == (HealthState.UNAVAILABLE, "due_work_overdue")


def test_recovery_health_exposes_safe_repeated_and_terminal_poison_job_ids(tmp_path):
    repeated_id = "123e4567-e89b-42d3-a456-426614174000"
    terminal_id = "123e4567-e89b-42d3-a456-426614174001"
    recoveries = build_recovery_health(
        [
            {
                "job_id": repeated_id,
                "job_type": "build_export",
                "status": "queued",
                "attempt_count": 2,
                "max_attempts": 3,
                "error_code": None,
                "recovery_count": 2,
                "last_recovered_at": NOW,
            },
            {
                "job_id": terminal_id,
                "job_type": "telegram.publish",
                "status": "failed",
                "attempt_count": 3,
                "max_attempts": 3,
                "error_code": "worker_lease_expired",
                "recovery_count": 3,
                "last_recovered_at": NOW,
            },
        ],
        config=_config(tmp_path),
    )

    assert [(item.job_id, item.code, item.state) for item in recoveries] == [
        (repeated_id, "repeated_lease_recovery", HealthState.STALE),
        (terminal_id, "poison_job_terminal", HealthState.UNAVAILABLE),
    ]
    rendered = json.dumps([item.model_dump(mode="json") for item in recoveries])
    assert "worker_lease_expired" not in rendered


def test_health_output_omits_secret_values_references_payloads_and_raw_metadata(tmp_path):
    heartbeat = _heartbeat(
        "OPENROUTER_API_KEY",
        NOW,
        capabilities=("source", "TELEGRAM_DESTINATION_NEWS_TOKEN"),
        metadata={
            "job_types": ["ingest.collect", "credential_ref"],
            "state": "working",
            "active_work_type": "api_key",
            "active_work_started_at": NOW.isoformat(),
            "last_success_at": NOW.isoformat(),
            "payload": {"authorization": "Bearer health-canary"},
        },
    )

    components, coverage = build_component_health(
        [heartbeat],
        reference_time=NOW,
        config=_config(tmp_path),
    )
    rendered = json.dumps(
        {key: value.model_dump(mode="json") for key, value in components.items()},
        sort_keys=True,
    )

    assert list(components) == ["component-92df3a66daaf"]
    assert components["component-92df3a66daaf"].capabilities == ("source",)
    assert components["component-92df3a66daaf"].active_work_type is None
    assert coverage == {"ingest.collect": 1}
    for forbidden in (
        "OPENROUTER_API_KEY",
        "TELEGRAM_DESTINATION_NEWS_TOKEN",
        "credential_ref",
        "health-canary",
        "authorization",
        "payload",
    ):
        assert forbidden not in rendered


def test_prometheus_output_uses_only_sanitized_fixed_metrics(tmp_path):
    heartbeat = _heartbeat(
        "OPENROUTER_API_KEY",
        NOW,
        metadata={
            "job_types": ["ingest.collect", "credential_ref"],
            "state": "idle",
            "last_success_at": NOW.isoformat(),
            "payload": {"token": "metrics-canary"},
        },
    )
    components, coverage = build_component_health(
        [heartbeat],
        reference_time=NOW,
        config=_config(tmp_path),
    )
    queues = build_queue_health(
        [_queue_row(job_type="ingest.collect", due_count=1, oldest_due_at=NOW)],
        generated_at=NOW,
        healthy_job_coverage=coverage,
        config=_config(tmp_path),
    )
    from app.operations.health import _operational_snapshot

    snapshot = _operational_snapshot(
        NOW,
        {"database": _dependency("database", HealthState.HEALTHY, NOW)},
        components,
        queues,
        [],
    )
    rendered = render_prometheus_metrics(snapshot)

    assert "newscraft_component_heartbeat_age_seconds" in rendered
    assert "newscraft_queue_due_jobs" in rendered
    assert "newscraft_component_restarts_window" in rendered
    assert "component-92df3a66daaf" in rendered
    for forbidden in ("OPENROUTER_API_KEY", "credential_ref", "metrics-canary", "payload"):
        assert forbidden not in rendered


def test_timezone_and_microsecond_precision_are_normalized_without_truncation():
    tehran = timezone(timedelta(hours=3, minutes=30))
    local = datetime(2026, 7, 17, 12, 0, 0, 654321, tzinfo=tehran)
    normalized = normalize_utc(local, field="local")

    assert normalized == NOW
    assert normalized.microsecond == 654321
    assert snapshot_high_water(NOW - timedelta(microseconds=1), local) == NOW
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_utc(datetime(2026, 7, 17), field="naive")


def _queue_row(**changes):
    values = {
        "job_type": "build_export",
        "due_count": 0,
        "oldest_due_at": None,
        "running_count": 0,
        "expired_lease_count": 0,
        "stale_running_count": 0,
        "overdue_running_count": 0,
        "excessive_retry_count": 0,
        "exhausted_active_count": 0,
        "failed_count": 0,
        "needs_review_count": 0,
    }
    values.update(changes)
    return values
