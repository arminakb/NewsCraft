from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from newscraft.api.deps import get_db
from newscraft.services.diagnostics_service import DiagnosticsService

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.post("/sources")
def source_diagnostics(db: Session = Depends(get_db)):
    return DiagnosticsService(db).source_diagnostics()
