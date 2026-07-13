from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_settings import SettingsError

from app.core.config import Settings
from app.core.faults import FaultHit, InjectedFault, NoopFaultInjector, ScriptedFaultInjector
from app.jobs.registry import JobHandlerRegistry
from app.jobs.worker import WorkerRunner


def test_fault_injection_cannot_start_outside_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FAILURE_INJECTION_PROFILE", "worker_after_claim")

    with pytest.raises(SettingsError, match="failure injection requires APP_ENV=test"):
        Settings(_env_file=None)


def test_fault_injection_profile_is_accepted_only_for_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("FAILURE_INJECTION_PROFILE", "worker_after_claim")

    configured = Settings(_env_file=None)

    assert configured.app_env == "test"
    assert configured.failure_injection_profile == "worker_after_claim"


@pytest.mark.asyncio
async def test_noop_fault_injector_never_interrupts_a_named_point() -> None:
    await NoopFaultInjector().hit("worker.after_claim", {"job_id": str(uuid4())})


@pytest.mark.asyncio
async def test_scripted_fault_is_one_shot_and_records_only_redacted_metadata() -> None:
    secret = "fault-boundary-canary"
    job_id = uuid4()
    injector = ScriptedFaultInjector({"worker.after_claim": 1})

    with pytest.raises(InjectedFault) as raised:
        await injector.hit(
            "worker.after_claim",
            {
                "job_id": job_id,
                "authorization": f"Bearer {secret}",
                "nested": {"api_key": secret},
            },
        )

    assert raised.value.point == "worker.after_claim"
    assert raised.value.context == {
        "job_id": str(job_id),
        "authorization": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]"},
    }
    assert secret not in str(raised.value)
    assert secret not in repr(raised.value.context)
    assert injector.hits == (
        FaultHit(
            point="worker.after_claim",
            context=raised.value.context,
        ),
    )

    await injector.hit("worker.after_claim", {"job_id": job_id})

    assert len(injector.hits) == 2


@pytest.mark.asyncio
async def test_fault_injectors_reject_unknown_points() -> None:
    with pytest.raises(ValueError, match="unknown fault point"):
        await NoopFaultInjector().hit("worker.after_clam", {})
    with pytest.raises(ValueError, match="unknown fault point"):
        ScriptedFaultInjector({"worker.after_clam": 1})


@pytest.mark.asyncio
async def test_worker_before_heartbeat_fault_fires_before_repository_update() -> None:
    stop = asyncio.Event()
    repository_calls: list[dict[str, object]] = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def commit(self) -> None:
            return None

    class Repository:
        def __init__(self, session) -> None:
            self.session = session

        async def heartbeat_job(self, **kwargs) -> None:
            repository_calls.append(kwargs)
            stop.set()

    job_id = uuid4()
    started = asyncio.Event()
    injector = ScriptedFaultInjector({"worker.before_heartbeat": 1})
    runner = WorkerRunner(
        session_factory=Session,
        handler_registry=JobHandlerRegistry(),
        repository_factory=Repository,
        worker_id="worker-fault-test",
        capabilities=(),
        clock=lambda: datetime(2026, 7, 13, 8, 0, tzinfo=UTC),
        fault_injector=injector,
    )

    with pytest.raises(InjectedFault, match="worker.before_heartbeat"):
        await runner._lease_heartbeat_loop(job_id, stop, started)

    assert started.is_set()
    assert repository_calls == []
    assert injector.hits == (
        FaultHit(
            point="worker.before_heartbeat",
            context=injector.hits[0].context,
        ),
    )
    assert injector.hits[0].context["job_id"] == str(job_id)
