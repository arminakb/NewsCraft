from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.generation_settings import provider_capabilities
from app.api.telegram_destinations import (
    get_job_repository,
    get_secret_resolver,
)
from app.api.telegram_schemas import (
    TelegramAutomationOptionsOut,
    TelegramResearchPolicyInput,
    TelegramRouteAcceptedOut,
    TelegramRouteBackfillIn,
    TelegramRouteCreate,
    TelegramRouteDryRunIn,
    TelegramRouteOut,
)
from app.automations.models import AutomationDispatch, AutomationRoute, TelegramSourceConfig
from app.core.redaction import redact_string
from app.core.secrets import SecretResolver
from app.db.models import Source
from app.db.session import get_session
from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplate, PromptTemplateVersion
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin
from app.publishing.models import Destination
from app.stories.models import StoryRevision

router = APIRouter(prefix="/telegram/automations", tags=["telegram"])
SessionDependency = Depends(get_session)
JobRepositoryDependency = Annotated[JobRepository, Depends(get_job_repository)]
SecretResolverDependency = Annotated[SecretResolver, Depends(get_secret_resolver)]
type ExecutableResolver = Callable[[str], str | None]


def get_executable_resolver() -> ExecutableResolver:
    return shutil.which


ExecutableResolverDependency = Annotated[ExecutableResolver, Depends(get_executable_resolver)]


def _provider_is_configured(
    profile: AIProviderProfile,
    secrets: SecretResolver,
    executable_resolver: ExecutableResolver,
) -> bool:
    capabilities, _codes = provider_capabilities(profile, secrets, executable_resolver)
    return capabilities["generation"]


def _provider_supports_research(
    profile: AIProviderProfile,
    secrets: SecretResolver,
    executable_resolver: ExecutableResolver,
) -> bool:
    capabilities, _codes = provider_capabilities(profile, secrets, executable_resolver)
    return capabilities["research"]


def _job_out(result) -> JobAcceptedOut:
    return JobAcceptedOut(
        job_id=result.job.id,
        status=result.job.status,
        deduplicated=not result.created,
    )


async def _route_or_404(session: AsyncSession, route_id: UUID) -> AutomationRoute:
    route = await session.get(AutomationRoute, route_id)
    if route is None:
        raise HTTPException(404, "Telegram automation route not found")
    return route


@router.get("", response_model=list[TelegramRouteOut])
async def list_routes(session: AsyncSession = SessionDependency):
    return list(await session.scalars(select(AutomationRoute).order_by(AutomationRoute.name)))


@router.get("/options", response_model=TelegramAutomationOptionsOut)
async def automation_options(
    session: AsyncSession = SessionDependency,
    secrets: SecretResolverDependency = None,
    executable_resolver: ExecutableResolverDependency = shutil.which,
):
    sources = list(await session.scalars(select(Source).where(Source.platform == "telegram_public")))
    source_configs = list(await session.scalars(select(TelegramSourceConfig)))
    configs_by_source = {item.source_id: item for item in source_configs}
    destinations = list(
        await session.scalars(
            select(Destination).where(Destination.platform == "telegram", Destination.enabled.is_(True))
        )
    )
    brands = list(await session.scalars(select(BrandProfile).order_by(BrandProfile.name)))
    templates = list(
        await session.scalars(select(PromptTemplate).where(PromptTemplate.purpose_key == "telegram_rewrite"))
    )
    template_ids = {item.id for item in templates}
    versions = list(
        await session.scalars(select(PromptTemplateVersion).where(PromptTemplateVersion.is_active.is_(True)))
    )
    profiles = list(await session.scalars(select(AIProviderProfile).where(AIProviderProfile.enabled.is_(True))))
    safe_profiles = []
    for profile in profiles:
        capabilities, _codes = provider_capabilities(profile, secrets, executable_resolver)
        if capabilities["generation"]:
            safe_profiles.append(
                {
                    "id": profile.id,
                    "name": profile.name,
                    "provider_type": profile.provider_type,
                    "default_model": profile.default_model,
                    "configured": True,
                    "capabilities": capabilities,
                }
            )
    return TelegramAutomationOptionsOut(
        sources=[
            {
                "id": item.id,
                "name": item.name,
                "access_mode": configs_by_source[item.id].access_mode,
            }
            for item in sources
            if item.id in configs_by_source
        ],
        destinations=[
            {
                "id": item.id,
                "name": item.name,
                "health_status": item.health_status,
                "allow_auto_publish": bool((item.settings or {}).get("allow_auto_publish")),
            }
            for item in destinations
        ],
        brand_profiles=[{"id": item.id, "name": item.name} for item in brands],
        prompt_template_versions=[
            {"id": item.id, "version": item.version} for item in versions if item.prompt_template_id in template_ids
        ],
        ai_provider_profiles=safe_profiles,
    )


