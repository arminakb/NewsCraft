from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import nh3
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, exists, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select

from app.api.stories import _story_summaries
from app.content.article_metadata import (
    canonical_article_expressions,
    canonical_content_type,
    canonical_language,
    canonical_topic,
    canonicalize_article_classification,
)
from app.db.models import ArticleCollection, ArticleCollectionItem, ContentItem, ItemMedia, MediaAsset, Source
from app.db.session import get_session
from app.stories.models import Story, StoryEvidenceSnapshot

router = APIRouter(tags=["articles"])
SessionDependency = Depends(get_session)

_EXCERPT_LIMIT = 500
_EXCERPT_SCAN_LIMIT = 2_000
ArticleSort = Literal["newest", "score"]
CoverageState = Literal["ungrouped", "incomplete", "complete"]


class ArticleSourceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID | None
    name: str | None
    platform: str | None
    homepage_url: str | None


class ArticleImageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    url: str
    kind: str
    width: int | None
    height: int | None
    alt_text: str | None
    fetch_status: str


class ArticleStorySummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    editorial_state: str
    complete: bool
    score: int = Field(ge=0, le=100)


class ArticleCoverageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: CoverageState
    stories: list[ArticleStorySummaryOut]


class ArticleReadinessSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool


class ArticleReadinessDetailOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    reason: str | None
    blockers: list[str]


class ArticleCoreOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str | None
    summary: str | None
    excerpt: str | None
    source: ArticleSourceOut
    canonical_url: str | None
    published_at: datetime | None
    sort_at: datetime
    display_at: datetime
    date_basis: Literal["published", "collected"]
    score: int
    content_type: str
    topic: str | None
    domain: str | None
    language: str | None
    direction: Literal["ltr", "rtl"] | None
    coverage: ArticleCoverageOut
    image: ArticleImageOut | None
    has_image: bool
    marked: Literal[False] = False
    marked_at: None = None
    saved: bool
    saved_collection_ids: list[UUID]


class ArticleSummaryOut(ArticleCoreOut):
    article_readiness: ArticleReadinessSummaryOut


class ArticleListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ArticleSummaryOut]
    next_cursor: str | None
    result_count: int = Field(ge=0)


class ArticleFacetValueOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    count: int = Field(ge=1)


class ArticleCoverageFacetOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: CoverageState
    count: int = Field(ge=1)


class ArticleSourceFacetOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    platform: str
    count: int = Field(ge=1)


class ArticleFacetsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    languages: list[ArticleFacetValueOut]
    topics: list[ArticleFacetValueOut]
    content_types: list[ArticleFacetValueOut]
    sources: list[ArticleSourceFacetOut]
    coverage: list[ArticleCoverageFacetOut]


class ArticleStoryLinkOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    editorial_state: str
    primary_language: str
    active: bool
    superseded_by_id: UUID | None
    evidence_count: int = Field(ge=0)
    complete: bool
    completeness_score: int = Field(ge=0, le=100)
    story_url: str
    evidence_url: str
    research_runs_url: str
    content_packs_url: str


class ArticleEvidenceReferenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    story_id: UUID
    evidence_key: str
    title: str | None
    source_url: str | None
    published_at: datetime | None
    captured_at: datetime
    content_sha256: str
    story_url: str
    evidence_url: str


class ArticleMediaOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    url: str
    kind: str
    mime_type: str | None
    width: int | None
    height: int | None
    alt_text: str | None
    title: str | None
    fetch_status: str
    role: str
    sort_order: int
    primary: bool


class ArticleRawClassificationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: str | None
    topic: str | None
    language: str | None


class ArticleAdvancedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: str
    status: str
    rewrite_bucket: str | None
    classification_reasons: list[str]
    source_tier: str
    freshness_bucket: str
    quality_status: str
    title_quality: str
    title_was_generated: bool
    content_intent: str | None
    duplicate_of_id: UUID | None
    date_source: str | None
    date_parse_status: str
    created_at: datetime
    updated_at: datetime
    raw_classification: ArticleRawClassificationOut


