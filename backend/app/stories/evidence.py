from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from app.normalization.urls import normalize_url

if TYPE_CHECKING:
    from app.discovery.models import ExtractedArticle
    from app.stories.schemas import ManualTextInput


@dataclass(frozen=True, slots=True)
class EvidenceInput:
    content_item_id: UUID | None
    title: str | None
    content_text: str
    source_url: str | None
    authors: list[str]
    published_at: datetime | None
    captured_at: datetime
    summary: str | None = None
    content_html: str | None = None
    source_label: str | None = None
    payload_kind: str | None = None
    request_url: str | None = None
    final_url: str | None = None
    raw_text: str | None = None
    extraction_status: str | None = None
    extraction_warnings: tuple[str, ...] = ()

    @classmethod
    def from_extracted_article(
        cls,
        article: ExtractedArticle,
        *,
        title_override: str | None = None,
    ) -> EvidenceInput:
        return cls(
            content_item_id=None,
            title=title_override if title_override is not None else article.title,
            content_text=article.content_text,
            source_url=article.final_url or None,
            authors=[article.author] if article.author else [],
            published_at=article.published_at,
            captured_at=datetime.now(UTC),
            summary=article.summary or None,
            content_html=article.content_html,
            payload_kind="manual_url_input",
            request_url=article.url,
            final_url=article.final_url or None,
            raw_text=None,
            extraction_status=article.extraction_status,
            extraction_warnings=tuple(article.extraction_warnings),
        )

    @classmethod
    def from_operator_text(cls, request: ManualTextInput) -> EvidenceInput:
        source_url = str(request.source_url) if request.source_url is not None else None
        return cls(
            content_item_id=None,
            title=request.title,
            content_text=request.text,
            source_url=source_url,
            authors=[],
            published_at=None,
            captured_at=datetime.now(UTC),
            source_label=request.source_label,
            payload_kind="manual_text_input",
            request_url="manual://operator",
            final_url=None,
            raw_text=request.text,
        )


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
