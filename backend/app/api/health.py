from fastapi import APIRouter, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import SessionDependency
from app.operations.health import ReadinessService, ReadinessSnapshot, SecretReadinessService

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Process/event-loop liveness only; intentionally performs no dependency IO."""
    return {"status": "alive"}


@router.get("/health/ready", response_model=ReadinessSnapshot)
async def readiness(
    response: Response,
    session: AsyncSession = SessionDependency,
) -> ReadinessSnapshot:
    snapshot = await ReadinessService(session).snapshot()
    if not snapshot.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return snapshot


@router.get("/health/ready/secrets", response_model=ReadinessSnapshot)
async def secret_readiness(
    request: Request,
    response: Response,
    session: AsyncSession = SessionDependency,
) -> ReadinessSnapshot:
    runtime = getattr(request.app.state, "secret_store_runtime", None)
    snapshot = await SecretReadinessService(session, runtime=runtime).snapshot()
    if not snapshot.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return snapshot