class ArticleDetailOut(ArticleCoreOut):
    article_readiness: ArticleReadinessDetailOut
    content_text: str | None
    sanitized_html: str | None
    authors: list[str]
    tags: list[str]
    media: list[ArticleMediaOut]
    story_links: list[ArticleStoryLinkOut]
    evidence_references: list[ArticleEvidenceReferenceOut]
    advanced: ArticleAdvancedOut


@dataclass(frozen=True, slots=True)
class ArticleFilters:
    search_query: str | None = None
    languages: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    content_types: tuple[str, ...] = ()
    source_ids: tuple[UUID, ...] = ()
    coverage: tuple[CoverageState, ...] = ()
    has_image: bool | None = None
    score_min: int | None = None
    score_max: int | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    collection_id: UUID | None = None

    def fingerprint(self) -> str:
        payload = {
            "q": self.search_query,
            "language": self.languages,
            "topic": self.topics,
            "content_type": self.content_types,
            "source_id": tuple(str(value) for value in self.source_ids),
            "coverage": self.coverage,
            "has_image": self.has_image,
            "score_min": self.score_min,
            "score_max": self.score_max,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "collection_id": str(self.collection_id) if self.collection_id else None,
        }
        raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


_EMPTY_FILTER_KEY = ArticleFilters().fingerprint()


def _display_at_expression():
    return func.coalesce(ContentItem.published_at, ContentItem.sort_at)


def _topic_expression():
    return ContentItem.metrics["classification"]["category"].astext


def _article_classification_expressions():
    return canonical_article_expressions(
        ContentItem.content_type,
        _topic_expression(),
        ContentItem.language_code,
    )


def _usable_image_expression():
    return exists(
        select(1)
        .select_from(MediaAsset)
        .where(
            MediaAsset.id == ContentItem.primary_image_id,
            MediaAsset.kind == "image",
            MediaAsset.fetch_status != "expired",
            MediaAsset.normalized_url != "",
        )
        .correlate(ContentItem)
    )


def _search_vector_expression():
    document = (
        func.coalesce(ContentItem.title, literal_column("''"))
        + literal_column("' '")
        + func.coalesce(ContentItem.content_text, literal_column("''"))
    )
    return func.to_tsvector(literal_column("'simple'::regconfig"), document)


def _story_completeness_subquery():
    source_host = func.lower(
        func.regexp_replace(
            func.split_part(
                func.split_part(func.coalesce(StoryEvidenceSnapshot.source_url, ""), "://", 2),
                "/",
                1,
            ),
            r":\d+$",
            "",
        )
    )
    source_label = func.lower(func.trim(StoryEvidenceSnapshot.snapshot_metadata["source_label"].astext))
    source_identity = case(
        (source_host != "", "host:" + source_host),
        (source_label != "", "source:" + source_label),
        else_=None,
    )
    body_characters = func.sum(
        func.char_length(
            func.regexp_replace(
                func.coalesce(StoryEvidenceSnapshot.content_text, ""),
                r"\s+",
                "",
                "g",
            )
        )
    )
    has_primary = func.bool_or(
        func.coalesce(StoryEvidenceSnapshot.snapshot_metadata["is_primary"].astext == "true", False)
    )
    return (
        select(
            StoryEvidenceSnapshot.story_id.label("story_id"),
            func.count(func.distinct(source_identity)).label("source_count"),
            body_characters.label("body_character_count"),
            has_primary.label("has_primary"),
        )
        .group_by(StoryEvidenceSnapshot.story_id)
        .subquery("story_completeness")
    )


def _active_story_exists():
    link = aliased(StoryEvidenceSnapshot)
    story = aliased(Story)
    return exists(
        select(1)
        .select_from(link)
        .join(story, story.id == link.story_id)
        .where(
            link.content_item_id == ContentItem.id,
            story.superseded_by_id.is_(None),
        )
    ).correlate(ContentItem)


def _complete_story_exists():
    link = aliased(StoryEvidenceSnapshot)
    story = aliased(Story)
    completeness = _story_completeness_subquery()
    return exists(
        select(1)
        .select_from(link)
        .join(story, story.id == link.story_id)
        .join(completeness, completeness.c.story_id == story.id)
        .where(
            link.content_item_id == ContentItem.id,
            story.superseded_by_id.is_(None),
            completeness.c.source_count >= 2,
            completeness.c.body_character_count >= 800,
            completeness.c.has_primary.is_(True),
        )
    ).correlate(ContentItem)


