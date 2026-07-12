from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.jobs.models import WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus
from app.main import app


async def test_retry_response_materializes_server_updated_fields(db_session: AsyncSession):
    job = await _seed_job(db_session, status=JobStatus.FAILED)

    response = await _post_with_session(f"/jobs/{job.id}/retry", db_session)

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["updated_at"]


async def test_cancel_response_materializes_server_updated_fields(db_session: AsyncSession):
    job = await _seed_job(db_session, status=JobStatus.QUEUED)

    response = await _post_with_session(f"/jobs/{job.id}/cancel", db_session)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["updated_at"]


async def _seed_job(session: AsyncSession, *, status: JobStatus) -> WorkflowJob:
    result = await JobRepository(session).enqueue_job(
        job_type="ingest.collect",
        payload={},
        idempotency_key=f"api-transition-{status.value}",
        origin=JobOrigin.MANUAL,
    )
    job = result.job
    job.status = status
    if status == JobStatus.FAILED:
        job.error_class = JobErrorClass.PERMANENT
        job.error_code = "test_failure"
        job.error_message = "test failure"
        job.finished_at = datetime.now(UTC)
    job_id = job.id
    await session.commit()
    stored = await session.get(WorkflowJob, job_id)
    assert stored is not None
    return stored


async def _post_with_session(path: str, session: AsyncSession):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(path)
    finally:
        app.dependency_overrides.clear()
