from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CoverageState = Literal["ungrouped", "incomplete", "complete"]
ContentOrigin = Literal[
    "source_provided",
    "extracted",
    "source_excerpt",
    "generated_summary",
    "unavailable",
    "unknown",
]


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
    content_origin: ContentOrigin
    sanitized_html: str | None
    authors: list[str]
    tags: list[str]
    media: list[ArticleMediaOut]
    story_links: list[ArticleStoryLinkOut]
    evidence_references: list[ArticleEvidenceReferenceOut]
    advanced: ArticleAdvancedOut
