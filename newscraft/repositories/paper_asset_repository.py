from sqlalchemy import select
from sqlalchemy.orm import Session

from newscraft.db.models import PaperAsset


class PaperAssetRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_for_article(self, article_id: int):
        return self.db.scalar(select(PaperAsset).where(PaperAsset.article_id == article_id))

    def upsert(self, data: dict):
        asset = self.get_for_article(data.get("article_id"))
        if not asset:
            asset = PaperAsset(article_id=data.get("article_id"))
            self.db.add(asset)
        for key in ("pdf_path", "text_path", "notebooklm_brief_path", "instagram_brief_path", "podcast_brief_path"):
            setattr(asset, key, data.get(key))
        asset.asset_metadata = data.get("metadata") or {}
        self.db.commit()
        self.db.refresh(asset)
        return asset
