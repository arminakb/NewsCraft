from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.models import Automation, AutomationVersion
from app.automations.definitions.schemas import (
    AutomationResourceOut,
    ResourceKind,
    ResourceRequest,
    WorkflowGraphV1,
)
from app.automations.models import TelegramSourceConfig
from app.db.models import ArticleCollection, Source
from app.generation.models import AIProviderProfile, BrandProfile, PromptTemplateVersion
from app.jobs.credential_capabilities import (
    CapabilityStatusService,
    ResourceCapability,
    provider_shape_capabilities,
)
from app.publishing.models import Destination

_MANAGE_HREF: dict[ResourceKind, str] = {
    "source": "/sources",
    "provider": "/settings?section=llm-providers",
    "prompt_version": "/settings?section=prompts",
    "editorial_profile": "/settings",
    "destination": "/settings?section=telegram",
    "collection": "/feed",
}

_RESOURCE_FIELDS: dict[str, dict[str, ResourceKind]] = {
    "collection_article_added": {"collection_id": "collection"},
    "new_source_item": {"source_ids": "source"},
    "select_content": {"source_ids": "source"},
    "research": {"provider_profile_id": "provider"},
    "generate_content_pack": {
        "editorial_profile_id": "editorial_profile",
        "provider_profile_id": "provider",
    },
    "telegram_publish": {"destination_id": "destination"},
}


def graph_resource_requests(graph: WorkflowGraphV1) -> set[tuple[ResourceKind, UUID]]:
    found: set[tuple[ResourceKind, UUID]] = set()
    for node in graph.nodes:
        for field, kind in _RESOURCE_FIELDS.get(node.type, {}).items():
            raw = node.config.get(field)
            if raw is None:
                continue
            values = raw if isinstance(raw, list) else [raw]
            for value in values:
                try:
                    found.add((kind, UUID(str(value))))
                except (TypeError, ValueError):
                    continue
        if node.type == "generate_content_pack":
            prompt_ids = node.config.get("prompt_version_ids", [])
            for raw in prompt_ids if isinstance(prompt_ids, list) else []:
                try:
                    found.add(("prompt_version", UUID(str(raw))))
                except (TypeError, ValueError):
                    continue
    return found


def graph_resource_locations(
    graph: WorkflowGraphV1,
) -> dict[tuple[ResourceKind, UUID], list[tuple[str, str]]]:
    locations: dict[tuple[ResourceKind, UUID], list[tuple[str, str]]] = defaultdict(list)
    for node in graph.nodes:
        for field, kind in _RESOURCE_FIELDS.get(node.type, {}).items():
            raw = node.config.get(field)
            values = raw if isinstance(raw, list) else [raw]
            for value in values:
                try:
                    resource_id = UUID(str(value))
                except (TypeError, ValueError):
                    continue
                locations[(kind, resource_id)].append((node.id, f"config.{field}"))
        if node.type == "generate_content_pack":
            raw_prompt_ids = node.config.get("prompt_version_ids", [])
            for value in raw_prompt_ids if isinstance(raw_prompt_ids, list) else []:
                try:
                    resource_id = UUID(str(value))
                except (TypeError, ValueError):
                    continue
                locations[("prompt_version", resource_id)].append((node.id, "config.prompt_version_ids"))
    return locations


async def _automation_references(
    session: AsyncSession,
    automation_id: UUID | None,
) -> tuple[set[tuple[ResourceKind, UUID]], set[tuple[ResourceKind, UUID]], set[UUID]]:
    if automation_id is None:
        return set(), set(), set()
    automation = await session.get(Automation, automation_id)
    if automation is None:
        return set(), set(), set()
    active: set[tuple[ResourceKind, UUID]] = set()
    current: set[tuple[ResourceKind, UUID]] = set()
    new_source_trigger_ids: set[UUID] = set()
    for version_id in {automation.active_version_id, automation.draft_version_id} - {None}:
        version = await session.get(AutomationVersion, version_id)
        if version is None:
            continue
        graph = WorkflowGraphV1.model_validate(version.graph)
        references = graph_resource_requests(graph)
        current |= references
        for node in graph.nodes:
            if node.type != "new_source_item":
                continue
            values = node.config.get("source_ids")
            for value in values if isinstance(values, list) else []:
                try:
                    new_source_trigger_ids.add(UUID(str(value)))
                except (TypeError, ValueError):
                    continue
        if version_id == automation.active_version_id:
            active |= references
    return current, active, new_source_trigger_ids


