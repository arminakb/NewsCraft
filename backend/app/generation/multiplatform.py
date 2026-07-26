from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from pydantic import BaseModel

from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramVariantPayload,
    Platform,
    PlatformPayload,
    XVariantPayload,
)
from app.research.schemas import CitationRef, Claim

PLATFORM_PROMPT_PURPOSE: dict[Platform, str] = {
    "telegram": "telegram_pack",
    "instagram": "instagram_pack",
    "x": "x_pack",
    "blog": "blog_pack",
}

PLATFORM_ORDER: tuple[Platform, ...] = ("telegram", "instagram", "x", "blog")


def deduplicate_preserving_order[T](values: Iterable[T]) -> list[T]:
    result: list[T] = []
    seen: set[T] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _citations(payload: PlatformPayload) -> list[CitationRef]:
    if isinstance(payload, InstagramVariantPayload | BlogVariantPayload):
        return list(payload.citations)
    if isinstance(payload, XVariantPayload):
        return [citation for post in payload.posts for citation in post.citations]
    return []


def ordered_distinct_citations(payload: PlatformPayload) -> list[CitationRef]:
    result: list[CitationRef] = []
    seen: set[tuple[str, UUID, str | None, str, str]] = set()
    for citation in _citations(payload):
        identity = (
            citation.evidence_key,
            citation.evidence_snapshot_id,
            str(citation.source_url) if citation.source_url is not None else None,
            citation.locator,
            citation.excerpt_sha256,
        )
        if identity in seen:
            continue
        seen.add(identity)
        result.append(citation)
    return result


def payload_claims(platform: Platform, payload: PlatformPayload) -> list[Claim]:
    """Map complete manual-platform copy to the shared citation-integrity contract."""

    if platform == "instagram" and isinstance(payload, InstagramVariantPayload):
        copy = "\n".join(
            part
            for part in [
                payload.hook,
                payload.caption,
                *(f"{slide.headline}\n{slide.body}" for slide in sorted(payload.carousel, key=lambda item: item.order)),
            ]
            if part.strip()
        )
        return [Claim(text=copy, citations=payload.citations)]
    if platform == "x" and isinstance(payload, XVariantPayload):
        return [Claim(text=post.text, citations=post.citations) for post in payload.posts]
    if platform == "blog" and isinstance(payload, BlogVariantPayload):
        return [
            Claim(
                text="\n".join([payload.title, *payload.headings, payload.body_markdown]),
                citations=payload.citations,
            )
        ]
    raise ValueError(f"Platform {platform} payload type does not match")


MANUAL_PLATFORM_ADAPTERS: dict[Platform, type[BaseModel]] = {
    "instagram": InstagramVariantPayload,
    "x": XVariantPayload,
    "blog": BlogVariantPayload,
}
