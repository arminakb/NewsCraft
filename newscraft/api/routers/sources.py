from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from newscraft.api.deps import get_db
from newscraft.domain.schemas import SourceCreate, SourceRead, SourceUpdate
from newscraft.services.diagnostics_service import DiagnosticsService
from newscraft.services.source_service import SourceService

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceRead])
def list_sources(db: Session = Depends(get_db)):
    return SourceService(db).list()


@router.post("", response_model=SourceRead)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    return SourceService(db).create(payload.model_dump())


@router.patch("/{source_id}", response_model=SourceRead)
def update_source(source_id: int, payload: SourceUpdate, db: Session = Depends(get_db)):
    source = SourceService(db).update(source_id, payload.model_dump(exclude_unset=True))
    if not source:
        raise HTTPException(status_code=404, detail="source not found")
    return source


@router.get("/health")
def source_health(db: Session = Depends(get_db)):
    return SourceService(db).health()


@router.post("/diagnostics")
def source_diagnostics(db: Session = Depends(get_db)):
    return DiagnosticsService(db).source_diagnostics()
