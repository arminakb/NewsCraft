from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from newscraft.api.deps import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
