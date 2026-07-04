from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from newscraft.api.deps import get_db
from newscraft.domain.schemas import ArticleRead
from newscraft.services.article_service import ArticleService

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=list[ArticleRead])
def list_articles(
    db: Session = Depends(get_db),
    source_type: str | None = None,
    connector: str | None = None,
    category: str | None = None,
    status: str | None = None,
    language: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: str = "latest",
):
    return ArticleService(db).list(
        source_type=source_type,
        connector=connector,
        category=category,
        status=status,
        language=language,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit,
        offset=offset,
        sort=sort,
    )


@router.get("/{article_id}", response_model=ArticleRead)
def get_article(article_id: int, db: Session = Depends(get_db)):
    article = ArticleService(db).get(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="article not found")
    return article
