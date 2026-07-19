from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.jobs.credential_capabilities import CapabilityStatusService

SessionDependency = Depends(get_session)


def get_capability_status_service(
    session: AsyncSession = SessionDependency,
) -> CapabilityStatusService:
    return CapabilityStatusService(session)


CapabilityStatusDependency = Annotated[
    CapabilityStatusService,
    Depends(get_capability_status_service),
]


__all__ = ["CapabilityStatusDependency", "get_capability_status_service"]
