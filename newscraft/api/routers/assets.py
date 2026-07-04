from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from newscraft.api.deps import get_db
from newscraft.domain.schemas import PaperAssetRead
from newscraft.services.asset_service import AssetService

router = APIRouter(prefix="/articles/{article_id}/assets", tags=["assets"])


@router.post("/arxiv", response_model=PaperAssetRead)
def prepare_arxiv_assets(article_id: int, db: Session = Depends(get_db)):
    return AssetService(db).prepare_arxiv_assets(article_id)


@router.get("", response_model=PaperAssetRead | None)
def get_assets(article_id: int, db: Session = Depends(get_db)):
    asset = AssetService(db).get_assets(article_id)
    if not asset:
        raise HTTPException(status_code=404, detail="assets not found")
    return asset
