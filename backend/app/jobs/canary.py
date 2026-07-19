from __future__ import annotations

import argparse
import asyncio
import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.db.session import async_session
from app.jobs.errors import PermanentJobError
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin, JobStatus, job_payload_copy

SOURCE_GENERATION_CANARY = "operations.canary.source_generation"
PUBLISHING_CANARY = "operations.canary.publishing"
CanaryTarget = Literal["source-generation", "publishing"]


class _CanaryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: CanaryTarget
    hold_seconds: float = Field(default=0, ge=0, le=60)


async def handle_worker_canary(
    job: JobExecution,
    _context: JobContext,
) -> dict[str, str]:
    try:
        payload = _CanaryPayload.model_validate(job_payload_copy(job))
    except Exception:
        raise PermanentJobError(
            code="worker_canary_payload_invalid",
            message="Worker canary payload is invalid",
        ) from None
    expected = _target_for_job_type(job.job_type)
    if payload.target != expected:
        raise PermanentJobError(
            code="worker_canary_target_mismatch",
            message="Worker canary target does not match its job type",
        )
    if payload.hold_seconds:
        await asyncio.sleep(payload.hold_seconds)
    return {"target": expected, "status": "completed"}


async def run_canary(
    target: CanaryTarget,
    *,
    wait_seconds: float,
    hold_seconds: float = 0,
    max_attempts: int = 1,
) -> int:
    job_type = _job_type_for_target(target)
    request_id = uuid4()
    async with async_session() as session:
        enqueued = await JobRepository(session).enqueue_job(
            job_type=job_type,
            payload={"target": target, "hold_seconds": hold_seconds},
            idempotency_key=f"operations:restart-canary:{request_id}",
            origin=JobOrigin.MANUAL,
            max_attempts=max_attempts,
            pause_sensitive=False,
        )
        job_id = enqueued.job.id
        await session.commit()

    deadline = asyncio.get_running_loop().time() + wait_seconds
    while asyncio.get_running_loop().time() <= deadline:
        async with async_session() as session:
            job = await session.get(WorkflowJob, job_id)
            if job is not None and job.status in {
                JobStatus.SUCCEEDED,
                JobStatus.FAILED,
                JobStatus.NEEDS_REVIEW,
                JobStatus.CANCELLED,
            }:
                print(
                    json.dumps(
                        {"job_id": str(job_id), "status": str(job.status)},
                        sort_keys=True,
                    )
                )
                return 0 if job.status == JobStatus.SUCCEEDED else 1
        await asyncio.sleep(0.5)
    print(json.dumps({"job_id": str(job_id), "status": "timeout"}, sort_keys=True))
    return 1


def _job_type_for_target(target: CanaryTarget) -> str:
    return SOURCE_GENERATION_CANARY if target == "source-generation" else PUBLISHING_CANARY


def _target_for_job_type(job_type: str) -> CanaryTarget:
    if job_type == SOURCE_GENERATION_CANARY:
        return "source-generation"
    if job_type == PUBLISHING_CANARY:
        return "publishing"
    raise PermanentJobError(
        code="worker_canary_job_type_invalid",
        message="Worker canary job type is invalid",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enqueue a no-side-effect worker restart canary")
    parser.add_argument(
        "--target",
        choices=("source-generation", "publishing"),
        required=True,
    )
    parser.add_argument("--wait-seconds", type=float, default=180.0)
    parser.add_argument("--hold-seconds", type=float, default=0)
    parser.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=1)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    if (
        arguments.wait_seconds <= 0
        or arguments.wait_seconds > 600
        or arguments.hold_seconds < 0
        or arguments.hold_seconds > 60
    ):
        raise SystemExit(2)
    raise SystemExit(
        asyncio.run(
            run_canary(
                arguments.target,
                wait_seconds=arguments.wait_seconds,
                hold_seconds=arguments.hold_seconds,
                max_attempts=arguments.max_attempts,
            )
        )
    )


if __name__ == "__main__":
    main()
