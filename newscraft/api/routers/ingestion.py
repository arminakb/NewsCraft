from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from newscraft.api.deps import get_db
from newscraft.domain.schemas import IngestionRunCreate, IngestionRunRead
from newscraft.services.ingestion_service import IngestionService

router = APIRouter(prefix="/ingestion/runs", tags=["ingestion"])


@router.post("", response_model=IngestionRunRead)
def start_ingestion(payload: IngestionRunCreate, db: Session = Depends(get_db)):
    return IngestionService(db).run(selected_sources=payload.selected_sources)


@router.get("", response_model=list[IngestionRunRead])
def list_runs(db: Session = Depends(get_db), limit: int = 50):
    return IngestionService(db).list_runs(limit=limit)


@router.get("/{run_id}", response_model=IngestionRunRead)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = IngestionService(db).get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="ingestion run not found")
    return run
