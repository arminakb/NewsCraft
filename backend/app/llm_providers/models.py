from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, timestamp_now, uuid_pk


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_model: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encrypted_secrets.id", ondelete="RESTRICT"), nullable=True
    )
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    health_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unchecked")
    generation_capability: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    research_capability: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_tested_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    ownership: Mapped[str] = mapped_column(Text, nullable=False, server_default="operator_managed")
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_llm_providers_name"),
        UniqueConstraint("secret_id", name="uq_llm_providers_secret_id"),
        CheckConstraint("protocol IN ('openai_compatible', 'fake')", name="ck_llm_providers_protocol"),
        CheckConstraint(
            "health_status IN ('unchecked', 'healthy', 'degraded', 'unhealthy')",
            name="ck_llm_providers_health_status",
        ),
        CheckConstraint(
            "generation_capability IN ('unknown', 'ready', 'unavailable')",
            name="ck_llm_providers_generation_capability",
        ),
        CheckConstraint(
            "research_capability IN ('unknown', 'ready', 'unavailable')",
            name="ck_llm_providers_research_capability",
        ),
        CheckConstraint(
            "ownership IN ('system_managed', 'operator_managed')",
            name="ck_llm_providers_ownership",
        ),
        CheckConstraint(
            "last_test_latency_ms IS NULL OR last_test_latency_ms >= 0",
            name="ck_llm_providers_last_test_latency_ms",
        ),
        CheckConstraint(
            "(protocol = 'fake' AND base_url IS NULL AND secret_id IS NULL) OR "
            "(protocol = 'openai_compatible' AND base_url IS NOT NULL)",
            name="ck_llm_providers_protocol_shape",
        ),
        CheckConstraint(
            "protocol != 'openai_compatible' OR ("
            "COALESCE(jsonb_typeof(settings->'pricing') = 'object', false) AND "
            "COALESCE(jsonb_typeof(settings->'research_budgets') = 'object', false))",
            name="ck_llm_providers_required_settings",
        ),
        Index("ix_llm_providers_enabled_name", "enabled", "name"),
    )


__all__ = ["LLMProvider"]
