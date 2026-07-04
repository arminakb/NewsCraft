from datetime import date, datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from newscraft.db.models import Article


class ArticleRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, data: dict):
        values = self._values(data)
        existing = self._find_existing(values)
        if existing:
            return existing
        article = Article(**values)
        self.db.add(article)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return self._find_existing(values)
        self.db.refresh(article)
        return article

    def get(self, article_id: int):
        return self.db.get(Article, article_id)

    def list(
        self,
        source_type=None,
        connector=None,
        category=None,
        status=None,
        language=None,
        date_from: date | datetime | None = None,
        date_to: date | datetime | None = None,
        search=None,
        limit=100,
        offset=0,
        sort="latest",
    ):
        stmt = select(Article)
        if source_type:
            stmt = stmt.where(Article.source_type == source_type)
        if connector:
            stmt = stmt.where(Article.connector == connector)
        if category:
            stmt = stmt.where(Article.category == category)
        if status:
            stmt = stmt.where(Article.status == status)
        if language:
            stmt = stmt.where(Article.language == language)
        if date_from:
            stmt = stmt.where(Article.published_at >= date_from)
        if date_to:
            stmt = stmt.where(Article.published_at <= date_to)
        if search:
            term = f"%{search}%"
            stmt = stmt.where(or_(Article.title.ilike(term), Article.summary.ilike(term)))
        order = Article.score.desc() if sort == "score" else Article.published_at.desc().nullslast()
        return list(self.db.scalars(stmt.order_by(order, Article.created_at.desc()).limit(limit).offset(offset)))

    def update_status(self, article_id: int, status: str):
        article = self.get(article_id)
        if not article:
            return None
        article.status = status
        self.db.commit()
        self.db.refresh(article)
        return article

    def _find_existing(self, values):
        if values.get("url"):
            row = self.db.scalar(select(Article).where(Article.url == values["url"]))
            if row:
                return row
        if values.get("external_id"):
            return self.db.scalar(
                select(Article).where(Article.source == values["source"], Article.external_id == values["external_id"])
            )
        return None

    def _values(self, data):
        metadata = data.get("metadata") or data.get("metrics") or {}
        return {
            "title": data.get("title") or "",
            "url": data.get("url"),
            "external_id": data.get("external_id"),
            "source": data.get("source") or "Unknown",
            "source_type": data.get("source_type"),
            "connector": data.get("connector") or data.get("source_type"),
            "source_group": data.get("source_group"),
            "author": data.get("author"),
            "summary": data.get("summary") or data.get("description"),
            "content": data.get("content") or data.get("text"),
            "published_at": self._datetime(data.get("published_at")),
            "collected_at": self._datetime(data.get("collected_at")),
            "category": data.get("category"),
            "score": data.get("score") or 0,
            "status": data.get("status") or "new",
            "language": data.get("language"),
            "article_metadata": metadata,
            "raw_data": data.get("raw_data") or data,
        }

    def _datetime(self, value):
        if not value or isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        text = str(value).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
