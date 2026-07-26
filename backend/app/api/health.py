from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.operations.health import ReadinessService, ReadinessSnapshot

router = APIRouter(tags=["health"])
SessionDependency = Depends(get_session)


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
