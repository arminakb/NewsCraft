from fastapi import HTTPException

from newscraft.repositories.article_repository import ArticleRepository
from newscraft.repositories.paper_asset_repository import PaperAssetRepository


class AssetService:
    def __init__(self, db, article_repo=None, asset_repo=None):
        self.article_repo = article_repo or ArticleRepository(db)
        self.asset_repo = asset_repo or PaperAssetRepository(db)

    def get_assets(self, article_id: int):
        return self.asset_repo.get_for_article(article_id)

    def prepare_arxiv_assets(self, article_id: int):
        article = self.article_repo.get(article_id)
        if not article:
            raise HTTPException(status_code=404, detail="article not found")
        if article.source_type != "arxiv":
            raise HTTPException(status_code=400, detail="article is not an arXiv item")
        # ponytail: record that asset prep was requested; full PDF extraction stays in legacy UI for now.
        return self.asset_repo.upsert({"article_id": article.id, "metadata": {"source_url": article.url, "status": "requested"}})
