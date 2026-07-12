from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.normalization.urls import normalize_url


@dataclass(frozen=True, slots=True)
class EvidenceInput:
    content_item_id: UUID | None
    title: str | None
    content_text: str
    source_url: str | None
    authors: list[str]
    published_at: datetime | None
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class CapturedEvidence:
    input: EvidenceInput
    evidence_key: str
    content_sha256: str

    @property
    def source_url(self) -> str | None:
        return self.input.source_url


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_key: str
    evidence_snapshot_id: UUID
    content_item_id: UUID | None
    title: str | None
    content_text: str
    content_sha256: str
    source_url: str | None
    authors: tuple[str, ...]
    published_at: datetime | None
    captured_at: datetime


def build_evidence_key(
    *,
    content_item_id: UUID | None,
    source_url: str | None,
    content_sha256: str,
) -> str:
    if content_item_id is not None:
        return f"content-item:{content_item_id}:{content_sha256}"
    if source_url is not None:
        return f"url:{normalize_url(source_url)}:{content_sha256}"
    return f"operator-text:{content_sha256}"


def capture_evidence(value: EvidenceInput) -> CapturedEvidence:
    content_sha256 = hashlib.sha256(value.content_text.encode("utf-8")).hexdigest()
    return CapturedEvidence(
        input=value,
        evidence_key=build_evidence_key(
            content_item_id=value.content_item_id,
            source_url=value.source_url,
            content_sha256=content_sha256,
        ),
        content_sha256=content_sha256,
    )
