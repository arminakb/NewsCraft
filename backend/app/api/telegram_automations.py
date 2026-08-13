from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.capabilities import CapabilityStatusDependency
from app.api.dependencies import InjectedSession, SessionDependency
from app.api.telegram_destinations import (
    get_job_repository,
)
from app.api.telegram_schemas import (
    TelegramAutomationOptionsOut,
    TelegramPromptPolicyInput,
    TelegramResearchPolicyInput,
    TelegramRouteAcceptedOut,
    TelegramRouteBackfillIn,
    TelegramRouteCreate,
    TelegramRouteDryRunIn,
    TelegramRouteOut,
)
from app.automations.models import AutomationDispatch, AutomationRoute, TelegramSourceConfig
from app.core.redaction import redact_string
from app.db.models import Source
from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplate, PromptTemplateVersion
from app.jobs.credential_capabilities import CapabilityStatusService, provider_shape_capabilities
from app.jobs.errors import JobCapabilityUnavailable
from app.jobs.repository import EnqueueJobResult, JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin
from app.publishing.models import Destination
from app.stories.models import StoryRevision

router = APIRouter(prefix="/telegram/automations", tags=["telegram"])
#: Dispatch history is append-only and unbounded; the listing answers
#: newest-first, so this ceiling trims only the tail of an audit log.
DISPATCH_CEILING = 200
JobRepositoryDependency = Annotated[JobRepository, Depends(get_job_repository)]


def _provider_is_configured(
    profile: AIProviderProfile,
) -> bool:
    capabilities, _codes = provider_shape_capabilities(profile)
    return capabilities["generation"]


def _provider_supports_research(
    profile: AIProviderProfile,
) -> bool:
    capabilities, _codes = provider_shape_capabilities(profile)
    return capabilities["research"]


_ROUTE_RESPONSE_ATTRIBUTES = tuple(TelegramRouteOut.model_fields)


def _job_out(result: EnqueueJobResult) -> JobAcceptedOut:
    return JobAcceptedOut.model_validate(
        {
            "job_id": result.job.id,
            "status": result.job.status,
            "deduplicated": not result.created,
        }
    )


async def _materialize_route_out(
    session: AsyncSession,
    route: AutomationRoute,
) -> TelegramRouteOut:
    """Copy every public route scalar while async ORM access is still safe."""
    await session.flush()
    await session.refresh(route, attribute_names=list(_ROUTE_RESPONSE_ATTRIBUTES))
    return TelegramRouteOut.model_validate(route)


async def _route_or_404(session: AsyncSession, route_id: UUID) -> AutomationRoute:
    route = await session.get(AutomationRoute, route_id)
    if route is None:
        raise HTTPException(404, "Telegram automation route not found")
    return route


async def _telegram_prompt_or_422(
    session: AsyncSession,
    version_id: UUID,
    *,
    require_active: bool,
) -> PromptTemplateVersion:
    version = await session.get(PromptTemplateVersion, version_id)
    template = await session.get(PromptTemplate, version.prompt_template_id) if version is not None else None
    if (
        version is None
        or template is None
        or template.purpose_key != "telegram_rewrite"
        or (require_active and not version.is_active)
    ):
        state = "active " if require_active else ""
        raise HTTPException(
            422,
            {
                "code": "telegram_prompt_policy_invalid",
                "message": f"Route requires an {state}telegram_rewrite prompt version",
            },
        )
    return version


async def _active_telegram_prompt(session: AsyncSession) -> PromptTemplateVersion:
    templates = list(
        await session.scalars(select(PromptTemplate).where(PromptTemplate.purpose_key == "telegram_rewrite"))
    )
    template_ids = {item.id for item in templates}
    versions = list(
        await session.scalars(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.prompt_template_id.in_(template_ids),
                PromptTemplateVersion.is_active.is_(True),
            )
        )
    )
    active = [item for item in versions if item.prompt_template_id in template_ids and item.is_active]
    if len(active) != 1:
        raise HTTPException(
            422,
            {
                "code": "telegram_active_prompt_invalid",
                "message": "Exactly one active telegram_rewrite prompt is required",
            },
        )
    return active[0]


