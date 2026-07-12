from __future__ import annotations

from app.core.safe_http import (
    MAX_REDIRECTS,
    MAX_RESPONSE_BYTES,
    SafeHttpClient,
    SafeHttpError,
)
from app.discovery.article_extractor import extract_article
from app.discovery.models import DiscoveryItem
from app.stories.schemas import ManualUrlInput

MAX_MANUAL_REDIRECTS = MAX_REDIRECTS
MAX_MANUAL_RESPONSE_BYTES = MAX_RESPONSE_BYTES
ManualIntakeFetchError = SafeHttpError
ManualIntakeHttpClient = SafeHttpClient


def manual_discovery_item(request: ManualUrlInput) -> DiscoveryItem:
    submitted_url = str(request.url)
    return DiscoveryItem(
        source_platform="manual",
        source_name="",
        external_id=submitted_url,
        title=request.title or submitted_url,
        url=submitted_url,
        summary="",
        published_at=None,
        image_url=None,
        author=None,
        metadata={"intake_kind": "url"},
    )


__all__ = [
    "MAX_MANUAL_REDIRECTS",
    "MAX_MANUAL_RESPONSE_BYTES",
    "ManualIntakeFetchError",
    "ManualIntakeHttpClient",
    "extract_article",
    "manual_discovery_item",
]
