from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class MediaCandidate:
    original_url: str
    normalized_url: str
    kind: str
    source_field: str
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None
    title: str | None = None
    confidence: float = 1.0


@dataclass(slots=True)
class ParsedSourceItem:
    external_id_raw: str | None
    external_id_norm: str
    source_url: str | None
    source_url_norm: str | None
    canonical_url_candidate: str | None
    title: str
    summary: str
    content_html: str | None
    content_text: str
    author: str | None
    categories: list[str]
    published_raw: str | None
    published_at: datetime | None
    date_parse_status: str
    media_candidates: list[MediaCandidate] = field(default_factory=list)
    parser_meta: dict = field(default_factory=dict)


@dataclass(slots=True)
class ParsedSourcePayload:
    items: list[ParsedSourceItem]
    warnings: list[str] = field(default_factory=list)
    feed_meta: dict = field(default_factory=dict)
