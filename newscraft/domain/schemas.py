from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from newscraft.domain.enums import ArticleStatus, ContentDraftStatus


class ArticleBase(BaseModel):
    title: str
    url: str | None = None
    external_id: str | None = None
    source: str = "Unknown"
    source_type: str | None = None
    connector: str | None = None
    source_group: str | None = None
    author: str | None = None
    summary: str | None = None
    content: str | None = None
    published_at: datetime | str | None = None
    collected_at: datetime | None = None
    category: str | None = None
    score: float = 0
    status: str = ArticleStatus.NEW
    language: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class ArticleCreate(ArticleBase):
    pass


class ArticleRead(ArticleBase):
    id: int
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="article_metadata")

    model_config = ConfigDict(from_attributes=True)


class ArticleStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def valid_status(cls, value):
        if value not in set(ArticleStatus):
            raise ValueError(f"invalid article status: {value}")
        return value


class SourceCreate(BaseModel):
    name: str
    source_type: str
    connector: str
    url: str | None = None
    language: str | None = None
    category: str | None = None
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class SourceUpdate(BaseModel):
    name: str | None = None
    source_type: str | None = None
    connector: str | None = None
    url: str | None = None
    language: str | None = None
    category: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class SourceRead(SourceCreate):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IngestionRunCreate(BaseModel):
    selected_sources: list[str] = Field(default_factory=list)


class IngestionRunRead(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    selected_sources: list[Any]
    total_fetched: int
    total_saved: int
    total_duplicates: int
    total_failed: int
    error_message: str | None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="run_metadata")

    model_config = ConfigDict(from_attributes=True)


class ApprovedArticleRead(BaseModel):
    id: int
    article_id: int | None
    title: str
    url: str | None
    source: str | None
    source_type: str | None
    connector: str | None
    source_group: str | None
    published_at: datetime | None
    summary: str | None
    category: str | None
    score: float
    notes: str | None
    approved_at: datetime
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="article_metadata")

    model_config = ConfigDict(from_attributes=True)


class PaperAssetRead(BaseModel):
    id: int
    article_id: int | None
    pdf_path: str | None
    text_path: str | None
    notebooklm_brief_path: str | None
    instagram_brief_path: str | None
    podcast_brief_path: str | None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="asset_metadata")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContentDraftCreate(BaseModel):
    article_id: int
    platform: str
    draft_text: str
    status: str = ContentDraftStatus.DRAFT
    human_notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def valid_status(cls, value):
        if value not in set(ContentDraftStatus):
            raise ValueError(f"invalid content draft status: {value}")
        return value


class ContentDraftUpdate(BaseModel):
    platform: str | None = None
    draft_text: str | None = None
    status: str | None = None
    human_notes: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, value):
        if value is not None and value not in set(ContentDraftStatus):
            raise ValueError(f"invalid content draft status: {value}")
        return value


class ContentDraftRead(ContentDraftCreate):
    id: int
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="draft_metadata")

    model_config = ConfigDict(from_attributes=True)
