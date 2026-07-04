from fastapi import APIRouter

from newscraft.services.diagnostics_service import DiagnosticsService

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.post("/sources")
def source_diagnostics():
    return DiagnosticsService().source_diagnostics()
