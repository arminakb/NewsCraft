from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newscraft.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("url", name="uq_articles_url"),
        UniqueConstraint("source", "external_id", name="uq_articles_source_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(80))
    connector: Mapped[str | None] = mapped_column(String(80))
    source_group: Mapped[str | None] = mapped_column(String(120))
    author: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    category: Mapped[str | None] = mapped_column(String(120))
    score: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    language: Mapped[str | None] = mapped_column(String(20))
    article_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    approved: Mapped["ApprovedArticle | None"] = relationship(back_populates="article")
    assets: Mapped[list["PaperAsset"]] = relationship(back_populates="article")
    drafts: Mapped[list["ContentDraft"]] = relationship(back_populates="article")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    connector: Mapped[str] = mapped_column(String(80), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    language: Mapped[str | None] = mapped_column(String(20))
    category: Mapped[str | None] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="running")
    selected_sources: Mapped[list] = mapped_column(JSON, default=list)
    total_fetched: Mapped[int] = mapped_column(Integer, default=0)
    total_saved: Mapped[int] = mapped_column(Integer, default=0)
    total_duplicates: Mapped[int] = mapped_column(Integer, default=0)
    total_failed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    run_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    source_logs: Mapped[list["SourceRunLog"]] = relationship(back_populates="ingestion_run")


class SourceRunLog(Base):
    __tablename__ = "source_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    source_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="running")
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    saved_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    log_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="source_logs")


class ApprovedArticle(Base):
    __tablename__ = "approved_articles"
    __table_args__ = (UniqueConstraint("url", name="uq_approved_articles_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id"))
    source: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str | None] = mapped_column(String(80))
    connector: Mapped[str | None] = mapped_column(String(80))
    source_group: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(120))
    score: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    article_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(40), default="approved")

    article: Mapped[Article | None] = relationship(back_populates="approved")


class PaperAsset(Base):
    __tablename__ = "paper_assets"
    __table_args__ = (UniqueConstraint("article_id", name="uq_paper_assets_article_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id"))
    pdf_path: Mapped[str | None] = mapped_column(String(1000))
    text_path: Mapped[str | None] = mapped_column(String(1000))
    notebooklm_brief_path: Mapped[str | None] = mapped_column(String(1000))
    instagram_brief_path: Mapped[str | None] = mapped_column(String(1000))
    podcast_brief_path: Mapped[str | None] = mapped_column(String(1000))
    asset_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article: Mapped[Article | None] = relationship(back_populates="assets")


class ContentDraft(Base):
    __tablename__ = "content_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    human_notes: Mapped[str | None] = mapped_column(Text)
    draft_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    article: Mapped[Article] = relationship(back_populates="drafts")
