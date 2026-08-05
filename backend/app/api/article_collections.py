from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.collection_events import enqueue_collection_article_added
from app.db.models import ArticleCollection, ArticleCollectionItem, ContentItem
from app.db.session import get_session

router = APIRouter(prefix="/article-collections", tags=["article-collections"])
SessionDependency = Depends(get_session)


def normalize_collection_name(value: str) -> tuple[str, str]:
    name = value.strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("collection name must contain between 1 and 60 characters")
    return name, name.casefold()


class ArticleCollectionNameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name, _ = normalize_collection_name(value)
        return name


class ArticleCollectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    article_count: int
    created_at: datetime
    updated_at: datetime


def _collection_out(row: Mapping[Any, Any]) -> ArticleCollectionOut:
    return ArticleCollectionOut(
        id=row["id"],
        name=row["name"],
        article_count=row["article_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _collection_projection():
    return (
        select(
            ArticleCollection.id,
            ArticleCollection.name,
            ArticleCollection.created_at,
            ArticleCollection.updated_at,
            func.count(ArticleCollectionItem.content_item_id).label("article_count"),
        )
        .outerjoin(
            ArticleCollectionItem,
            ArticleCollectionItem.collection_id == ArticleCollection.id,
        )
        .group_by(ArticleCollection.id)
    )


async def _get_collection(session: AsyncSession, collection_id: UUID) -> ArticleCollection:
    collection = await session.get(ArticleCollection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="article collection not found")
    return collection


async def _require_content_item(session: AsyncSession, content_item_id: UUID) -> None:
    if await session.get(ContentItem, content_item_id) is None:
        raise HTTPException(status_code=404, detail="article not found")


async def _require_unique_name(
    session: AsyncSession,
    normalized_name: str,
    *,
    excluding_id: UUID | None = None,
) -> None:
    statement = select(ArticleCollection.id).where(ArticleCollection.normalized_name == normalized_name)
    if excluding_id is not None:
        statement = statement.where(ArticleCollection.id != excluding_id)
    if await session.scalar(statement) is not None:
        raise HTTPException(status_code=409, detail="article collection name already exists")


async def _collection_with_count(
    session: AsyncSession,
    collection_id: UUID,
) -> ArticleCollectionOut:
    row = (
        (await session.execute(_collection_projection().where(ArticleCollection.id == collection_id))).mappings().one()
    )
    return _collection_out(row)


@router.get("", response_model=list[ArticleCollectionOut])
async def list_article_collections(
    session: AsyncSession = SessionDependency,
) -> list[ArticleCollectionOut]:
    rows = (
        (
            await session.execute(
                _collection_projection().order_by(
                    ArticleCollection.normalized_name,
                    ArticleCollection.id,
                )
            )
        )
        .mappings()
        .all()
    )
    return [_collection_out(row) for row in rows]


@router.post("", response_model=ArticleCollectionOut, status_code=status.HTTP_201_CREATED)
async def create_article_collection(
    body: ArticleCollectionNameIn,
    session: AsyncSession = SessionDependency,
) -> ArticleCollectionOut:
    name, normalized_name = normalize_collection_name(body.name)
    await _require_unique_name(session, normalized_name)
    collection = ArticleCollection(name=name, normalized_name=normalized_name)
    try:
        async with session.begin_nested():
            session.add(collection)
            await session.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="article collection name already exists") from None
    await session.commit()
    return await _collection_with_count(session, collection.id)


@router.patch("/{collection_id}", response_model=ArticleCollectionOut)
async def rename_article_collection(
    collection_id: UUID,
    body: ArticleCollectionNameIn,
    session: AsyncSession = SessionDependency,
) -> ArticleCollectionOut:
    collection = await _get_collection(session, collection_id)
    name, normalized_name = normalize_collection_name(body.name)
    await _require_unique_name(session, normalized_name, excluding_id=collection.id)
    collection.name = name
    collection.normalized_name = normalized_name
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="article collection name already exists") from None
    await session.commit()
    return await _collection_with_count(session, collection.id)


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article_collection(
    collection_id: UUID,
    session: AsyncSession = SessionDependency,
) -> Response:
    collection = await _get_collection(session, collection_id)
    await session.delete(collection)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{collection_id}/articles/{content_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def save_article_to_collection(
    collection_id: UUID,
    content_item_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
) -> Response:
    await _get_collection(session, collection_id)
    await _require_content_item(session, content_item_id)
    saved_at = (
        await session.execute(
            insert(ArticleCollectionItem)
            .values(collection_id=collection_id, content_item_id=content_item_id)
            .on_conflict_do_nothing(index_elements=["collection_id", "content_item_id"])
            .returning(ArticleCollectionItem.saved_at)
        )
    ).scalar_one_or_none()
    if saved_at is not None:
        principal = getattr(request.state, "security_principal", None)
        actor_id = (
            f"{principal.principal_type}:{principal.principal_id}"
            if principal is not None
            else "operator"
        )
        await enqueue_collection_article_added(
            session,
            article_id=content_item_id,
            collection_id=collection_id,
            added_at=saved_at,
            actor_id=actor_id,
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{collection_id}/articles/{content_item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_article_from_collection(
    collection_id: UUID,
    content_item_id: UUID,
    session: AsyncSession = SessionDependency,
) -> Response:
    await _get_collection(session, collection_id)
    await _require_content_item(session, content_item_id)
    await session.execute(
        delete(ArticleCollectionItem).where(
            ArticleCollectionItem.collection_id == collection_id,
            ArticleCollectionItem.content_item_id == content_item_id,
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