@router.post("", response_model=TelegramRouteOut, status_code=201)
async def create_route(
    body: TelegramRouteCreate,
    session: AsyncSession = SessionDependency,
    secrets: SecretResolverDependency = None,
    executable_resolver: ExecutableResolverDependency = shutil.which,
):
    source = await session.scalar(select(Source).where(Source.id == body.source_id).with_for_update())
    source_config = await session.get(TelegramSourceConfig, body.source_id)
    destination = await session.get(Destination, body.destination_id)
    brand = await session.get(BrandProfile, body.brand_profile_id)
    prompt_version = await session.get(PromptTemplateVersion, body.prompt_template_version_id)
    profile = await session.get(AIProviderProfile, body.ai_provider_profile_id)
    if None in (source, source_config, destination, brand, prompt_version, profile):
        raise HTTPException(422, "Referenced Telegram route configuration is missing")
    prompt = await session.get(PromptTemplate, prompt_version.prompt_template_id)
    if source.platform != "telegram_public" or source_config.access_mode != body.access_mode:
        raise HTTPException(422, "Route source and access mode do not match")
    if destination.platform != "telegram" or not destination.enabled:
        raise HTTPException(422, "Telegram destination is not enabled")
    if prompt is None or prompt.purpose_key != "telegram_rewrite" or not prompt_version.is_active:
        raise HTTPException(422, "Route requires an active telegram_rewrite prompt")
    if not _provider_is_configured(profile, secrets, executable_resolver):
        raise HTTPException(422, "AI provider profile is not configured")
    if body.content_filters.model is None and profile.default_model is None:
        raise HTTPException(422, "Route requires a model override or provider default model")
    research_profile_id = body.content_filters.research_provider_profile_id
    if research_profile_id is not None:
        research_profile = await session.get(AIProviderProfile, research_profile_id)
        if research_profile is None or not _provider_supports_research(research_profile, secrets, executable_resolver):
            raise HTTPException(422, "Research provider profile is not configured")
    if body.publishing_policy == "auto_publish" and not bool((destination.settings or {}).get("allow_auto_publish")):
        raise HTTPException(422, "Destination does not allow auto publishing")
    existing = await session.scalar(
        select(AutomationRoute).where(
            AutomationRoute.name == body.name,
            AutomationRoute.source_id == body.source_id,
            AutomationRoute.destination_id == body.destination_id,
        )
    )
    if existing is not None:
        expected = {
            "brand_profile_id": body.brand_profile_id,
            "prompt_template_version_id": body.prompt_template_version_id,
            "ai_provider_profile_id": body.ai_provider_profile_id,
            "access_mode": body.access_mode,
            "research_mode": body.research_mode,
            "content_filters": body.content_filters.model_dump(mode="json"),
            "media_policy": body.media_policy,
            "attribution_policy": body.attribution_policy,
            "custom_footer": body.custom_footer,
            "publishing_policy": body.publishing_policy,
            "poll_interval_seconds": body.poll_interval_seconds,
            "quiet_hours": body.quiet_hours.model_dump(mode="json") if body.quiet_hours else {},
            "retry_policy": body.retry_policy.model_dump(mode="json"),
        }
        if all(getattr(existing, key) == value for key, value in expected.items()):
            return existing
        raise HTTPException(409, "Telegram automation route already exists with different configuration")
    route = AutomationRoute(
        name=body.name,
        source_id=body.source_id,
        destination_id=body.destination_id,
        brand_profile_id=body.brand_profile_id,
        prompt_template_version_id=body.prompt_template_version_id,
        ai_provider_profile_id=body.ai_provider_profile_id,
        access_mode=body.access_mode,
        research_mode=body.research_mode,
        content_filters=body.content_filters.model_dump(mode="json"),
        media_policy=body.media_policy,
        attribution_policy=body.attribution_policy,
        custom_footer=body.custom_footer,
        publishing_policy=body.publishing_policy,
        poll_interval_seconds=body.poll_interval_seconds,
        quiet_hours=body.quiet_hours.model_dump(mode="json") if body.quiet_hours else {},
        retry_policy=body.retry_policy.model_dump(mode="json"),
        cursor_state={"status": "not_initialized"},
        enabled=False,
        paused_at=None,
        backfill_limit=None,
        backfill_since=None,
    )
    session.add(route)
    await session.flush()
    await session.commit()
    return route


@router.get("/{route_id}", response_model=TelegramRouteOut)
async def get_route(route_id: UUID, session: AsyncSession = SessionDependency):
    return await _route_or_404(session, route_id)


@router.patch("/{route_id}/research-policy", response_model=TelegramRouteOut)
async def update_research_policy(
    route_id: UUID,
    body: TelegramResearchPolicyInput,
    session: AsyncSession = SessionDependency,
    secrets: SecretResolverDependency = None,
    executable_resolver: ExecutableResolverDependency = shutil.which,
):
    route = await session.scalar(select(AutomationRoute).where(AutomationRoute.id == route_id).with_for_update())
    if route is None:
        raise HTTPException(404, "Telegram automation route not found")
    if body.research_provider_profile_id is not None:
        profile = await session.get(AIProviderProfile, body.research_provider_profile_id)
        if profile is None or not _provider_supports_research(profile, secrets, executable_resolver):
            raise HTTPException(422, "Research provider profile is not configured")
    filters = dict(route.content_filters or {})
    filters.pop("research_backend", None)
    if body.research_provider_profile_id is None:
        filters.pop("research_provider_profile_id", None)
    else:
        filters["research_provider_profile_id"] = str(body.research_provider_profile_id)
    route.research_mode = body.research_mode
    route.content_filters = filters
    await session.commit()
    return route


