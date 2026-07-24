from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, LargeBinary, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, timestamp_now, uuid_pk


class EncryptedSecret(Base):
    __tablename__ = "encrypted_secrets"

    id: Mapped[uuid.UUID] = uuid_pk()
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    owner_type: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = timestamp_now()
    last_rotated_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        CheckConstraint("octet_length(nonce) = 12", name="ck_encrypted_secrets_nonce_length"),
        CheckConstraint("octet_length(ciphertext) >= 16", name="ck_encrypted_secrets_ciphertext_length"),
        UniqueConstraint("owner_type", "owner_id", "purpose", name="uq_encrypted_secret_owner_purpose"),
        Index("ix_encrypted_secrets_key_version", "key_version"),
    )


class SecurityAuditEvent(Base):
    __tablename__ = "security_audit_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    required_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('attempted', 'succeeded', 'rejected', 'failed')",
            name="ck_security_audit_outcome",
        ),
        Index("ix_security_audit_created", created_at.desc()),
        Index("ix_security_audit_actor_created", "actor_type", "actor_id", created_at.desc()),
        Index("ix_security_audit_resource_created", "resource_type", "resource_id", created_at.desc()),
    )


__all__ = ["EncryptedSecret", "SecurityAuditEvent"]
