from newscraft.domain.enums import ArticleStatus
from newscraft.repositories.article_repository import ArticleRepository
from newscraft.repositories.approved_article_repository import ApprovedArticleRepository


class ArticleService:
    def __init__(self, db, article_repo=None, approved_repo=None):
        self.db = db
        self.article_repo = article_repo or ArticleRepository(db)
        self.approved_repo = approved_repo or ApprovedArticleRepository(db)

    def list(self, **filters):
        return self.article_repo.list(**filters)

    def get(self, article_id: int):
        return self.article_repo.get(article_id)

    def set_status(self, article_id: int, status: str):
        if status not in set(ArticleStatus):
            raise ValueError(f"invalid article status: {status}")
        return self.article_repo.update_status(article_id, status)

    def approve(self, article_id: int, notes=None):
        article = self.set_status(article_id, ArticleStatus.APPROVED)
        if not article:
            return None
        return self.approved_repo.create_from_article(article, notes=notes)

    def reject(self, article_id: int):
        return self.set_status(article_id, ArticleStatus.REJECTED)

    def reset(self, article_id: int):
        return self.set_status(article_id, ArticleStatus.NEW)
