from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramVariantPayload,
    Platform,
    PlatformPayload,
    TelegramVariantPayload,
    XVariantPayload,
)
from app.generation.platform_validation import validate_platform_payload
from app.generation.telegram_schema import TelegramRewriteOutput
from app.research.schemas import CitationRef, Claim

PLATFORM_PROMPT_PURPOSE: dict[Platform, str] = {
    "telegram": "telegram_pack",
    "instagram": "instagram_pack",
    "x": "x_pack",
    "blog": "blog_pack",
}

PLATFORM_ORDER: tuple[Platform, ...] = ("telegram", "instagram", "x", "blog")


class MultiPlatformPackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_revision_id: UUID
    brand_profile_id: UUID
    platforms: list[Platform] = Field(min_length=1)
    generation_provider_profile_id: UUID


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
                *(
                    f"{slide.headline}\n{slide.body}"
                    for slide in sorted(payload.carousel, key=lambda item: item.order)
                ),
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


class GenerationContext(Protocol):
    provider: Any
    repository: Any

    async def require_active_prompt_version(self, purpose: str) -> Any: ...

    async def start_generation_run(self, platform: Platform, *, prompt_template_version_id: UUID) -> Any: ...

    def request_for(self, platform: Platform, *, prompt_version: Any) -> Any: ...

    async def record_attempt(self, run: Any, provider_result: Any) -> Any: ...

    def release_two_telegram_content(self, rewrite: TelegramRewriteOutput) -> dict[str, Any]: ...

    async def validated_telegram_evidence_map(self) -> list[CitationRef]: ...

    async def validate_manual_platform_citations(self, platform: Platform, payload: PlatformPayload) -> None: ...


class GeneratedPack(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    revisions: list[Any]


async def generate_platform_variants(
    request: MultiPlatformPackRequest,
    context: GenerationContext,
) -> GeneratedPack:
    revisions: list[Any] = []
    for platform in deduplicate_preserving_order(request.platforms):
        prompt = await context.require_active_prompt_version(PLATFORM_PROMPT_PURPOSE[platform])
        run = await context.start_generation_run(platform, prompt_template_version_id=prompt.id)
        provider_result = await context.provider.generate(
            context.request_for(platform, prompt_version=prompt)
        )
        attempt = await context.record_attempt(run, provider_result)
        if platform == "telegram":
            rewrite = TelegramRewriteOutput.model_validate(provider_result.output)
            stored_content = context.release_two_telegram_content(rewrite)
            payload = TelegramVariantPayload.model_validate(stored_content)
            evidence_map = await context.validated_telegram_evidence_map()
        else:
            payload = MANUAL_PLATFORM_ADAPTERS[platform].model_validate(provider_result.output)
            await context.validate_manual_platform_citations(platform, payload)
            stored_content = payload.model_dump(mode="json")
            evidence_map = ordered_distinct_citations(payload)
        issues = validate_platform_payload(platform, payload)
        revisions.append(
            await context.repository.create_revision(
                platform,
                stored_content,
                [item.model_dump(mode="json") for item in evidence_map],
                [item.model_dump(mode="json") for item in issues],
                attempt.id,
            )
        )
    return GeneratedPack(revisions=revisions)
