from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.jobs.types import JobExecution, JobOrigin


def _claimed_job(*, job_type: str = "ingest.collect", payload=None):
    return SimpleNamespace(
        id=uuid4(),
        job_type=job_type,
        payload=payload or {"nested": {"items": ["one", "two"]}},
        attempt_count=1,
        max_attempts=3,
        origin=JobOrigin.AUTOMATION,
        lease_owner="worker-test",
        created_at=datetime(2026, 7, 11, 7, 0, tzinfo=UTC),
        scheduled_for=datetime(2026, 7, 11, 8, 0, tzinfo=UTC),
        priority=10,
        pause_sensitive=True,
    )


def test_execution_is_deeply_immutable_and_detached_from_source_payload():
    source = {"nested": {"items": ["one", "two"]}}
    execution = JobExecution.from_job(_claimed_job(payload=source))

    source["nested"]["items"].append("source-only")
    with pytest.raises(FrozenInstanceError):
        execution.job_type = "changed"
    with pytest.raises(TypeError):
        execution.payload["added"] = True
    with pytest.raises(TypeError):
        execution.payload["nested"]["added"] = True
    assert execution.payload["nested"]["items"] == ("one", "two")

    mutable = execution.payload_copy()
    mutable["nested"]["items"].append("copy-only")
    assert execution.payload["nested"]["items"] == ("one", "two")


def test_execution_rejects_secret_values_instead_of_mutating_handler_input():
    with pytest.raises(ValueError, match="secret value"):
        JobExecution.from_job(_claimed_job(payload={"api_key": "secret-canary"}))


def test_execution_preserves_validated_retention_preview_capability():
    execution = JobExecution.from_job(
        _claimed_job(
            job_type="execute_retention",
            payload={"run_id": str(uuid4()), "preview_token": "a" * 64},
        )
    )

    assert execution.payload_copy()["preview_token"] == "a" * 64
