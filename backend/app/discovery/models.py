from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class DiscoveryItem:
    source_platform: str
    source_name: str
    external_id: str
    title: str
    url: str | None
    summary: str
    published_at: datetime | None
    image_url: str | None
    author: str | None
    categories: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedArticle:
    url: str
    final_url: str
    title: str
    summary: str
    content_text: str
    content_html: str | None
    author: str | None
    published_at: datetime | None
    image_url: str | None
    extraction_status: str
    extraction_warnings: list[str] = field(default_factory=list)
