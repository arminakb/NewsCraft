from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.jobs.types import JobExecution, JobOrigin


def test_job_execution_preserves_explicit_automation_links_across_payload_updates():
    run_id = uuid4()
    node_run_id = uuid4()
    execution = JobExecution(
        id=uuid4(),
        job_type="telegram.route.dry_run",
        payload={"route_id": str(uuid4()), "force_review": True},
        attempt_count=1,
        max_attempts=3,
        origin=JobOrigin.MANUAL,
        lease_owner="source-worker",
        created_at=datetime.now(UTC),
        scheduled_for=None,
        priority=0,
        pause_sensitive=True,
        automation_run_id=run_id,
        automation_node_run_id=node_run_id,
    )

    continued = execution.with_payload({**execution.payload_copy(), "defer_sequence": 1})

    assert continued.automation_run_id == run_id
    assert continued.automation_node_run_id == node_run_id
    assert continued.payload_copy()["defer_sequence"] == 1
