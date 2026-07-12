from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import IngestRunRequest, IngestRunSummaryOut
from app.db.models import IngestRun
from app.db.session import get_session
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin

router = APIRouter()
SessionDependency = Depends(get_session)


@router.get("/ingest/runs", response_model=list[IngestRunSummaryOut])
async def list_ingest_runs(
    limit: int = Query(100, ge=1, le=250),
    session: AsyncSession = SessionDependency,
):
    rows = await session.scalars(
        select(IngestRun).order_by(IngestRun.started_at.desc()).limit(limit)
    )
    return list(rows)


@router.post("/ingest/run", response_model=JobAcceptedOut, status_code=202)
async def run_ingest(request: IngestRunRequest, session: AsyncSession = SessionDependency):
    result = await JobRepository(session).enqueue_job(
        job_type="ingest.collect",
        payload={"platforms": request.platforms, "source_ids": request.source_ids},
        idempotency_key=f"manual:ingest:{request.request_id}",
        origin=JobOrigin.MANUAL,
        pause_sensitive=False,
    )
    await session.commit()
    return JobAcceptedOut(
        job_id=result.job.id,
        status=result.job.status,
        deduplicated=not result.created,
    )