async def _require_route_capabilities(
    route: AutomationRoute,
    capability_status: CapabilityStatusService,
    *,
    job_type: str,
) -> None:
    await capability_status.require_available(
        "source",
        route.source_id,
        "source",
        job_type=job_type,
    )
    await capability_status.require_available(
        "provider",
        route.ai_provider_profile_id,
        "generation",
        job_type=job_type,
    )
    research_profile_id = (route.content_filters or {}).get("research_provider_profile_id")
    if route.research_mode != "off" and research_profile_id is not None:
        try:
            research_id = UUID(str(research_profile_id))
        except ValueError:
            raise JobCapabilityUnavailable(
                code="job_capability_unknown",
                job_type=job_type,
                retry_after_seconds=capability_status.config.capability_retry_after_seconds,
            ) from None
        await capability_status.require_available(
            "provider",
            research_id,
            "research",
            job_type=job_type,
        )
    if route.publishing_policy == "auto_publish":
        await capability_status.require_available(
            "destination",
            route.destination_id,
            "publishing",
            job_type=job_type,
        )


@router.get("", response_model=list[TelegramRouteOut])
async def list_routes(session: AsyncSession = SessionDependency):
    return list(await session.scalars(select(AutomationRoute).order_by(AutomationRoute.name)))


@router.get("/options", response_model=TelegramAutomationOptionsOut)
async def automation_options(
    session: InjectedSession,
    capability_status: CapabilityStatusDependency,
):
    sources = list(await session.scalars(select(Source).where(Source.platform == "telegram_public")))
    source_configs = list(await session.scalars(select(TelegramSourceConfig)))
    configs_by_source = {item.source_id: item for item in source_configs}
    destinations = list(
        await session.scalars(
            select(Destination).where(
                Destination.platform == "telegram",
                Destination.enabled.is_(True),
                Destination.health_status == "healthy",
                Destination.administrator_status == "administrator",
            )
        )
    )
    brands = list(
        await session.scalars(select(BrandProfile).order_by(BrandProfile.is_default.desc(), BrandProfile.name))
    )
    templates = list(
        await session.scalars(select(PromptTemplate).where(PromptTemplate.purpose_key == "telegram_rewrite"))
    )
    template_ids = {item.id for item in templates}
    versions = list(await session.scalars(select(PromptTemplateVersion).order_by(PromptTemplateVersion.version.desc())))
    profiles = list(await session.scalars(select(AIProviderProfile).where(AIProviderProfile.enabled.is_(True))))
    safe_profiles = []
    for profile in profiles:
        shaped, _codes = provider_shape_capabilities(profile)
        if shaped["generation"]:
            capability_states = {
                "generation": await capability_status.get("provider", profile.id, "generation"),
                "research": await capability_status.get("provider", profile.id, "research"),
            }
            capabilities = {name: shaped[name] and state.available for name, state in capability_states.items()}
            safe_profiles.append(
                {
                    "id": profile.id,
                    "name": profile.name,
                    "provider_type": profile.provider_type,
                    "default_model": profile.default_model,
                    "configured": capabilities["generation"],
                    "capabilities": capabilities,
                    "capability_states": capability_states,
                }
            )
    safe_sources = []
    for source in sources:
        if source.id not in configs_by_source:
            continue
        state = await capability_status.get("source", source.id, "source")
        safe_sources.append(
            {
                "id": source.id,
                "name": source.name,
                "access_mode": configs_by_source[source.id].access_mode,
                "capability_state": state,
            }
        )
    safe_destinations = []
    for destination in destinations:
        state = await capability_status.get("destination", destination.id, "publishing")
        safe_destinations.append(
            {
                "id": destination.id,
                "name": destination.name,
                "health_status": destination.health_status,
                "capability_state": state,
            }
        )
    return TelegramAutomationOptionsOut(
        sources=safe_sources,
        destinations=safe_destinations,
        brand_profiles=[{"id": item.id, "name": item.name} for item in brands],
        prompt_template_versions=[
            {
                "id": item.id,
                "version": item.version,
                "is_active": item.is_active,
                "checksum_sha256": item.checksum_sha256,
            }
            for item in versions
            if item.prompt_template_id in template_ids
        ],
        ai_provider_profiles=safe_profiles,
    )


