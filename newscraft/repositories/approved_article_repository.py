from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newscraft.db.models import ApprovedArticle


class ApprovedArticleRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_from_article(self, article, notes=None):
        existing = self.db.scalar(select(ApprovedArticle).where(ApprovedArticle.url == article.url))
        if existing:
            return existing
        approved = ApprovedArticle(
            article_id=article.id,
            source=article.source,
            source_type=article.source_type,
            connector=article.connector,
            source_group=article.source_group,
            title=article.title,
            url=article.url,
            published_at=article.published_at,
            summary=article.summary,
            category=article.category,
            score=article.score,
            notes=notes,
            article_metadata=article.article_metadata or {},
        )
        self.db.add(approved)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return self.db.scalar(select(ApprovedArticle).where(ApprovedArticle.url == article.url))
        self.db.refresh(approved)
        return approved

    def list(self, limit=100, category=None, source_type=None):
        stmt = select(ApprovedArticle)
        if category:
            stmt = stmt.where(ApprovedArticle.category == category)
        if source_type:
            stmt = stmt.where(ApprovedArticle.source_type == source_type)
        return list(self.db.scalars(stmt.order_by(ApprovedArticle.approved_at.desc()).limit(limit)))
