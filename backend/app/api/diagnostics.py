from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DiagnosticsOut
from app.db.session import get_session
from app.diagnostics.service import DiagnosticsService

router = APIRouter()
SessionDependency = Depends(get_session)


@router.get("/diagnostics", response_model=DiagnosticsOut)
async def diagnostics(session: AsyncSession = SessionDependency):
    return await DiagnosticsService(session).check()