@router.post("", response_model=TelegramRouteOut, status_code=201)
async def create_route(
    body: TelegramRouteCreate,
    session: AsyncSession = SessionDependency,
):
    source = await session.scalar(select(Source).where(Source.id == body.source_id).with_for_update())
    source_config = await session.get(TelegramSourceConfig, body.source_id)
    destination = await session.get(Destination, body.destination_id)
    brand = await session.get(BrandProfile, body.brand_profile_id)
    prompt_version = await _telegram_prompt_or_422(
        session,
        body.prompt_template_version_id,
        require_active=body.prompt_policy == "follow_active",
    )
    profile = await session.get(AIProviderProfile, body.ai_provider_profile_id)
    if (
        source is None
        or source_config is None
        or destination is None
        or brand is None
        or prompt_version is None
        or profile is None
    ):
        raise HTTPException(422, "Referenced Telegram route configuration is missing")
    if source.platform != "telegram_public" or source_config.access_mode != body.access_mode:
        raise HTTPException(422, "Route source and access mode do not match")
    if (
        destination.platform != "telegram"
        or not destination.enabled
        or destination.health_status != "healthy"
        or destination.administrator_status != "administrator"
    ):
        raise HTTPException(422, "Telegram destination is not ready")
    if not _provider_is_configured(profile):
        raise HTTPException(422, "AI provider profile configuration is invalid")
    if body.content_filters.model is None and profile.default_model is None:
        raise HTTPException(422, "Route requires a model override or provider default model")
    research_profile_id = body.content_filters.research_provider_profile_id
    if research_profile_id is not None:
        research_profile = await session.get(AIProviderProfile, research_profile_id)
        if research_profile is None or not _provider_supports_research(research_profile):
            raise HTTPException(422, "Research provider profile configuration is invalid")
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
            "prompt_policy": body.prompt_policy,
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
            response = await _materialize_route_out(session, existing)
            await session.commit()
            return response
        raise HTTPException(409, "Telegram automation route already exists with different configuration")
    route = AutomationRoute(
        name=body.name,
        source_id=body.source_id,
        destination_id=body.destination_id,
        brand_profile_id=body.brand_profile_id,
        prompt_template_version_id=body.prompt_template_version_id,
        prompt_policy=body.prompt_policy,
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
    response = await _materialize_route_out(session, route)
    await session.commit()
    return response


@router.patch("/{route_id}/prompt-policy", response_model=TelegramRouteOut)
async def update_prompt_policy(
    route_id: UUID,
    body: TelegramPromptPolicyInput,
    session: AsyncSession = SessionDependency,
):
    route = await session.scalar(select(AutomationRoute).where(AutomationRoute.id == route_id).with_for_update())
    if route is None:
        raise HTTPException(404, "Telegram automation route not found")
    if body.prompt_policy == "follow_active":
        version = await _active_telegram_prompt(session)
    else:
        if body.prompt_template_version_id is None:  # pragma: no cover - request model invariant
            raise HTTPException(422, "Pinned prompt policy requires a prompt version")
        version = await _telegram_prompt_or_422(
            session,
            body.prompt_template_version_id,
            require_active=False,
        )
    route.prompt_policy = body.prompt_policy
    route.prompt_template_version_id = version.id
    response = await _materialize_route_out(session, route)
    await session.commit()
    return response


@router.get("/{route_id}", response_model=TelegramRouteOut)
async def get_route(route_id: UUID, session: AsyncSession = SessionDependency):
    return await _route_or_404(session, route_id)


@router.patch("/{route_id}/research-policy", response_model=TelegramRouteOut)
async def update_research_policy(
    route_id: UUID,
    body: TelegramResearchPolicyInput,
    session: AsyncSession = SessionDependency,
):
    route = await session.scalar(select(AutomationRoute).where(AutomationRoute.id == route_id).with_for_update())
    if route is None:
        raise HTTPException(404, "Telegram automation route not found")
    if body.research_provider_profile_id is not None:
        profile = await session.get(AIProviderProfile, body.research_provider_profile_id)
        if profile is None or not _provider_supports_research(profile):
            raise HTTPException(422, "Research provider profile configuration is invalid")
    filters = dict(route.content_filters or {})
    filters.pop("research_backend", None)
    if body.research_provider_profile_id is None:
        filters.pop("research_provider_profile_id", None)
    else:
        filters["research_provider_profile_id"] = str(body.research_provider_profile_id)
    route.research_mode = body.research_mode
    route.content_filters = filters
    response = await _materialize_route_out(session, route)
    await session.commit()
    return response


@router.post("/{route_id}/activate", response_model=TelegramRouteAcceptedOut, status_code=202)
async def activate_route(
    route_id: UUID,
    session: InjectedSession,
    jobs: JobRepositoryDependency,
    capability_status: CapabilityStatusDependency,
):
    route = await session.scalar(select(AutomationRoute).where(AutomationRoute.id == route_id).with_for_update())
    if route is None:
        raise HTTPException(404, "Telegram automation route not found")
    await _require_route_capabilities(
        route,
        capability_status,
        job_type="telegram.route.initialize",
    )
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
    response = TelegramRouteAcceptedOut(
        route=await _materialize_route_out(session, route),
        job=_job_out(result),
    )
    await session.commit()
    return response


@router.post("/{route_id}/pause", response_model=TelegramRouteOut)
async def pause_route(route_id: UUID, session: AsyncSession = SessionDependency):
    route = await _route_or_404(session, route_id)
    route.paused_at = datetime.now(UTC)
    response = await _materialize_route_out(session, route)
    await session.commit()
    return response


@router.post("/{route_id}/resume", response_model=TelegramRouteOut)
async def resume_route(
    route_id: UUID,
    session: InjectedSession,
    capability_status: CapabilityStatusDependency,
):
    route = await _route_or_404(session, route_id)
    await _require_route_capabilities(
        route,
        capability_status,
        job_type="telegram.route.poll",
    )
    route.paused_at = None
    response = await _materialize_route_out(session, route)
    await session.commit()
    return response


@router.post("/{route_id}/dry-run", response_model=TelegramRouteAcceptedOut, status_code=202)
async def dry_run_route(
    route_id: UUID,
    body: TelegramRouteDryRunIn,
    session: InjectedSession,
    jobs: JobRepositoryDependency,
    capability_status: CapabilityStatusDependency,
):
    route = await _route_or_404(session, route_id)
    await _require_route_capabilities(
        route,
        capability_status,
        job_type="telegram.route.dry_run",
    )
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
    response = TelegramRouteAcceptedOut(
        route=await _materialize_route_out(session, route),
        job=_job_out(result),
    )
    await session.commit()
    return response


@router.post("/{route_id}/backfill", response_model=TelegramRouteAcceptedOut, status_code=202)
async def backfill_route(
    route_id: UUID,
    body: TelegramRouteBackfillIn,
    session: InjectedSession,
    jobs: JobRepositoryDependency,
    capability_status: CapabilityStatusDependency,
):
    route = await _route_or_404(session, route_id)
    await _require_route_capabilities(
        route,
        capability_status,
        job_type="telegram.route.backfill",
    )
    bounds = body.model_dump(mode="json", exclude_none=True)
    bounds_hash = hashlib.sha256(json.dumps(bounds, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = await jobs.enqueue_job(
        job_type="telegram.route.backfill",
        payload={"route_id": str(route.id), **bounds},
        idempotency_key=f"telegram-route-backfill:{route.id}:{bounds_hash}",
        origin=JobOrigin.MANUAL,
    )
    response = TelegramRouteAcceptedOut(
        route=await _materialize_route_out(session, route),
        job=_job_out(result),
    )
    await session.commit()
    return response


@router.get("/{route_id}/dispatches")
async def list_route_dispatches(route_id: UUID, session: AsyncSession = SessionDependency):
    await _route_or_404(session, route_id)
    rows = list(
        await session.scalars(
            select(AutomationDispatch)
            .where(AutomationDispatch.route_id == route_id)
            .order_by(AutomationDispatch.created_at.desc())
            .limit(DISPATCH_CEILING)
        )
    )
    # One lookup for the whole page: a dispatch history grows without bound, so
    # resolving each row's story revision on its own turns a listing into as
    # many round trips as there are dispatches.
    revision_ids = {row.story_revision_id for row in rows if row.story_revision_id is not None}
    story_revisions = (
        {
            revision.id: revision
            for revision in await session.scalars(
                select(StoryRevision).where(StoryRevision.id.in_(revision_ids))
            )
        }
        if revision_ids
        else {}
    )
    output = []
    for row in rows:
        story_revision = story_revisions.get(row.story_revision_id)
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
