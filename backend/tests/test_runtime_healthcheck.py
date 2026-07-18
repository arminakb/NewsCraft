from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.jobs import healthcheck

NOW = datetime(2026, 7, 17, 8, 30, tzinfo=UTC)


class SessionContext:
    def __init__(self, heartbeat=None, *, failure: Exception | None = None):
        self.heartbeat = heartbeat
        self.failure = failure

    async def __aenter__(self):
        if self.failure is not None:
            raise self.failure
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, _model, _identity):
        return self.heartbeat

    async def scalar(self, _statement):
        return NOW


def _heartbeat(
    component_type: str,
    observed_at: datetime,
    *,
    component_id: str | None = None,
    capabilities: tuple[str, ...] | None = None,
    job_types: tuple[str, ...] | None = None,
):
    scheduler = component_type == "scheduler"
    return SimpleNamespace(
        component_id=component_id or component_type,
        component_type=component_type,
        capabilities=list(
            capabilities if capabilities is not None else (("scheduling",) if scheduler else ("ingestion", "source"))
        ),
        observed_at=observed_at,
        runtime_metadata={
            "job_types": list(
                job_types if job_types is not None else (() if scheduler else ("ingest.collect", "manual_intake"))
            )
        },
    )


async def _check(monkeypatch, heartbeat, *, component_type="worker", limit=120):
    monkeypatch.setattr(healthcheck, "async_session", lambda: SessionContext(heartbeat))
    return await healthcheck.check_component(
        component_type,
        limit,
        component_id=component_type,
        expected_capabilities=(("scheduling",) if component_type == "scheduler" else ("ingestion", "source")),
        expected_job_types=(() if component_type == "scheduler" else ("ingest.collect", "manual_intake")),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("component_type", "age", "limit", "expected"),
    [
        ("worker", 120, 120, 0),
        ("worker", 121, 120, 1),
        ("scheduler", 90, 90, 0),
        ("scheduler", 91, 90, 1),
    ],
)
async def test_component_healthcheck_uses_database_clock_and_exact_age_boundary(
    monkeypatch,
    component_type,
    age,
    limit,
    expected,
):
    session = SessionContext(_heartbeat(component_type, NOW - timedelta(seconds=age)))
    monkeypatch.setattr(healthcheck, "async_session", lambda: session)

    assert (
        await healthcheck.check_component(
            component_type,
            limit,
            component_id=component_type,
            expected_capabilities=(("scheduling",) if component_type == "scheduler" else ("ingestion", "source")),
            expected_job_types=(() if component_type == "scheduler" else ("ingest.collect", "manual_intake")),
        )
        == expected
    )


@pytest.mark.asyncio
async def test_component_healthcheck_fails_closed_for_missing_wrong_or_database_failure(monkeypatch):
    monkeypatch.setattr(healthcheck, "async_session", lambda: SessionContext())
    assert await _check(monkeypatch, None) == 1

    assert await _check(monkeypatch, _heartbeat("scheduler", NOW)) == 1

    monkeypatch.setattr(
        healthcheck,
        "async_session",
        lambda: SessionContext(failure=RuntimeError("token=healthcheck-canary")),
    )
    assert (
        await healthcheck.check_component(
            "worker",
            120,
            component_id="worker",
            expected_capabilities=("ingestion", "source"),
            expected_job_types=("ingest.collect", "manual_intake"),
        )
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "heartbeat",
    [
        _heartbeat("worker", NOW, component_id="different-worker"),
        _heartbeat("worker", NOW, capabilities=("publishing",)),
        _heartbeat("worker", NOW, job_types=("telegram.publish",)),
        SimpleNamespace(
            component_id="worker",
            component_type="worker",
            capabilities=["ingestion", "source"],
            observed_at=NOW,
            runtime_metadata={},
        ),
    ],
)
async def test_component_healthcheck_rejects_wrong_identity_capabilities_or_claimable_jobs(
    monkeypatch,
    heartbeat,
):
    assert await _check(monkeypatch, heartbeat) == 1


@pytest.mark.asyncio
async def test_component_healthcheck_accepts_fresh_exact_worker_and_scheduler(monkeypatch):
    assert await _check(monkeypatch, _heartbeat("worker", NOW)) == 0
    assert (
        await _check(
            monkeypatch,
            _heartbeat("scheduler", NOW),
            component_type="scheduler",
            limit=90,
        )
        == 0
    )


def test_healthcheck_cli_failure_output_is_sanitized(monkeypatch, capsys):
    monkeypatch.setattr(
        healthcheck,
        "async_session",
        lambda: SessionContext(failure=RuntimeError("token=healthcheck-output-canary")),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "healthcheck",
            "--component-id",
            "worker-source-generation",
            "--component-type",
            "worker",
            "--expected-capabilities",
            "generation,ingestion,source",
            "--expected-job-types",
            "ingest.collect",
            "--max-age-seconds",
            "120",
        ],
    )

    with pytest.raises(SystemExit) as raised:
        healthcheck.main()

    assert raised.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