def _missing(kind: ResourceKind, resource_id: UUID, *, active: bool) -> AutomationResourceOut:
    return AutomationResourceOut(
        id=resource_id,
        kind=kind,
        display_name=f"Unavailable {kind.replace('_', ' ')}",
        state="unavailable",
        reason_code="resource_missing",
        capabilities=[],
        referenced_by_active_version=active,
        manage_href=_MANAGE_HREF[kind],
    )


async def summarize_resources(
    session: AsyncSession,
    requests: Iterable[ResourceRequest],
    *,
    automation_id: UUID | None,
    capability_status: CapabilityStatusService | None = None,
) -> list[AutomationResourceOut]:
    unique = {(item.kind, item.id) for item in requests}
    current_refs, active_refs, new_source_trigger_ids = await _automation_references(session, automation_id)
    unique |= current_refs
    grouped: dict[ResourceKind, set[UUID]] = defaultdict(set)
    for kind, resource_id in unique:
        grouped[kind].add(resource_id)

    sources = {
        item.id: item
        for item in await session.scalars(select(Source).where(Source.id.in_(grouped["source"])))
    }
    collections = {
        item.id: item
        for item in await session.scalars(
            select(ArticleCollection).where(ArticleCollection.id.in_(grouped["collection"]))
        )
    }
    source_configs = {
        item.source_id: item
        for item in await session.scalars(
            select(TelegramSourceConfig).where(TelegramSourceConfig.source_id.in_(grouped["source"]))
        )
    }
    providers = {
        item.id: item
        for item in await session.scalars(
            select(AIProviderProfile).where(AIProviderProfile.id.in_(grouped["provider"]))
        )
    }
    prompts = {
        item.id: item
        for item in await session.scalars(
            select(PromptTemplateVersion).where(PromptTemplateVersion.id.in_(grouped["prompt_version"]))
        )
    }
    profiles = {
        item.id: item
        for item in await session.scalars(
            select(BrandProfile).where(BrandProfile.id.in_(grouped["editorial_profile"]))
        )
    }
    destinations = {
        item.id: item
        for item in await session.scalars(
            select(Destination).where(Destination.id.in_(grouped["destination"]))
        )
    }

    output: list[AutomationResourceOut] = []
    for kind, resource_id in sorted(unique, key=lambda item: (item[0], str(item[1]))):
        active = (kind, resource_id) in active_refs
        if kind == "collection":
            collection = collections.get(resource_id)
            if collection is None:
                output.append(_missing(kind, resource_id, active=active))
                continue
            output.append(
                AutomationResourceOut(
                    id=resource_id,
                    kind=kind,
                    display_name=collection.name,
                    state="ready",
                    reason_code=None,
                    capabilities=["collection_article_added"],
                    referenced_by_active_version=active,
                    manage_href=_MANAGE_HREF[kind],
                )
            )
        elif kind == "source":
            source = sources.get(resource_id)
            if source is None or source.deleted_at is not None:
                output.append(_missing(kind, resource_id, active=active))
                continue
            state = "ready"
            reason = None
            if not source.active:
                state, reason = "disabled", "disabled"
            elif source.platform == "telegram_public" and resource_id in new_source_trigger_ids:
                # The canonical ingestion worker reads Source.telegram_username directly.
                # TelegramSourceConfig belongs to the legacy Telegram route trigger.
                pass
            elif source.platform == "telegram_public" and resource_id not in source_configs:
                state, reason = "not_configured", "source_configuration_missing"
            elif (
                capability_status is not None
                and source.platform == "telegram_public"
                and resource_id not in new_source_trigger_ids
            ):
                capability = await capability_status.get("source", resource_id, "source")
                if capability.status != "available":
                    state = "stale" if capability.status in {"stale", "unknown"} else "not_configured"
                    reason = capability.failure_code
            output.append(
                AutomationResourceOut(
                    id=resource_id,
                    kind=kind,
                    display_name=source.name,
                    state=state,  # type: ignore[arg-type]
                    reason_code=reason,
                    capabilities=["source"] if source.platform == "telegram_public" else ["select_content"],
                    referenced_by_active_version=active,
                    manage_href=_MANAGE_HREF[kind],
                )
            )
        elif kind == "provider":
            provider = providers.get(resource_id)
            if provider is None:
                output.append(_missing(kind, resource_id, active=active))
                continue
            shaped, codes = provider_shape_capabilities(provider)
            capabilities: list[ResourceCapability] = []
            if shaped["generation"]:
                capabilities.append("generation")
            if shaped["research"]:
                capabilities.append("research")
            state = "ready" if capabilities else ("disabled" if not provider.enabled else "not_configured")
            reason = None if capabilities else (codes[0] if codes else "invalid_configuration")
            if capability_status is not None and capabilities:
                observations = [await capability_status.get("provider", resource_id, item) for item in capabilities]
                if not any(item.available for item in observations):
                    stale = any(item.status in {"stale", "unknown"} for item in observations)
                    state = "stale" if stale else "not_configured"
                    reason = observations[0].failure_code
            output.append(
                AutomationResourceOut(
                    id=resource_id,
                    kind=kind,
                    display_name=provider.name,
                    state=state,  # type: ignore[arg-type]
                    reason_code=reason,
                    capabilities=[str(item) for item in capabilities],
                    referenced_by_active_version=active,
                    manage_href=_MANAGE_HREF[kind],
                )
            )
        elif kind == "prompt_version":
            prompt = prompts.get(resource_id)
            if prompt is None:
                output.append(_missing(kind, resource_id, active=active))
                continue
            output.append(
                AutomationResourceOut(
                    id=resource_id,
                    kind=kind,
                    display_name=f"Prompt version {prompt.version}",
                    state="ready" if prompt.is_active else "stale",
                    reason_code=None if prompt.is_active else "prompt_version_inactive",
                    capabilities=["generation"],
                    referenced_by_active_version=active,
                    manage_href=_MANAGE_HREF[kind],
                )
            )
        elif kind == "editorial_profile":
            profile = profiles.get(resource_id)
            if profile is None:
                output.append(_missing(kind, resource_id, active=active))
                continue
            output.append(
                AutomationResourceOut(
                    id=resource_id,
                    kind=kind,
                    display_name=profile.name,
                    state="ready",
                    reason_code=None,
                    capabilities=["editorial_profile"],
                    referenced_by_active_version=active,
                    manage_href=_MANAGE_HREF[kind],
                )
            )
        else:
            destination = destinations.get(resource_id)
            if destination is None:
                output.append(_missing(kind, resource_id, active=active))
                continue
            state = "ready"
            reason = None
            if not destination.enabled:
                state, reason = "disabled", "disabled"
            elif destination.health_status != "healthy" or destination.administrator_status != "administrator":
                state, reason = "stale", "destination_not_ready"
            elif capability_status is not None:
                capability = await capability_status.get("destination", resource_id, "publishing")
                if not capability.available:
                    state = "stale" if capability.status in {"stale", "unknown"} else "not_configured"
                    reason = capability.failure_code
            output.append(
                AutomationResourceOut(
                    id=resource_id,
                    kind=kind,
                    display_name=destination.name,
                    state=state,  # type: ignore[arg-type]
                    reason_code=reason,
                    capabilities=["telegram_publish"] if destination.platform == "telegram" else [],
                    referenced_by_active_version=active,
                    manage_href=_MANAGE_HREF[kind],
                )
            )
    return output


async def count_automation_definitions_referencing(session: AsyncSession, resource_id: UUID) -> int:
    """Count immutable definitions containing one exact resource UUID.

    Dependency checks are infrequent and correctness matters more than a broad
    browser-facing index. JSONPath keeps matching scoped to node config values.
    """
    return int(
        await session.scalar(
            text(
                "SELECT count(DISTINCT automation_id) FROM automation_versions "
                "WHERE jsonb_path_exists("
                "graph, '$.nodes[*].config.** ? (@ == $resource_id)', "
                "jsonb_build_object('resource_id', to_jsonb(CAST(:resource_id AS text))))"
            ),
            {"resource_id": str(resource_id)},
        )
        or 0
    )


__all__ = [
    "count_automation_definitions_referencing",
    "graph_resource_locations",
    "graph_resource_requests",
    "summarize_resources",
]