def _coverage_state_expression():
    return case(
        (_complete_story_exists(), "complete"),
        (_active_story_exists(), "incomplete"),
        else_="ungrouped",
    )


def _base_article_columns() -> tuple:
    return (
        ContentItem.id,
        ContentItem.title,
        ContentItem.summary,
        func.substr(ContentItem.content_text, 1, _EXCERPT_SCAN_LIMIT).label("excerpt_source"),
        ContentItem.canonical_url,
        ContentItem.published_at,
        ContentItem.sort_at,
        _display_at_expression().label("display_at"),
        ContentItem.score,
        ContentItem.content_type.label("raw_content_type"),
        _topic_expression().label("raw_topic"),
        ContentItem.classification_metadata["source_domain"].astext.label("domain"),
        ContentItem.language_code.label("raw_language_code"),
        ContentItem.direction,
        ContentItem.is_rewrite_ready,
        Source.id.label("source_id"),
        Source.name.label("source_name"),
        Source.platform.label("source_platform"),
        Source.homepage_url.label("source_homepage_url"),
        ContentItem.classification_metadata["source_name"].astext.label("legacy_source_name"),
        ContentItem.classification_metadata["source_platform"].astext.label("legacy_source_platform"),
        MediaAsset.id.label("image_id"),
        MediaAsset.normalized_url.label("image_url"),
        MediaAsset.kind.label("image_kind"),
        MediaAsset.width.label("image_width"),
        MediaAsset.height.label("image_height"),
        MediaAsset.alt_text.label("image_alt_text"),
        MediaAsset.fetch_status.label("image_fetch_status"),
    )


def _join_article_projection(statement: Select) -> Select:
    return statement.outerjoin(Source, Source.id == ContentItem.primary_source_id).outerjoin(
        MediaAsset,
        MediaAsset.id == ContentItem.primary_image_id,
    )


@dataclass(frozen=True, slots=True)
class ArticleQuery:
    filters: ArticleFilters
    sort: ArticleSort
    cursor: tuple[datetime, UUID] | tuple[int, datetime, UUID] | None

    def filtered(self, statement: Select) -> Select:
        display_at = _display_at_expression()
        content_type, topic, language = _article_classification_expressions()
        filters = self.filters
        if filters.search_query is not None:
            if any(character.isalnum() for character in filters.search_query):
                statement = statement.where(
                    _search_vector_expression().op("@@")(
                        func.websearch_to_tsquery(
                            literal_column("'simple'::regconfig"),
                            filters.search_query,
                        )
                    )
                )
            else:
                escaped_query = filters.search_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                pattern = f"%{escaped_query}%"
                statement = statement.where(
                    or_(
                        ContentItem.title.ilike(pattern, escape="\\"),
                        ContentItem.content_text.ilike(pattern, escape="\\"),
                    )
                )
        if filters.languages:
            statement = statement.where(language.in_(filters.languages))
        if filters.topics:
            statement = statement.where(topic.in_(filters.topics))
        if filters.content_types:
            statement = statement.where(content_type.in_(filters.content_types))
        if filters.source_ids:
            statement = statement.where(ContentItem.primary_source_id.in_(filters.source_ids))
        if filters.coverage:
            statement = statement.where(_coverage_state_expression().in_(filters.coverage))
        if filters.has_image is not None:
            usable_image = _usable_image_expression()
            statement = statement.where(usable_image if filters.has_image else ~usable_image)
        if filters.score_min is not None:
            statement = statement.where(ContentItem.score >= filters.score_min)
        if filters.score_max is not None:
            statement = statement.where(ContentItem.score <= filters.score_max)
        if filters.date_from is not None:
            statement = statement.where(display_at >= filters.date_from)
        if filters.date_to is not None:
            statement = statement.where(display_at < filters.date_to)
        if filters.collection_id is not None:
            statement = statement.where(
                exists(
                    select(1)
                    .select_from(ArticleCollectionItem)
                    .where(
                        ArticleCollectionItem.collection_id == filters.collection_id,
                        ArticleCollectionItem.content_item_id == ContentItem.id,
                    )
                    .correlate(ContentItem)
                )
            )
        return statement

    def count_statement(self) -> Select:
        return self.filtered(select(func.count()).select_from(ContentItem))

    def list_statement(self, limit: int) -> Select:
        display_at = _display_at_expression()
        statement = self.filtered(_join_article_projection(select(*_base_article_columns())))
        if self.cursor is not None:
            if self.sort == "newest":
                cursor_at, cursor_id = self.cursor
                statement = statement.where(
                    or_(
                        display_at < cursor_at,
                        (display_at == cursor_at) & (ContentItem.id < cursor_id),
                    )
                )
            else:
                cursor_score, cursor_at, cursor_id = self.cursor
                statement = statement.where(
                    or_(
                        ContentItem.score < cursor_score,
                        (ContentItem.score == cursor_score) & (display_at < cursor_at),
                        (ContentItem.score == cursor_score) & (display_at == cursor_at) & (ContentItem.id < cursor_id),
                    )
                )
        if self.sort == "score":
            statement = statement.order_by(
                ContentItem.score.desc(),
                display_at.desc(),
                ContentItem.id.desc(),
            )
        else:
            statement = statement.order_by(display_at.desc(), ContentItem.id.desc())
        return statement.limit(limit + 1)


