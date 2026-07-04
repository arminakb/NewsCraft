from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from newscraft.api.deps import get_db
from newscraft.domain.schemas import ArticleRead, ArticleStatusUpdate, ApprovedArticleRead
from newscraft.services.article_service import ArticleService

router = APIRouter(prefix="/articles", tags=["review"])


@router.post("/{article_id}/approve", response_model=ApprovedArticleRead)
def approve_article(article_id: int, db: Session = Depends(get_db)):
    approved = ArticleService(db).approve(article_id)
    if not approved:
        raise HTTPException(status_code=404, detail="article not found")
    return approved


@router.post("/{article_id}/reject", response_model=ArticleRead)
def reject_article(article_id: int, db: Session = Depends(get_db)):
    article = ArticleService(db).reject(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="article not found")
    return article


@router.post("/{article_id}/reset", response_model=ArticleRead)
def reset_article(article_id: int, db: Session = Depends(get_db)):
    article = ArticleService(db).reset(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="article not found")
    return article


@router.patch("/{article_id}/status", response_model=ArticleRead)
def update_article_status(article_id: int, payload: ArticleStatusUpdate, db: Session = Depends(get_db)):
    article = ArticleService(db).set_status(article_id, payload.status)
    if not article:
        raise HTTPException(status_code=404, detail="article not found")
    return article