@router.post("/{route_id}/activate", response_model=TelegramRouteAcceptedOut, status_code=202)
async def activate_route(
    route_id: UUID,
    session: AsyncSession = SessionDependency,
    jobs: JobRepositoryDependency = None,
):
    route = await session.scalar(select(AutomationRoute).where(AutomationRoute.id == route_id).with_for_update())
    if route is None:
        raise HTTPException(404, "Telegram automation route not found")
    state = route.cursor_state or {}
    replaying_initialization = (
        route.enabled and state.get("status") == "initializing" and bool(state.get("activation_requested_at"))
    )
    if replaying_initialization:
        requested_at = str(state["activation_requested_at"])
    else:
        requested_at = datetime.now(UTC).isoformat()
        route.enabled = True
        route.paused_at = None
        route.backfill_limit = None
        route.backfill_since = None
        route.cursor_state = {
            "status": "initializing",
            "activation_requested_at": requested_at,
            "activation_message_id": None,
            "last_message_id": None,
            "recent_fingerprints": {},
        }
    result = await jobs.enqueue_job(
        job_type="telegram.route.initialize",
        payload={"route_id": str(route.id), "activation_requested_at": requested_at},
        idempotency_key=f"telegram-route-initialize:{route.id}:{requested_at}",
        origin=JobOrigin.AUTOMATION,
    )
    await session.commit()
    return TelegramRouteAcceptedOut(route=route, job=_job_out(result))


@router.post("/{route_id}/pause", response_model=TelegramRouteOut)
async def pause_route(route_id: UUID, session: AsyncSession = SessionDependency):
    route = await _route_or_404(session, route_id)
    route.paused_at = datetime.now(UTC)
    await session.commit()
    return route


@router.post("/{route_id}/resume", response_model=TelegramRouteOut)
async def resume_route(route_id: UUID, session: AsyncSession = SessionDependency):
    route = await _route_or_404(session, route_id)
    route.paused_at = None
    await session.commit()
    return route


@router.post("/{route_id}/dry-run", response_model=TelegramRouteAcceptedOut, status_code=202)
async def dry_run_route(
    route_id: UUID,
    body: TelegramRouteDryRunIn,
    session: AsyncSession = SessionDependency,
    jobs: JobRepositoryDependency = None,
):
    route = await _route_or_404(session, route_id)
    payload = {
        "route_id": str(route.id),
        "source_message_id": body.source_message_id,
        "force_review": True,
    }
    request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = await jobs.enqueue_job(
        job_type="telegram.route.dry_run",
        payload=payload,
        idempotency_key=f"telegram-route-dry-run:{route.id}:{request_hash}",
        origin=JobOrigin.MANUAL,
    )
    await session.commit()
    return TelegramRouteAcceptedOut(route=route, job=_job_out(result))


@router.post("/{route_id}/backfill", response_model=TelegramRouteAcceptedOut, status_code=202)
async def backfill_route(
    route_id: UUID,
    body: TelegramRouteBackfillIn,
    session: AsyncSession = SessionDependency,
    jobs: JobRepositoryDependency = None,
):
    route = await _route_or_404(session, route_id)
    bounds = body.model_dump(mode="json", exclude_none=True)
    bounds_hash = hashlib.sha256(json.dumps(bounds, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = await jobs.enqueue_job(
        job_type="telegram.route.backfill",
        payload={"route_id": str(route.id), **bounds},
        idempotency_key=f"telegram-route-backfill:{route.id}:{bounds_hash}",
        origin=JobOrigin.MANUAL,
    )
    await session.commit()
    return TelegramRouteAcceptedOut(route=route, job=_job_out(result))


@router.get("/{route_id}/dispatches")
async def list_route_dispatches(route_id: UUID, session: AsyncSession = SessionDependency):
    await _route_or_404(session, route_id)
    rows = list(
        await session.scalars(
            select(AutomationDispatch)
            .where(AutomationDispatch.route_id == route_id)
            .order_by(AutomationDispatch.created_at.desc())
        )
    )
    output = []
    for row in rows:
        story_revision = await session.get(StoryRevision, row.story_revision_id)
        output.append(
            {
                "id": row.id,
                "route_id": row.route_id,
                "source_item_id": row.source_item_id,
                "story_id": story_revision.story_id if story_revision is not None else None,
                "story_revision_id": row.story_revision_id,
                "source_key": row.source_key,
                "source_fingerprint": row.source_fingerprint,
                "source_message_ids": row.source_message_ids,
                "dispatch_kind": row.dispatch_kind,
                "status": row.status,
                "generation_run_id": row.generation_run_id,
                "variant_revision_id": row.variant_revision_id,
                "publish_job_id": row.publish_job_id,
                "error_code": redact_string(row.error_code) if row.error_code is not None else None,
                "error_message": redact_string(row.error_message) if row.error_message is not None else None,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
    return output