def article_detail_statement(content_item_id: UUID) -> Select:
    return _join_article_projection(
        select(
            *_base_article_columns(),
            ContentItem.content_text,
            ContentItem.content_html_sanitized,
            ContentItem.authors,
            ContentItem.tags,
            ContentItem.rewrite_ready_reason,
            ContentItem.rewrite_blockers,
            ContentItem.item_type,
            ContentItem.status,
            ContentItem.rewrite_bucket,
            ContentItem.classification_reasons,
            ContentItem.source_tier,
            ContentItem.freshness_bucket,
            ContentItem.quality_status,
            ContentItem.title_quality,
            ContentItem.title_was_generated,
            ContentItem.content_intent,
            ContentItem.duplicate_of_id,
            ContentItem.date_source,
            ContentItem.date_parse_status,
            ContentItem.created_at,
            ContentItem.updated_at,
            MediaAsset.mime_type.label("image_mime_type"),
            MediaAsset.title.label("image_title"),
        )
    ).where(ContentItem.id == content_item_id)


def encode_article_cursor(sort: ArticleSort, row: Any, filters_key: str = _EMPTY_FILTER_KEY) -> str:
    payload: dict[str, object] = {
        "v": 2,
        "sort": sort,
        "filters": filters_key,
        "display_at": row.display_at.isoformat(),
        "id": str(row.id),
    }
    if sort == "score":
        payload["score"] = row.score
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_article_cursor(
    value: str,
    sort: ArticleSort,
    filters_key: str = _EMPTY_FILTER_KEY,
) -> tuple[datetime, UUID] | tuple[int, datetime, UUID]:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
        expected_keys = {"v", "sort", "filters", "display_at", "id"}
        if sort == "score":
            expected_keys.add("score")
        if not isinstance(payload, dict) or set(payload) != expected_keys:
            raise ValueError
        if payload["v"] != 2 or payload["sort"] != sort or payload["filters"] != filters_key:
            raise ValueError
        display_at = datetime.fromisoformat(payload["display_at"])
        if display_at.tzinfo is None or display_at.utcoffset() is None:
            raise ValueError
        content_item_id = UUID(payload["id"])
        if sort == "score":
            score = payload["score"]
            if isinstance(score, bool) or not isinstance(score, int):
                raise ValueError
            return score, display_at, content_item_id
        return display_at, content_item_id
    except binascii.Error, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError:
        raise ValueError("invalid article cursor") from None


