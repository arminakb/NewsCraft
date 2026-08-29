from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.generation.commands import GeneratePackRequest
from app.generation.errors import InvalidGenerationRequest
from app.generation.models import BrandProfile
from app.generation.multiplatform import (
    PLATFORM_PROMPT_PURPOSE,
    deduplicate_preserving_order,
)
from app.jobs.models import WorkflowJob
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin
from app.research.models import ResearchRun
from app.research.service import ResearchRequestError, ResearchService
from app.stories.models import Story, StoryRevision


async def request_content_pack(
    service: Any,
    story_id: UUID,
    request: GeneratePackRequest,
    *,
    evaluation_run_id: UUID | None = None,
) -> JobAcceptedOut:
    platforms = deduplicate_preserving_order(request.platforms)
    canonical = await service.require_active_prompt_version("canonical_story")
    platform_prompts = {
        platform: await service.require_active_prompt_version(PLATFORM_PROMPT_PURPOSE[platform])
        for platform in platforms
    }
    _profile, provider_identity = await service._require_profile(request.generation_provider_profile_id)
    brand = await _load_story_and_brand(service, story_id, request.brand_profile_id)
    _validate_research_options(request)
    bound_payload = await _bound_research_payload(service, story_id, request)
    payload = (
        request.model_dump(mode="json", exclude={"research_run_id", "brand_profile_id"})
        | bound_payload
        | {
            "story_id": str(story_id),
            "brand_profile_id": str(brand.id),
            "platforms": platforms,
            "canonical_prompt_template_version_id": str(canonical.id),
            "platform_prompt_template_version_ids": {
                platform: str(prompt.id) for platform, prompt in platform_prompts.items()
            },
            "canonical_prompt_checksum": canonical.checksum_sha256,
            "platform_prompt_checksums": {
                platform: prompt.checksum_sha256 for platform, prompt in platform_prompts.items()
            },
            "generation_provider_configuration_revision": provider_identity.revision,
            "generation_provider_configuration_checksum": provider_identity.checksum,
        }
    )
    if evaluation_run_id is not None:
        payload["evaluation_run_id"] = str(evaluation_run_id)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = await _enqueue(service, story_id, request, payload, digest)
    await service.session.flush()
    return result


async def _load_story_and_brand(
    service: Any,
    story_id: UUID,
    brand_profile_id: UUID | None,
) -> BrandProfile:
    story = await service.session.scalar(
        select(Story).where(Story.id == story_id, Story.superseded_by_id.is_(None)).with_for_update()
    )
    if story is None:
        raise InvalidGenerationRequest("active story not found")
    brand = (
        await service.session.get(BrandProfile, brand_profile_id)
        if brand_profile_id is not None
        else await service.session.scalar(
            select(BrandProfile).where(BrandProfile.is_default.is_(True)).with_for_update()
        )
    )
    if brand is None:
        message = (
            "brand profile not found" if brand_profile_id is not None else "default editorial profile is not configured"
        )
        raise InvalidGenerationRequest(message, code="editorial_profile_unavailable")
    return brand


def _validate_research_options(request: GeneratePackRequest) -> None:
    if request.research_mode == "auto_if_incomplete" and request.research_provider_profile_id is None:
        raise InvalidGenerationRequest("auto research requires research_provider_profile_id")
    if request.research_run_id is not None and (
        request.research_mode != "off" or request.research_provider_profile_id is not None
    ):
        raise InvalidGenerationRequest("bound research run cannot request another research mode")


async def _bound_research_payload(
    service: Any,
    story_id: UUID,
    request: GeneratePackRequest,
) -> dict[str, str]:
    if request.research_run_id is None:
        return {}
    run = await service.session.get(ResearchRun, request.research_run_id)
    result_revision = (
        await service.session.get(StoryRevision, run.result_story_revision_id)
        if run is not None and run.result_story_revision_id is not None
        else None
    )
    if (
        run is None
        or run.status != "succeeded"
        or run.story_id != story_id
        or result_revision is None
        or result_revision.story_id != story_id
    ):
        raise InvalidGenerationRequest("research run is not a succeeded result for this story")
    return {
        "completed_research_run_id": str(run.id),
        "research_result_story_revision_id": str(result_revision.id),
    }


async def _enqueue(
    service: Any,
    story_id: UUID,
    request: GeneratePackRequest,
    payload: dict[str, Any],
    digest: str,
) -> JobAcceptedOut:
    if request.research_mode == "auto_if_incomplete":
        return await _enqueue_after_research(service, story_id, request, payload, digest)
    return _job_out(
        await service.jobs.enqueue_job(
            job_type="content_pack.generate",
            payload=payload,
            idempotency_key=f"content-pack:{story_id}:{digest}",
            origin=JobOrigin.MANUAL,
        )
    )


async def _enqueue_after_research(
    service: Any,
    story_id: UUID,
    request: GeneratePackRequest,
    payload: dict[str, Any],
    digest: str,
) -> JobAcceptedOut:
    continuation = {
        "job_type": "content_pack.generate",
        "payload": payload,
        "idempotency_prefix": f"content-pack:{story_id}:{digest}",
        "subscriber_id": digest,
        "expected_story_id": str(story_id),
        "expected_provider_profile_id": str(request.research_provider_profile_id),
    }
    try:
        research = await ResearchService(service.session).request(
            story_id=story_id,
            mode="auto_if_incomplete",
            depth="standard",
            provider_profile_id=request.research_provider_profile_id,
            query_hint=None,
            continuation=continuation,
            prompt_template_version_id=request.research_prompt_template_version_id,
            prompt_checksum_sha256=request.research_prompt_checksum_sha256,
            query_budget=request.research_query_budget,
            page_budget=request.research_page_budget,
            time_budget_seconds=request.research_time_budget_seconds,
        )
    except ResearchRequestError as exc:
        raise InvalidGenerationRequest(str(exc)) from None
    if research.disposition != "enqueued":
        return _job_out(
            await service.jobs.enqueue_job(
                job_type="content_pack.generate",
                payload=payload,
                idempotency_key=f"content-pack:{story_id}:{digest}",
                origin=JobOrigin.MANUAL,
            )
        )
    assert research.job_id is not None
    job = await service.session.get(WorkflowJob, research.job_id)
    if job is None:
        raise InvalidGenerationRequest("research job is unavailable")
    return JobAcceptedOut(job_id=job.id, status=job.status, deduplicated=False)


def _job_out(result: Any) -> JobAcceptedOut:
    return JobAcceptedOut(
        job_id=result.job.id,
        status=result.job.status,
        deduplicated=not result.created,
    )
