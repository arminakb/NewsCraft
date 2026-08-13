from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class SourceFetchTarget(Protocol):
    """Everything the fetch and parse helpers read off a source.

    Both the ORM `Source` row and the frozen `PreparedSource` snapshot the
    ingestion workflow hands to network code satisfy this, so the helpers can
    be annotated once instead of claiming a `Source` they never mutate.
    """

    @property
    def name(self) -> str: ...

    @property
    def platform(self) -> str: ...

    @property
    def feed_url(self) -> str | None: ...

    @property
    def telegram_username(self) -> str | None: ...

    @property
    def default_timezone(self) -> str: ...

    @property
    def etag(self) -> str | None: ...

    @property
    def last_modified(self) -> str | None: ...


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
    storage_path: str | None = None
    checksum_sha256: str | None = None
    byte_length: int | None = None
    fetch_status: str = "remote_only"


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