def _route_cursor(value: str | None, sort: ArticleSort, filters_key: str):
    if value is None:
        return None
    try:
        return decode_article_cursor(value, sort, filters_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _filter_values(values: list[str] | None, normalizer) -> tuple[str, ...]:
    normalized = {normalizer(value) for value in values or []}
    if None in normalized:
        raw_values = {" ".join(value.split()).lower() for value in values or []}
        if "general" in raw_values:
            raise HTTPException(
                status_code=422,
                detail="General is not an operator-facing article topic",
            )
        raise HTTPException(status_code=422, detail="article filter values cannot be blank")
    return tuple(sorted(normalized))


def _article_filters(
    *,
    q: str | None,
    language: list[str] | None,
    topic: list[str] | None,
    content_type: list[str] | None,
    source_id: list[UUID] | None,
    coverage: list[CoverageState] | None,
    has_image: bool | None,
    score_min: int | None,
    score_max: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
    collection_id: UUID | None,
) -> ArticleFilters:
    if score_min is not None and score_max is not None and score_min > score_max:
        raise HTTPException(status_code=422, detail="score_min must be less than or equal to score_max")
    for value in (date_from, date_to):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise HTTPException(status_code=422, detail="article date filters require timezone offsets")
    if date_from is not None and date_to is not None and date_from >= date_to:
        raise HTTPException(status_code=422, detail="date_from must be earlier than date_to")
    return ArticleFilters(
        search_query=(q.strip().casefold() or None) if q is not None else None,
        languages=_filter_values(language, canonical_language),
        topics=_filter_values(topic, canonical_topic),
        content_types=_filter_values(content_type, canonical_content_type),
        source_ids=tuple(sorted(set(source_id or []), key=str)),
        coverage=tuple(sorted(set(coverage or []))),
        has_image=has_image,
        score_min=score_min,
        score_max=score_max,
        date_from=date_from,
        date_to=date_to,
        collection_id=collection_id,
    )


def _bounded_excerpt(summary: str | None, content: str | None) -> str | None:
    if summary is not None and summary.strip():
        return None
    normalized = " ".join((content or "").split())
    return normalized[:_EXCERPT_LIMIT].rstrip() or None


def _label(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized or None


def _domain(value: object | None) -> str | None:
    normalized = _label(value)
    if normalized is None:
        return None
    try:
        host = urlsplit(normalized if "://" in normalized else f"//{normalized}").hostname
    except ValueError:
        return None
    return host.rstrip(".").lower() if host else None


def _direction(value: object | None) -> Literal["ltr", "rtl"] | None:
    return value if value in {"ltr", "rtl"} else None


def _source(row: Any) -> ArticleSourceOut:
    return ArticleSourceOut(
        id=row.source_id,
        name=_label(row.source_name) or _label(row.legacy_source_name),
        platform=_label(row.source_platform) or _label(row.legacy_source_platform),
        homepage_url=row.source_homepage_url,
    )


def _primary_image(row: Any) -> ArticleImageOut | None:
    if row.image_id is None or row.image_kind != "image" or row.image_fetch_status == "expired" or not row.image_url:
        return None
    return ArticleImageOut(
        id=row.image_id,
        url=row.image_url,
        kind=row.image_kind,
        width=row.image_width,
        height=row.image_height,
        alt_text=row.image_alt_text,
        fetch_status=row.image_fetch_status,
    )


async def _story_associations(
    session: AsyncSession,
    content_item_ids: list[UUID],
    *,
    include_historical: bool,
) -> dict[UUID, list[tuple[Story, dict]]]:
    if not content_item_ids:
        return {}
    statement = (
        select(StoryEvidenceSnapshot.content_item_id, Story)
        .join(Story, Story.id == StoryEvidenceSnapshot.story_id)
        .where(StoryEvidenceSnapshot.content_item_id.in_(content_item_ids))
    )
    if not include_historical:
        statement = statement.where(Story.superseded_by_id.is_(None))
    rows = (await session.execute(statement.order_by(Story.updated_at.desc(), Story.id.desc()))).all()
    stories: dict[UUID, Story] = {}
    item_story_ids: dict[UUID, list[UUID]] = defaultdict(list)
    seen: set[tuple[UUID, UUID]] = set()
    for content_item_id, story in rows:
        identity = (content_item_id, story.id)
        if identity in seen:
            continue
        seen.add(identity)
        stories[story.id] = story
        item_story_ids[content_item_id].append(story.id)
    summaries = await _story_summaries(session, list(stories.values())) if stories else {}
    return {
        content_item_id: [(stories[story_id], summaries[story_id]) for story_id in story_ids]
        for content_item_id, story_ids in item_story_ids.items()
    }


def _coverage(associations: list[tuple[Story, dict]]) -> ArticleCoverageOut:
    active = [(story, summary) for story, summary in associations if story.superseded_by_id is None]
    stories = [
        ArticleStorySummaryOut(
            id=story.id,
            title=story.title,
            editorial_state=story.status,
            complete=summary["completeness"]["complete"],
            score=summary["completeness"]["score"],
        )
        for story, summary in active
    ]
    state: CoverageState
    if not stories:
        state = "ungrouped"
    elif any(story.complete for story in stories):
        state = "complete"
    else:
        state = "incomplete"
    return ArticleCoverageOut(state=state, stories=stories)


async def _text_facets(session: AsyncSession, expression) -> list[ArticleFacetValueOut]:
    value = expression.label("value")
    rows = (
        await session.execute(
            select(value, func.count(ContentItem.id).label("count"))
            .where(value.is_not(None))
            .group_by(value)
            .order_by(value)
        )
    ).all()
    return [ArticleFacetValueOut(value=row.value, count=row.count) for row in rows]


def _core_fields(
    row: Any,
    coverage: ArticleCoverageOut,
    saved_collection_ids: list[UUID],
) -> dict[str, Any]:
    image = _primary_image(row)
    classification = canonicalize_article_classification(
        content_type=row.raw_content_type,
        topic=row.raw_topic,
        language=row.raw_language_code,
    )
    return {
        "id": row.id,
        "title": row.title,
        "summary": row.summary,
        "excerpt": _bounded_excerpt(row.summary, row.excerpt_source),
        "source": _source(row),
        "canonical_url": row.canonical_url,
        "published_at": row.published_at,
        "sort_at": row.sort_at,
        "display_at": row.display_at,
        "date_basis": "published" if row.published_at is not None else "collected",
        "score": row.score,
        "content_type": classification.content_type,
        "topic": classification.topic,
        "domain": _domain(row.domain),
        "language": classification.language,
        "direction": _direction(row.direction),
        "coverage": coverage,
        "image": image,
        "has_image": image is not None,
        "marked": False,
        "marked_at": None,
        "saved": bool(saved_collection_ids),
        "saved_collection_ids": saved_collection_ids,
    }


def article_summary_out(
    row: Any,
    associations: list[tuple[Story, dict]],
    saved_collection_ids: list[UUID],
) -> ArticleSummaryOut:
    return ArticleSummaryOut(
        **_core_fields(row, _coverage(associations), saved_collection_ids),
        article_readiness=ArticleReadinessSummaryOut(ready=bool(row.is_rewrite_ready)),
    )


async def _saved_collections_for_items(
    session: AsyncSession,
    content_item_ids: list[UUID],
) -> dict[UUID, list[UUID]]:
    if not content_item_ids:
        return {}
    rows = (
        await session.execute(
            select(
                ArticleCollectionItem.content_item_id,
                ArticleCollectionItem.collection_id,
            )
            .where(ArticleCollectionItem.content_item_id.in_(content_item_ids))
            .order_by(
                ArticleCollectionItem.content_item_id,
                ArticleCollectionItem.collection_id,
            )
        )
    ).all()
    memberships: dict[UUID, list[UUID]] = defaultdict(list)
    for content_item_id, collection_id in rows:
        memberships[content_item_id].append(collection_id)
    return dict(memberships)


def _story_link(story: Story, summary: dict) -> ArticleStoryLinkOut:
    return ArticleStoryLinkOut(
        id=story.id,
        title=story.title,
        editorial_state=story.status,
        primary_language=story.primary_language,
        active=story.superseded_by_id is None,
        superseded_by_id=story.superseded_by_id,
        evidence_count=summary["evidence_count"],
        complete=summary["completeness"]["complete"],
        completeness_score=summary["completeness"]["score"],
        story_url=f"/stories/{story.id}",
        evidence_url=f"/stories/{story.id}/evidence",
        research_runs_url=f"/stories/{story.id}/research-runs",
        content_packs_url=f"/stories/{story.id}/content-packs",
    )


async def _evidence_references(
    session: AsyncSession,
    content_item_id: UUID,
) -> list[ArticleEvidenceReferenceOut]:
    rows = list(
        await session.scalars(
            select(StoryEvidenceSnapshot)
            .where(StoryEvidenceSnapshot.content_item_id == content_item_id)
            .order_by(StoryEvidenceSnapshot.captured_at.desc(), StoryEvidenceSnapshot.id.desc())
        )
    )
    return [
        ArticleEvidenceReferenceOut(
            id=row.id,
            story_id=row.story_id,
            evidence_key=row.evidence_key,
            title=row.title,
            source_url=row.source_url,
            published_at=row.published_at,
            captured_at=row.captured_at,
            content_sha256=row.content_sha256,
            story_url=f"/stories/{row.story_id}",
            evidence_url=f"/stories/{row.story_id}/evidence",
        )
        for row in rows
    ]


async def _article_media(
    session: AsyncSession,
    content_item_id: UUID,
    primary_image_id: UUID | None,
    detail_row: Any,
) -> list[ArticleMediaOut]:
    rows = (
        await session.execute(
            select(ItemMedia, MediaAsset)
            .join(MediaAsset, MediaAsset.id == ItemMedia.media_asset_id)
            .where(ItemMedia.content_item_id == content_item_id)
            .order_by(ItemMedia.sort_order, ItemMedia.role, MediaAsset.id)
        )
    ).all()
    output = [
        ArticleMediaOut(
            id=media.id,
            url=media.normalized_url,
            kind=media.kind,
            mime_type=media.mime_type,
            width=media.width,
            height=media.height,
            alt_text=media.alt_text,
            title=media.title,
            fetch_status=media.fetch_status,
            role=attachment.role,
            sort_order=attachment.sort_order,
            primary=media.id == primary_image_id,
        )
        for attachment, media in rows
    ]
    if primary_image_id is not None and all(item.id != primary_image_id for item in output) and detail_row.image_id:
        output.insert(
            0,
            ArticleMediaOut(
                id=detail_row.image_id,
                url=detail_row.image_url,
                kind=detail_row.image_kind,
                mime_type=detail_row.image_mime_type,
                width=detail_row.image_width,
                height=detail_row.image_height,
                alt_text=detail_row.image_alt_text,
                title=detail_row.image_title,
                fetch_status=detail_row.image_fetch_status,
                role="primary_image",
                sort_order=0,
                primary=True,
            ),
        )
    return output


def _safe_html(value: str | None) -> str | None:
    if value is None:
        return None
    sanitized = nh3.clean(value, url_schemes={"http", "https", "mailto"}).strip()
    return sanitized or None


@router.get("/articles", response_model=ArticleListOut)
async def list_articles(
    cursor: str | None = Query(default=None, min_length=1, max_length=2_000),
    limit: int = Query(default=50, ge=1, le=200),
    sort: ArticleSort = "newest",
    q: Annotated[str | None, Query(max_length=200)] = None,
    language: Annotated[list[str] | None, Query()] = None,
    topic: Annotated[list[str] | None, Query()] = None,
    content_type: Annotated[list[str] | None, Query()] = None,
    source_id: Annotated[list[UUID] | None, Query()] = None,
    coverage: Annotated[list[CoverageState] | None, Query()] = None,
    has_image: Annotated[bool | None, Query()] = None,
    score_min: Annotated[int | None, Query()] = None,
    score_max: Annotated[int | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    collection_id: Annotated[UUID | None, Query()] = None,
    session: AsyncSession = SessionDependency,
) -> ArticleListOut:
    if collection_id is not None and await session.get(ArticleCollection, collection_id) is None:
        raise HTTPException(status_code=404, detail="article collection not found")
    filters = _article_filters(
        q=q,
        language=language,
        topic=topic,
        content_type=content_type,
        source_id=source_id,
        coverage=coverage,
        has_image=has_image,
        score_min=score_min,
        score_max=score_max,
        date_from=date_from,
        date_to=date_to,
        collection_id=collection_id,
    )
    filters_key = filters.fingerprint()
    decoded_cursor = _route_cursor(cursor, sort, filters_key)
    query = ArticleQuery(
        filters=filters,
        sort=sort,
        cursor=decoded_cursor,
    )
    result_count = int(await session.scalar(query.count_statement()) or 0)
    rows = (await session.execute(query.list_statement(limit))).all()
    page = rows[:limit]
    associations = await _story_associations(
        session,
        [row.id for row in page],
        include_historical=False,
    )
    memberships = await _saved_collections_for_items(session, [row.id for row in page])
    return ArticleListOut(
        items=[
            article_summary_out(
                row,
                associations.get(row.id, []),
                memberships.get(row.id, []),
            )
            for row in page
        ],
        next_cursor=(encode_article_cursor(sort, page[-1], filters_key) if len(rows) > limit and page else None),
        result_count=result_count,
    )


@router.get("/articles/facets", response_model=ArticleFacetsOut)
async def get_article_facets(
    session: AsyncSession = SessionDependency,
) -> ArticleFacetsOut:
    source_rows = (
        await session.execute(
            select(
                Source.id,
                Source.name,
                Source.platform,
                func.count(ContentItem.id).label("count"),
            )
            .join(ContentItem, ContentItem.primary_source_id == Source.id)
            .group_by(Source.id, Source.name, Source.platform)
            .order_by(Source.name, Source.platform, Source.id)
        )
    ).all()
    coverage_state = _coverage_state_expression().label("coverage_state")
    coverage_rows = (
        await session.execute(
            select(coverage_state, func.count(ContentItem.id).label("count"))
            .select_from(ContentItem)
            .group_by(coverage_state)
            .order_by(coverage_state)
        )
    ).all()
    content_type, topic, language = _article_classification_expressions()
    return ArticleFacetsOut(
        languages=await _text_facets(session, language),
        topics=await _text_facets(session, topic),
        content_types=await _text_facets(session, content_type),
        sources=[
            ArticleSourceFacetOut(
                id=row.id,
                name=row.name,
                platform=row.platform,
                count=row.count,
            )
            for row in source_rows
        ],
        coverage=[ArticleCoverageFacetOut(value=row.coverage_state, count=row.count) for row in coverage_rows],
    )


@router.get("/articles/{content_item_id}", response_model=ArticleDetailOut)
async def get_article(
    content_item_id: UUID,
    session: AsyncSession = SessionDependency,
) -> ArticleDetailOut:
    row = (await session.execute(article_detail_statement(content_item_id))).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="article not found")
    associations = (await _story_associations(session, [content_item_id], include_historical=True)).get(
        content_item_id, []
    )
    memberships = await _saved_collections_for_items(session, [content_item_id])
    return ArticleDetailOut(
        **_core_fields(
            row,
            _coverage(associations),
            memberships.get(content_item_id, []),
        ),
        article_readiness=ArticleReadinessDetailOut(
            ready=bool(row.is_rewrite_ready),
            reason=row.rewrite_ready_reason,
            blockers=list(row.rewrite_blockers or []),
        ),
        content_text=row.content_text,
        sanitized_html=_safe_html(row.content_html_sanitized),
        authors=list(row.authors or []),
        tags=list(row.tags or []),
        media=await _article_media(session, content_item_id, row.image_id, row),
        story_links=[_story_link(story, summary) for story, summary in associations],
        evidence_references=await _evidence_references(session, content_item_id),
        advanced=ArticleAdvancedOut(
            item_type=row.item_type,
            status=row.status,
            rewrite_bucket=row.rewrite_bucket,
            classification_reasons=list(row.classification_reasons or []),
            source_tier=row.source_tier,
            freshness_bucket=row.freshness_bucket,
            quality_status=row.quality_status,
            title_quality=row.title_quality,
            title_was_generated=row.title_was_generated,
            content_intent=row.content_intent,
            duplicate_of_id=row.duplicate_of_id,
            date_source=row.date_source,
            date_parse_status=row.date_parse_status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            raw_classification=ArticleRawClassificationOut(
                content_type=row.raw_content_type,
                topic=row.raw_topic,
                language=row.raw_language_code,
            ),
        ),
    )
