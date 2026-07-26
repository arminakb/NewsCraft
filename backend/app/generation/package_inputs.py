from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from app.generation.models import (
    BrandProfile,
    ContentPack,
    GenerationRun,
    PromptTemplateVersion,
)
from app.generation.multiplatform import (
    PLATFORM_PROMPT_PURPOSE,
    deduplicate_preserving_order,
    ordered_distinct_citations,
)
from app.generation.platform_schemas import Platform
from app.generation.platform_validation import (
    revision_gates_from_issues,
    validate_platform_payload,
)
from app.generation.revision_fence import RegenerationFenceOwner
from app.research.schemas import CitationRef
from app.stories.evidence import EvidenceRecord
from app.stories.models import StoryRevision


@dataclass(frozen=True, slots=True)
class RegenerationContext:
    variant_id: UUID
    base_revision_id: UUID
    base_content_hash: str


@dataclass(frozen=True, slots=True)
class PackInputs:
    payload: dict[str, Any]
    budget_started_at: datetime
    story_revision: StoryRevision
    brand: BrandProfile
    profile_id: UUID
    platforms: list[Platform]
    prompts: dict[Platform, PromptTemplateVersion]
    story_citations: list[CitationRef]
    evidence: dict[UUID, EvidenceRecord]
    source_media: list[dict[str, Any]]
    canonical_json: dict[str, Any]
    brand_json: dict[str, Any]
    first_story_pack_id: UUID | None
    regeneration: RegenerationContext | None


@dataclass(slots=True)
class PackProgress:
    cumulative_cost: Decimal
    pack: ContentPack | None = None
    results: list[dict[str, str]] = field(default_factory=list)
    completed_platforms: list[Platform] = field(default_factory=list)
    has_errors: bool = False
    regeneration_owner: RegenerationFenceOwner | None = None


@dataclass(frozen=True, slots=True)
class GeneratedPlatform:
    platform: Platform
    prompt: PromptTemplateVersion
    default_direction: Literal["ltr", "rtl"] | None
    run: GenerationRun
    attempt: Any
    authored: Any
    content: dict[str, Any] | None
    evidence_map: list[dict[str, Any]]
    validation_results: list[dict[str, Any]] | None
    has_errors: bool


def requested_platforms(payload: dict[str, Any]) -> list[Platform]:
    raw = payload.get("platforms")
    if raw is None and payload.get("platform") == "telegram":
        raw = ["telegram"]
    if not isinstance(raw, list) or not raw or any(item not in PLATFORM_PROMPT_PURPOSE for item in raw):
        from app.jobs.errors import PermanentJobError

        raise PermanentJobError(
            code="generation_job_platforms_invalid",
            message="Generation job platforms are invalid",
        )
    return deduplicate_preserving_order(raw)


def prompt_mappings(
    payload: dict[str, Any],
    platforms: list[Platform],
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt_ids = payload.get("platform_prompt_template_version_ids")
    if prompt_ids is None and payload.get("platform_prompt_template_version_id"):
        prompt_ids = {"telegram": payload["platform_prompt_template_version_id"]}
    checksums = payload.get("platform_prompt_checksums")
    if (
        checksums is None
        and platforms == ["telegram"]
        and payload.get("platform") == "telegram"
        and payload.get("platform_prompt_checksum")
    ):
        checksums = {"telegram": payload["platform_prompt_checksum"]}
    if (
        not isinstance(prompt_ids, dict)
        or set(prompt_ids) != set(platforms)
        or not isinstance(checksums, dict)
        or set(checksums) != set(platforms)
    ):
        from app.jobs.errors import PermanentJobError

        raise PermanentJobError(
            code="generation_prompt_mapping_invalid",
            message="Generation prompt mapping is invalid",
        )
    return prompt_ids, checksums


def regeneration_context(payload: dict[str, Any]) -> RegenerationContext | None:
    if payload.get("variant_id") is None:
        return None
    from app.jobs.errors import PermanentJobError

    try:
        regeneration = RegenerationContext(
            variant_id=UUID(str(payload["variant_id"])),
            base_revision_id=UUID(str(payload["base_revision_id"])),
            base_content_hash=str(payload["base_content_hash"]),
        )
    except KeyError, TypeError, ValueError:
        raise PermanentJobError(
            code="generation_regeneration_base_invalid",
            message="Regeneration base revision is invalid",
        ) from None
    if re.fullmatch(r"[0-9a-f]{64}", regeneration.base_content_hash) is None:
        raise PermanentJobError(
            code="generation_regeneration_base_invalid",
            message="Regeneration base revision is invalid",
        )
    return regeneration


def canonical_json(story_revision: StoryRevision) -> dict[str, Any]:
    return {
        "narrative": story_revision.narrative,
        "facts": story_revision.facts,
        "disagreements": story_revision.disagreements,
        "angles": story_revision.angles,
        "citations": story_revision.citations,
    }


def brand_json(brand: BrandProfile) -> dict[str, Any]:
    return {
        "id": str(brand.id),
        "name": brand.name,
        "output_language": brand.output_language,
        "tone": brand.tone,
        "editorial_rules": brand.editorial_rules,
        "attribution_rules": brand.attribution_rules,
        "default_hashtags": brand.default_hashtags,
        "platform_preferences": brand.platform_preferences,
    }


def telegram_direction(
    platform: Platform,
    brand: BrandProfile,
) -> Literal["ltr", "rtl"] | None:
    if platform != "telegram":
        return None
    preferences = dict(brand.platform_preferences or {}).get("telegram", {})
    return preferences.get(
        "direction",
        "rtl" if brand.output_language == "fa" else "ltr",
    )


def revision_material(
    platform: Platform,
    authored: Any,
    story_citations: list[CitationRef],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]] | None, bool]:
    if platform == "telegram":
        return (
            None,
            [item.model_dump(mode="json") for item in story_citations],
            None,
            False,
        )
    content = authored.model_dump(mode="json")
    evidence_map = [item.model_dump(mode="json") for item in ordered_distinct_citations(authored)]
    issues = validate_platform_payload(platform, authored)
    return (
        content,
        evidence_map,
        revision_gates_from_issues(issues),
        any(item.severity == "error" for item in issues),
    )
