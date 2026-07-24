from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, timestamp_now, uuid_pk


class CodexPairingSession(Base):
    __tablename__ = "codex_pairing_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    code_prefix: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    device_name: Mapped[str] = mapped_column(Text, nullable=False)
    requested_scopes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        CheckConstraint("octet_length(code_hash) = 32", name="ck_codex_pairing_code_hash"),
        CheckConstraint("length(code_prefix) = 12", name="ck_codex_pairing_code_prefix"),
        CheckConstraint(
            "jsonb_typeof(requested_scopes) = 'array'",
            name="ck_codex_pairing_scopes_array",
        ),
        CheckConstraint(
            "status IN ('pending', 'paired', 'cancelled', 'expired')",
            name="ck_codex_pairing_session_status",
        ),
        Index("ix_codex_pairing_sessions_status_expiry", "status", "expires_at"),
    )


class CodexConnection(Base):
    __tablename__ = "codex_connections"

    id: Mapped[uuid.UUID] = uuid_pk()
    device_name: Mapped[str] = mapped_column(Text, nullable=False)
    credential_prefix: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    credential_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    credential_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pairing_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("codex_pairing_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        CheckConstraint(
            "octet_length(credential_hash) = 32",
            name="ck_codex_connection_credential_hash",
        ),
        CheckConstraint(
            "length(credential_prefix) = 12",
            name="ck_codex_connection_credential_prefix",
        ),
        CheckConstraint(
            "length(credential_fingerprint) = 16",
            name="ck_codex_connection_fingerprint",
        ),
        CheckConstraint(
            "jsonb_typeof(scopes) = 'array'",
            name="ck_codex_connection_scopes_array",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_codex_connection_status",
        ),
        Index("ix_codex_connections_status_expiry", "status", "expires_at"),
        Index("ix_codex_connections_last_heartbeat", "last_heartbeat_at"),
    )


class CodexRateLimitBucket(Base):
    __tablename__ = "codex_rate_limit_buckets"

    key_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(nullable=False, server_default="1")
    updated_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        CheckConstraint("octet_length(key_hash) = 32", name="ck_codex_rate_limit_key_hash"),
        CheckConstraint("request_count > 0", name="ck_codex_rate_limit_count"),
        Index("ix_codex_rate_limit_updated", "updated_at"),
    )


class CodexIdempotencyRecord(Base):
    __tablename__ = "codex_idempotency_records"

    key_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        CheckConstraint(
            "octet_length(key_hash) = 32",
            name="ck_codex_idempotency_key_hash",
        ),
        Index("ix_codex_idempotency_created", "created_at"),
    )


__all__ = [
    "CodexConnection",
    "CodexIdempotencyRecord",
    "CodexPairingSession",
    "CodexRateLimitBucket",
]
