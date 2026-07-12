from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin
from app.stories.schemas import ManualIntakeRequest

router = APIRouter()
SessionDependency = Depends(get_session)


@router.post("/stories/manual", response_model=JobAcceptedOut, status_code=202)
async def create_manual_intake(
    payload: ManualIntakeRequest,
    session: AsyncSession = SessionDependency,
) -> JobAcceptedOut:
    job_payload = payload.model_dump(mode="json")
    payload_hash = hashlib.sha256(
        json.dumps(job_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    result = await JobRepository(session).enqueue_job(
        job_type="manual_intake",
        payload=job_payload,
        idempotency_key=f"manual_intake:{payload_hash}",
        origin=JobOrigin.MANUAL,
    )
    await session.commit()
    return JobAcceptedOut(
        job_id=result.job.id,
        status=result.job.status,
        deduplicated=not result.created,
    )
