from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.models import AutomationDispatch, AutomationRoute
from app.jobs.repository import EnqueueJobResult, JobRepository
from app.jobs.types import JobOrigin
from app.research.models import ResearchRun
from app.stories.models import StoryRevision


class TelegramContinuationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dispatch_id: UUID
    force_review: bool = False


class TelegramResearchContinuation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: Literal["telegram.route.process"]
    payload: TelegramContinuationPayload
    idempotency_prefix: str
    subscriber_id: str
    expected_route_id: UUID
    expected_story_id: UUID
    expected_story_revision_id: UUID
    expected_provider_profile_id: UUID
    expected_research_mode: Literal["auto_if_incomplete"]

    def validate_identity(self) -> TelegramResearchContinuation:
        dispatch_id = self.payload.dispatch_id
        if self.subscriber_id != f"telegram-dispatch:{dispatch_id}":
            raise ValueError("research continuation subscriber identity is invalid")
        if self.idempotency_prefix != f"telegram-route-process-after-research:{dispatch_id}":
            raise ValueError("research continuation key is invalid")
        return self


class ContentPackContinuationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: UUID
    brand_profile_id: UUID
    platform: Literal["telegram"]
    generation_provider_profile_id: UUID
    canonical_prompt_template_version_id: UUID
    platform_prompt_template_version_id: UUID
    research_mode: Literal["auto_if_incomplete"]
    research_provider_profile_id: UUID
    canonical_prompt_checksum: str
    platform_prompt_checksum: str


class ContentPackResearchContinuation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: Literal["content_pack.generate"]
    payload: ContentPackContinuationPayload
    idempotency_prefix: str
    subscriber_id: str
    expected_story_id: UUID
    expected_provider_profile_id: UUID

    def validate_identity(self) -> ContentPackResearchContinuation:
        if self.payload.story_id != self.expected_story_id:
            raise ValueError("content pack continuation story identity is invalid")
        if self.payload.research_provider_profile_id != self.expected_provider_profile_id:
            raise ValueError("content pack continuation provider identity is invalid")
        expected = f"content-pack:{self.expected_story_id}:{self.subscriber_id}"
        if self.idempotency_prefix != expected:
            raise ValueError("content pack continuation key is invalid")
        return self


def normalize_continuation(value: object) -> dict:
    if isinstance(value, dict) and value.get("job_type") == "content_pack.generate":
        parsed = ContentPackResearchContinuation.model_validate(value).validate_identity()
    else:
        parsed = TelegramResearchContinuation.model_validate(value).validate_identity()
    return parsed.model_dump(mode="json")


def append_unique_continuation(payload: dict, continuation: dict | None) -> tuple[dict, bool]:
    existing_values = list(payload.get("continuations") or [])
    legacy = payload.get("continuation")
    if legacy is not None:
        existing_values.append(legacy)
    normalized: list[dict] = []
    seen: set[str] = set()
    for value in existing_values:
        item = normalize_continuation(value)
        identity = item["subscriber_id"]
        if identity not in seen:
            normalized.append(item)
            seen.add(identity)
    created = False
    if continuation is not None:
        item = normalize_continuation(continuation)
        if item["subscriber_id"] not in seen:
            normalized.append(item)
            created = True
    updated = {key: value for key, value in payload.items() if key != "continuation"}
    return {**updated, "continuations": normalized}, created


async def enqueue_bound_continuation(
    session: AsyncSession,
    *,
    descriptor: dict,
    run: ResearchRun,
    result_revision: StoryRevision,
) -> EnqueueJobResult:
    value, dispatch = await _validate_bound_context(
        session,
        descriptor=descriptor,
        run=run,
        result_revision=result_revision,
    )
    if isinstance(value, TelegramResearchContinuation):
        assert dispatch is not None
        dispatch.story_revision_id = result_revision.id
        dispatch.status = "captured"
        dispatch.error_code = None
        dispatch.error_message = None
    continuation_payload = {
        **value.payload.model_dump(mode="json"),
        "completed_research_run_id": str(run.id),
    }
    if isinstance(value, ContentPackResearchContinuation):
        continuation_payload["research_result_story_revision_id"] = str(result_revision.id)
    return await JobRepository(session).enqueue_job(
        job_type=value.job_type,
        payload=continuation_payload,
        idempotency_key=f"{value.idempotency_prefix}:{result_revision.id}",
        origin=JobOrigin.AUTOMATION,
    )


async def continuation_can_reuse_result(
    session: AsyncSession,
    *,
    descriptor: dict,
    run: ResearchRun,
    result_revision: StoryRevision,
) -> bool:
    try:
        await _validate_bound_context(
            session,
            descriptor=descriptor,
            run=run,
            result_revision=result_revision,
        )
    except ValueError:
        return False
    return True


async def _validate_bound_context(
    session: AsyncSession,
    *,
    descriptor: dict,
    run: ResearchRun,
    result_revision: StoryRevision,
) -> tuple[TelegramResearchContinuation | ContentPackResearchContinuation, AutomationDispatch | None]:
    if descriptor.get("job_type") == "content_pack.generate":
        value = ContentPackResearchContinuation.model_validate(descriptor).validate_identity()
        if (
            value.expected_story_id != run.story_id
            or value.expected_provider_profile_id != run.provider_profile_id
            or result_revision.story_id != run.story_id
        ):
            raise ValueError("content pack research continuation binding is invalid")
        return value, None
    value = TelegramResearchContinuation.model_validate(descriptor).validate_identity()
    dispatch = await session.scalar(
        select(AutomationDispatch).where(AutomationDispatch.id == value.payload.dispatch_id).with_for_update()
    )
    if dispatch is None:
        raise ValueError("research continuation dispatch is missing")
    route = await session.scalar(
        select(AutomationRoute).where(AutomationRoute.id == dispatch.route_id).with_for_update()
    )
    current_revision = await session.get(StoryRevision, dispatch.story_revision_id)
    if route is None or current_revision is None:
        raise ValueError("research continuation context is missing")
    configured_profile = (route.content_filters or {}).get("research_provider_profile_id")
    try:
        configured_profile_id = UUID(str(configured_profile))
    except TypeError, ValueError:
        raise ValueError("research continuation profile is invalid") from None
    if (
        value.expected_route_id != route.id
        or value.expected_story_id != run.story_id
        or value.expected_provider_profile_id != run.provider_profile_id
        or value.expected_research_mode != route.research_mode
        or configured_profile_id != run.provider_profile_id
        or current_revision.story_id != run.story_id
        or result_revision.story_id != run.story_id
        or dispatch.story_revision_id != value.expected_story_revision_id
    ):
        raise ValueError("research continuation binding is invalid")
    ancestor = result_revision
    visited: set[UUID] = set()
    while ancestor.id != value.expected_story_revision_id:
        if ancestor.id in visited or ancestor.parent_revision_id is None:
            raise ValueError("research continuation result lineage is invalid")
        visited.add(ancestor.id)
        parent = await session.get(StoryRevision, ancestor.parent_revision_id)
        if parent is None or parent.story_id != run.story_id:
            raise ValueError("research continuation result lineage is invalid")
        ancestor = parent
    if result_revision.id == value.expected_story_revision_id:
        raise ValueError("research continuation result must descend from expected revision")
    return value, dispatch


__all__ = [
    "ContentPackResearchContinuation",
    "TelegramResearchContinuation",
    "append_unique_continuation",
    "continuation_can_reuse_result",
    "enqueue_bound_continuation",
    "normalize_continuation",
]
