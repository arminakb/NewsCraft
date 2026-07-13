from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.generation.revision_fence import public_job_result
from app.jobs.errors import InvalidJobTransition
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobDetailOut, JobEventOut, JobListOut, JobOut, JobSummaryOut
from app.jobs.types import JobErrorClass, JobStatus

router = APIRouter()
SessionDependency = Depends(get_session)


@router.get("/jobs", response_model=JobListOut)
async def list_jobs(
    status: Annotated[list[JobStatus] | None, Query()] = None,
    job_type: str | None = None,
    error_class: JobErrorClass | None = None,
    limit: int = Query(100, ge=1, le=250),
    session: AsyncSession = SessionDependency,
):
    jobs = await JobRepository(session).list_jobs(
        statuses=tuple(status or ()),
        job_type=job_type,
        error_class=error_class,
        limit=limit,
    )
    return JobListOut(items=[JobOut.model_validate(job) for job in jobs])


@router.get("/jobs/summary", response_model=JobSummaryOut)
async def job_summary(session: AsyncSession = SessionDependency):
    start_of_today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    queued = await _count_jobs(session, WorkflowJob.status == JobStatus.QUEUED)
    running = await _count_jobs(session, WorkflowJob.status == JobStatus.RUNNING)
    attention = await _count_jobs(
        session,
        WorkflowJob.status.in_((JobStatus.FAILED, JobStatus.NEEDS_REVIEW)),
    )
    succeeded_today = await _count_jobs(
        session,
        WorkflowJob.status == JobStatus.SUCCEEDED,
        WorkflowJob.finished_at >= start_of_today,
    )
    return JobSummaryOut(
        queued=queued,
        running=running,
        attention=attention,
        succeeded_today=succeeded_today,
    )


@router.get("/jobs/{job_id}", response_model=JobDetailOut)
async def get_job(job_id: UUID, session: AsyncSession = SessionDependency):
    job = await JobRepository(session).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    events = list(
        await session.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.workflow_job_id == job_id)
            .order_by(WorkflowEvent.created_at.desc())
        )
    )
    public_job = JobOut.model_validate(job).model_dump()
    return JobDetailOut(
        **public_job,
        payload=redact_event_data(job.payload),
        result=redact_event_data(public_job_result(job.result)),
        events=[
            JobEventOut(
                id=event.id,
                event_type=event.event_type,
                actor=event.actor,
                event_data=redact_event_data(event.event_data),
                created_at=event.created_at,
            )
            for event in events
        ],
    )


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
async def retry_job(job_id: UUID, session: AsyncSession = SessionDependency):
    try:
        job = await JobRepository(session).retry_job(job_id=job_id)
    except InvalidJobTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.refresh(job)
    response = JobOut.model_validate(job)
    await session.commit()
    return response


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: UUID, session: AsyncSession = SessionDependency):
    try:
        job = await JobRepository(session).cancel_job(job_id=job_id)
    except InvalidJobTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.refresh(job)
    response = JobOut.model_validate(job)
    await session.commit()
    return response


async def _count_jobs(session: AsyncSession, *criteria) -> int:
    statement = select(func.count()).select_from(WorkflowJob)
    for criterion in criteria:
        statement = statement.where(criterion)
    return int(await session.scalar(statement) or 0)
