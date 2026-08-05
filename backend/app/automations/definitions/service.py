from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.compiler import compile_graph, verify_compiled_plan
from app.automations.definitions.errors import AutomationDefinitionError
from app.automations.definitions.execution import materialize_runtime_projection
from app.automations.definitions.models import (
    Automation,
    AutomationRun,
    AutomationRuntimeProjection,
    AutomationTemplate,
    AutomationVersion,
)
from app.automations.definitions.registry import NODE_REGISTRY
from app.automations.definitions.resources import (
    graph_resource_locations,
    graph_resource_requests,
    summarize_resources,
)
from app.automations.definitions.schemas import (
    AutomationCreate,
    AutomationDetailOut,
    AutomationOut,
    AutomationPageOut,
    AutomationPatch,
    AutomationPreviewOut,
    AutomationPreviewStageOut,
    AutomationVersionCreate,
    AutomationVersionOut,
    AutomationVersionPageOut,
    AutomationVersionRestore,
    GraphValidationResult,
    ResourceRequest,
    ValidationFinding,
    WorkflowGraphV1,
    canonical_graph_data,
    graph_sha256,
)
from app.automations.definitions.validation import save_blocking_findings, validate_graph
from app.automations.models import AutomationRoute
from app.generation.models import PromptTemplateVersion
from app.jobs.credential_capabilities import CapabilityStatusService
from app.jobs.models import WorkflowEvent, WorkflowSchedule
from app.security.auth import SecurityPrincipal
from app.stories.models import StoryRevision

_ACTIVE_RUN_STATUSES = ("pending", "queued", "running", "waiting_for_review")
_COMPLETED_RUN_STATUSES = ("succeeded", "failed", "cancelled")

_PREVIEW_CATEGORIES = {
    "trigger": "trigger",
    "select_filter": "content",
    "research": "content",
    "generate": "ai",
    "validate": "validation",
    "review": "review",
}


def _output_platforms(node_type: str, config: object) -> list[str]:
    if node_type == "telegram_publish":
        return ["telegram"]
    if node_type == "save_drafts":
        return ["draft"]
    if node_type == "manual_package" and isinstance(config, dict):
        raw = config.get("platforms")
        if isinstance(raw, list):
            platforms = [item for item in raw if item in {"instagram", "x", "blog"}]
            if platforms:
                return list(dict.fromkeys(platforms))[:4]
        return ["multi"]
    return ["unknown"]


def _preview_category(node_type: str, family: str, platforms: list[str]) -> str:
    if node_type == "save_drafts" or platforms == ["draft"]:
        return "draft"
    if family == "output":
        return "publish"
    return _PREVIEW_CATEGORIES.get(family, "unknown")


def _automation_preview(
    version: AutomationVersion,
    *,
    version_state: str,
    run_count: int,
    completed_count: int,
    succeeded_count: int,
    last_run_at: datetime | None,
    last_outcome: str | None,
) -> AutomationPreviewOut | None:
    raw_nodes = version.graph.get("nodes")
    raw_outputs = version.graph.get("output_node_ids")
    if not isinstance(raw_nodes, list) or not isinstance(raw_outputs, list):
        return None

    raw_stages = version.compiled_plan.get("stages")
    if not raw_nodes and not isinstance(raw_stages, list):
        valid = version.validation_summary.get("valid")
        return AutomationPreviewOut(
            version=version.version,
            version_state=version_state,
            stages=[],
            output_platforms=["unknown"],
            valid=valid if isinstance(valid, bool) else None,
            run_count=run_count,
            success_rate=round(succeeded_count * 100 / completed_count) if completed_count else None,
            last_run_at=last_run_at,
            last_outcome=last_outcome,
        )
    if not isinstance(raw_stages, list):
        return None

    nodes = {
        item.get("id"): item
        for item in raw_nodes
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    output_ids = {item for item in raw_outputs if isinstance(item, str)}
    findings = version.validation_summary.get("findings")
    attention_ids = {
        item.get("node_id")
        for item in findings
        if isinstance(item, dict) and item.get("severity") == "error" and isinstance(item.get("node_id"), str)
    } if isinstance(findings, list) else set()
    valid = version.validation_summary.get("valid")
    valid_value = valid if isinstance(valid, bool) else None

    stages: list[AutomationPreviewStageOut] = []
    ordered = sorted(
        (item for item in raw_stages if isinstance(item, dict)),
        key=lambda item: item.get("ordinal") if isinstance(item.get("ordinal"), int) else 10_000,
    )
    output_platforms: list[str] = []
    for item in ordered:
        node_id = item.get("node_id")
        node_type = item.get("node_type")
        if not isinstance(node_id, str) or not isinstance(node_type, str):
            continue
        definition = NODE_REGISTRY.get(node_type)
        node = nodes.get(node_id)
        platforms = (
            _output_platforms(node_type, node.get("config") if isinstance(node, dict) else None)
            if node_id in output_ids
            else []
        )
        for platform in platforms:
            if platform not in output_platforms:
                output_platforms.append(platform)
        stages.append(
            AutomationPreviewStageOut(
                node_id=node_id,
                node_type=node_type,
                label=definition.display_name if definition else "Unknown step",
                category=_preview_category(node_type, definition.family if definition else "unknown", platforms),
                platforms=platforms,
                needs_attention=node_id in attention_ids,
            )
        )
    if not stages:
        return None
    return AutomationPreviewOut(
        version=version.version,
        version_state=version_state,
        stages=stages,
        output_platforms=output_platforms[:4] or ["unknown"],
        valid=valid_value,
        run_count=run_count,
        success_rate=round(succeeded_count * 100 / completed_count) if completed_count else None,
        last_run_at=last_run_at,
        last_outcome=last_outcome,
    )


def _error(code: str, status: int, message: str) -> AutomationDefinitionError:
    return AutomationDefinitionError(code, status, message)


def _record_event(
    session: AsyncSession,
    *,
    event_type: str,
    principal: SecurityPrincipal,
    automation_id: UUID,
    data: dict[str, object] | None = None,
) -> None:
    session.add(
        WorkflowEvent(
            event_type=event_type,
            actor=f"{principal.principal_type}:{principal.principal_id}"[:255],
            event_data={"automation_id": str(automation_id), **(data or {})},
        )
    )


async def _automation_for_update(session: AsyncSession, automation_id: UUID) -> Automation:
    automation = await session.scalar(select(Automation).where(Automation.id == automation_id).with_for_update())
    if automation is None:
        raise _error("automation_not_found", 404, "Automation was not found.")
    return automation


def _check_revision(automation: Automation, expected_revision: int) -> None:
    if automation.revision != expected_revision:
        raise _error(
            "automation_version_conflict",
            409,
            "Automation changed since it was loaded. Reload or copy your draft before saving.",
        )


async def _version_by_number(
    session: AsyncSession,
    automation_id: UUID,
    version_number: int,
) -> AutomationVersion:
    version = await session.scalar(
        select(AutomationVersion).where(
            AutomationVersion.automation_id == automation_id,
            AutomationVersion.version == version_number,
        )
    )
    if version is None:
        raise _error("automation_version_not_found", 404, "Automation version was not found.")
    return version


async def _materialize_automation(session: AsyncSession, automation: Automation) -> AutomationOut:
    await session.flush()
    await session.refresh(automation)
    return AutomationOut.model_validate(automation)


async def _materialize_version(session: AsyncSession, version: AutomationVersion) -> AutomationVersionOut:
    await session.flush()
    await session.refresh(version)
    return AutomationVersionOut.model_validate(version)


def _new_version(
    automation: Automation,
    graph: WorkflowGraphV1,
    *,
    version_number: int,
    validation: GraphValidationResult,
    principal: SecurityPrincipal,
    reason: str,
    idempotency_key: str | None,
) -> AutomationVersion:
    compiled = compile_graph(graph) if graph.nodes else None
    return AutomationVersion(
        id=uuid4(),
        automation_id=automation.id,
        version=version_number,
        schema_version=1,
        graph=canonical_graph_data(graph),
        graph_hash=graph_sha256(graph),
        compiler_version=compiled.compiler_version if compiled else None,
        compiled_plan=compiled.model_dump(mode="json") if compiled else {},
        validation_summary={
            **validation.model_dump(mode="json"),
            "scope": "graph_structure",
            "resource_readiness": "not_checked",
        },
        creation_actor_type=principal.principal_type,
        creation_actor_id=principal.principal_id,
        creation_reason=reason,
        idempotency_key=idempotency_key,
    )


def _require_saveable(validation: GraphValidationResult, *, allow_empty: bool = False) -> None:
    if allow_empty:
        return
    blocking = save_blocking_findings(validation)
    if not blocking:
        return
    first = blocking[0]
    raise _error(first.code, 422, first.message)


class AutomationDefinitionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_automations(
        self,
        *,
        limit: int,
        cursor: UUID | None,
        include_archived: bool,
    ) -> AutomationPageOut:
        statement = select(Automation)
        if not include_archived:
            statement = statement.where(Automation.archived_at.is_(None))
        if cursor is not None:
            statement = statement.where(Automation.id > cursor)
        rows = list(await self.session.scalars(statement.order_by(Automation.id).limit(limit + 1)))
        has_more = len(rows) > limit
        rows = rows[:limit]
        if not rows:
            return AutomationPageOut(items=[], next_cursor=None)

        version_selection = {
            row.id: (
                (row.active_version_id, "active")
                if row.lifecycle in {"active", "paused"} and row.active_version_id is not None
                else (row.draft_version_id, "draft")
                if row.draft_version_id is not None
                else (row.active_version_id, "active")
            )
            for row in rows
        }
        version_ids = {version_id for version_id, _state in version_selection.values() if version_id is not None}
        versions = {
            version.id: version
            for version in await self.session.scalars(
                select(AutomationVersion).where(AutomationVersion.id.in_(version_ids))
            )
        } if version_ids else {}

        automation_ids = [row.id for row in rows]
        run_summary_rows = (
            await self.session.execute(
                select(
                    AutomationRun.automation_id,
                    func.count(AutomationRun.id),
                    func.sum(case((AutomationRun.status.in_(_COMPLETED_RUN_STATUSES), 1), else_=0)),
                    func.sum(case((AutomationRun.status == "succeeded", 1), else_=0)),
                )
                .where(AutomationRun.automation_id.in_(automation_ids))
                .group_by(AutomationRun.automation_id)
            )
        ).all()
        run_summaries = {
            automation_id: (int(run_count), int(completed_count or 0), int(succeeded_count or 0))
            for automation_id, run_count, completed_count, succeeded_count in run_summary_rows
        }
        ranked_runs = (
            select(
                AutomationRun.automation_id.label("automation_id"),
                AutomationRun.created_at.label("created_at"),
                AutomationRun.status.label("status"),
                func.row_number().over(
                    partition_by=AutomationRun.automation_id,
                    order_by=(AutomationRun.created_at.desc(), AutomationRun.id.desc()),
                ).label("position"),
            )
            .where(AutomationRun.automation_id.in_(automation_ids))
            .subquery()
        )
        latest_run_rows = (
            await self.session.execute(
                select(ranked_runs.c.automation_id, ranked_runs.c.created_at, ranked_runs.c.status)
                .where(ranked_runs.c.position == 1)
            )
        ).all()
        latest_runs = {
            automation_id: (created_at, status)
            for automation_id, created_at, status in latest_run_rows
        }

        items: list[AutomationOut] = []
        for row in rows:
            version_id, version_state = version_selection[row.id]
            version = versions.get(version_id) if version_id else None
            run_count, completed_count, succeeded_count = run_summaries.get(row.id, (0, 0, 0))
            last_run_at, last_outcome = latest_runs.get(row.id, (None, None))
            preview = _automation_preview(
                version,
                version_state=version_state,
                run_count=run_count,
                completed_count=completed_count,
                succeeded_count=succeeded_count,
                last_run_at=last_run_at,
                last_outcome=last_outcome,
            ) if version else None
            items.append(AutomationOut.model_validate(row).model_copy(update={"preview": preview}))
        return AutomationPageOut(
            items=items,
            next_cursor=str(rows[-1].id) if has_more and rows else None,
        )

    async def get_automation(self, automation_id: UUID) -> AutomationDetailOut:
        automation = await self.session.get(Automation, automation_id)
        if automation is None:
            raise _error("automation_not_found", 404, "Automation was not found.")
        await self.session.flush()
        await self.session.refresh(automation)
        draft = (
            await self.session.get(AutomationVersion, automation.draft_version_id)
            if automation.draft_version_id
            else None
        )
        active = (
            await self.session.get(AutomationVersion, automation.active_version_id)
            if automation.active_version_id
            else None
        )
        projection = await self.session.get(AutomationRuntimeProjection, automation_id)
        return AutomationDetailOut(
            **AutomationOut.model_validate(automation).model_dump(),
            draft_version=AutomationVersionOut.model_validate(draft) if draft else None,
            active_version=AutomationVersionOut.model_validate(active) if active else None,
            legacy_route_id=projection.route_id if projection else None,
        )

    async def create_automation(
        self,
        body: AutomationCreate,
        *,
        principal: SecurityPrincipal,
        idempotency_key: str,
    ) -> AutomationDetailOut:
        existing = await self.session.scalar(select(Automation).where(Automation.idempotency_key == idempotency_key))
        if existing is not None:
            version = await self.session.get(AutomationVersion, existing.draft_version_id)
            if existing.name != body.name or version is None or version.graph_hash != graph_sha256(body.graph):
                raise _error(
                    "automation_version_conflict",
                    409,
                    "Idempotency key was already used for different Automation input.",
                )
            return await self.get_automation(existing.id)

        automation = Automation(
            id=uuid4(),
            name=body.name,
            description=body.description,
            lifecycle="inactive",
            owner_type="operator_managed",
            owner_id=principal.principal_id,
            revision=1,
            idempotency_key=idempotency_key,
        )
        validation = validate_graph(body.graph)
        _require_saveable(validation, allow_empty=not body.graph.nodes)
        self.session.add(automation)
        version = _new_version(
            automation,
            body.graph,
            version_number=1,
            validation=validation,
            principal=principal,
            reason=body.creation_reason,
            idempotency_key=f"{idempotency_key}:version:1",
        )
        self.session.add(version)
        await self.session.flush()
        automation.draft_version_id = version.id
        _record_event(
            self.session,
            event_type="automation.created",
            principal=principal,
            automation_id=automation.id,
            data={"version": 1, "graph_hash": version.graph_hash},
        )
        await self.session.flush()
        return await self.get_automation(automation.id)

    async def patch_automation(
        self,
        automation_id: UUID,
        body: AutomationPatch,
        *,
        principal: SecurityPrincipal,
    ) -> AutomationOut:
        automation = await _automation_for_update(self.session, automation_id)
        _check_revision(automation, body.expected_revision)
        if automation.archived_at is not None:
            raise _error("automation_dependency_conflict", 409, "Archived Automation cannot be edited.")
        if body.name is not None:
            automation.name = body.name.strip()
        if "description" in body.model_fields_set:
            automation.description = body.description
        automation.revision += 1
        _record_event(
            self.session,
            event_type="automation.metadata_updated",
            principal=principal,
            automation_id=automation.id,
            data={"revision": automation.revision},
        )
        return await _materialize_automation(self.session, automation)

    async def list_versions(
        self,
        automation_id: UUID,
        *,
        limit: int,
        cursor: int | None,
    ) -> AutomationVersionPageOut:
        if await self.session.get(Automation, automation_id) is None:
            raise _error("automation_not_found", 404, "Automation was not found.")
        statement = select(AutomationVersion).where(AutomationVersion.automation_id == automation_id)
        if cursor is not None:
            statement = statement.where(AutomationVersion.version < cursor)
        rows = list(
            await self.session.scalars(statement.order_by(AutomationVersion.version.desc()).limit(limit + 1))
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        return AutomationVersionPageOut(
            items=[AutomationVersionOut.model_validate(row) for row in rows],
            next_cursor=str(rows[-1].version) if has_more and rows else None,
        )

    async def get_version(self, automation_id: UUID, version_number: int) -> AutomationVersionOut:
        return AutomationVersionOut.model_validate(
            await _version_by_number(self.session, automation_id, version_number)
        )

    async def create_version(
        self,
        automation_id: UUID,
        body: AutomationVersionCreate,
        *,
        principal: SecurityPrincipal,
        idempotency_key: str,
    ) -> AutomationVersionOut:
        automation = await _automation_for_update(self.session, automation_id)
        existing = await self.session.scalar(
            select(AutomationVersion).where(
                AutomationVersion.automation_id == automation_id,
                AutomationVersion.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.graph_hash != graph_sha256(body.graph):
                raise _error(
                    "automation_version_conflict",
                    409,
                    "Idempotency key was already used for different version input.",
                )
            return await _materialize_version(self.session, existing)
        _check_revision(automation, body.expected_revision)
        if automation.archived_at is not None:
            raise _error("automation_dependency_conflict", 409, "Archived Automation cannot receive a draft.")
        next_number = int(
            await self.session.scalar(
                select(func.coalesce(func.max(AutomationVersion.version), 0)).where(
                    AutomationVersion.automation_id == automation_id
                )
            )
            or 0
        ) + 1
        validation = validate_graph(body.graph)
        _require_saveable(validation, allow_empty=not body.graph.nodes)
        version = _new_version(
            automation,
            body.graph,
            version_number=next_number,
            validation=validation,
            principal=principal,
            reason=body.creation_reason,
            idempotency_key=idempotency_key,
        )
        self.session.add(version)
        await self.session.flush()
        automation.draft_version_id = version.id
        automation.revision += 1
        _record_event(
            self.session,
            event_type="automation.version_created",
            principal=principal,
            automation_id=automation.id,
            data={"version": next_number, "graph_hash": version.graph_hash},
        )
        return await _materialize_version(self.session, version)

    async def restore_version(
        self,
        automation_id: UUID,
        version_number: int,
        body: AutomationVersionRestore,
        *,
        principal: SecurityPrincipal,
        idempotency_key: str,
    ) -> AutomationVersionOut:
        source = await _version_by_number(self.session, automation_id, version_number)
        return await self.create_version(
            automation_id,
            AutomationVersionCreate(
                expected_revision=body.expected_revision,
                graph=WorkflowGraphV1.model_validate(source.graph),
                creation_reason=body.creation_reason,
            ),
            principal=principal,
            idempotency_key=idempotency_key,
        )

    async def validate_version(
        self,
        automation_id: UUID,
        version_number: int,
        *,
        capability_status: CapabilityStatusService | None,
        principal: SecurityPrincipal | None = None,
    ) -> GraphValidationResult:
        version = await _version_by_number(self.session, automation_id, version_number)
        graph = WorkflowGraphV1.model_validate(version.graph)
        structural = validate_graph(graph)
        requests = [ResourceRequest(kind=kind, id=resource_id) for kind, resource_id in graph_resource_requests(graph)]
        resources = await summarize_resources(
            self.session,
            requests,
            automation_id=automation_id,
            capability_status=capability_status,
        )
        findings = list(structural.findings)
        locations = graph_resource_locations(graph)
        for resource in resources:
            if resource.state == "ready":
                continue
            resource_locations = locations.get((resource.kind, resource.id), [(None, None)])
            findings.extend(
                ValidationFinding(
                    code="automation_resource_unavailable",
                    severity="error",
                    message="Referenced resource is not ready.",
                    node_id=node_id,
                    field_path=field_path or f"resource.{resource.kind}.{resource.id}",
                    recovery_action=f"Open {resource.manage_href} and repair or replace the resource.",
                )
                for node_id, field_path in resource_locations
            )
        for node in graph.nodes:
            if node.type != "manual" or node.config.get("story_revision_id") is None:
                continue
            try:
                story_revision_id = UUID(str(node.config["story_revision_id"]))
            except ValueError:
                continue
            if await self.session.get(StoryRevision, story_revision_id) is None:
                findings.append(
                    ValidationFinding(
                        code="automation_resource_unavailable",
                        severity="error",
                        message="Referenced Story revision is unavailable.",
                        node_id=node.id,
                        field_path="config.story_revision_id",
                        recovery_action="Select an existing immutable Story revision.",
                    )
                )
        for node in graph.nodes:
            prompt_snapshots: list[tuple[object, object, str]] = []
            if node.type == "generate_content_pack":
                checksums = node.config.get("prompt_checksums")
                prompt_ids = node.config.get("prompt_version_ids")
                if isinstance(checksums, dict) and isinstance(prompt_ids, list):
                    prompt_snapshots.extend(
                        (raw_id, checksums.get(str(raw_id)), f"config.prompt_checksums.{raw_id}")
                        for raw_id in prompt_ids
                    )
            for raw_id, checksum, field_path in prompt_snapshots:
                if raw_id is None or checksum is None:
                    continue
                try:
                    prompt = await self.session.get(PromptTemplateVersion, UUID(str(raw_id)))
                except ValueError:
                    prompt = None
                if prompt is not None and prompt.checksum_sha256 != checksum:
                    findings.append(
                        ValidationFinding(
                            code="automation_resource_unavailable",
                            severity="error",
                            message="Prompt checksum does not match the saved prompt version.",
                            node_id=node.id,
                            field_path=field_path,
                            recovery_action="Select the prompt version again.",
                        )
                    )
        result = GraphValidationResult(
            valid=not any(item.severity == "error" for item in findings),
            graph_hash=structural.graph_hash,
            findings=findings,
        )
        if principal is not None:
            _record_event(
                self.session,
                event_type="automation.validated",
                principal=principal,
                automation_id=automation_id,
                data={
                    "version": version.version,
                    "graph_hash": result.graph_hash,
                    "valid": result.valid,
                    "finding_codes": sorted({finding.code for finding in result.findings}),
                },
            )
        return result

    async def archive(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        principal: SecurityPrincipal,
    ) -> AutomationOut:
        automation = await _automation_for_update(self.session, automation_id)
        _check_revision(automation, expected_revision)
        if automation.lifecycle == "active":
            raise _error("automation_dependency_conflict", 409, "Pause Automation before archiving.")
        active_run = await self.session.scalar(
            select(AutomationRun.id).where(
                AutomationRun.automation_id == automation_id,
                AutomationRun.status.in_(_ACTIVE_RUN_STATUSES),
            ).limit(1)
        )
        if active_run is not None:
            raise _error("automation_dependency_conflict", 409, "Automation has an active run.")
        projection = await self.session.get(AutomationRuntimeProjection, automation_id)
        if projection is not None:
            route = await self.session.get(AutomationRoute, projection.route_id)
            if route is not None and route.enabled:
                raise _error("automation_dependency_conflict", 409, "Legacy Telegram route is still enabled.")
        schedule = await self.session.scalar(
            select(WorkflowSchedule).where(WorkflowSchedule.schedule_key == f"automation:{automation.id}")
        )
        if schedule is not None:
            schedule.enabled = False
        automation.lifecycle = "archived"
        automation.archived_at = datetime.now(UTC)
        automation.revision += 1
        _record_event(
            self.session,
            event_type="automation.archived",
            principal=principal,
            automation_id=automation.id,
        )
        return await _materialize_automation(self.session, automation)

    async def pause(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        principal: SecurityPrincipal,
    ) -> AutomationOut:
        automation = await _automation_for_update(self.session, automation_id)
        _check_revision(automation, expected_revision)
        if automation.lifecycle != "active":
            raise _error("automation_dependency_conflict", 409, "Only an active Automation can pause.")
        automation.lifecycle = "paused"
        automation.revision += 1
        projection = await self.session.get(AutomationRuntimeProjection, automation_id)
        if projection is not None:
            route = await self.session.get(AutomationRoute, projection.route_id)
            if route is not None:
                route.paused_at = datetime.now(UTC)
        schedule = await self.session.scalar(
            select(WorkflowSchedule).where(WorkflowSchedule.schedule_key == f"automation:{automation.id}")
        )
        if schedule is not None:
            schedule.enabled = False
        _record_event(
            self.session,
            event_type="automation.paused",
            principal=principal,
            automation_id=automation.id,
        )
        return await _materialize_automation(self.session, automation)

    async def resume(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        principal: SecurityPrincipal,
        capability_status: CapabilityStatusService | None,
    ) -> AutomationOut:
        automation = await _automation_for_update(self.session, automation_id)
        _check_revision(automation, expected_revision)
        if automation.lifecycle != "paused":
            raise _error("automation_dependency_conflict", 409, "Only a paused Automation can resume.")
        automation.lifecycle = "active" if automation.active_version_id else "inactive"
        automation.revision += 1
        projection = await self.session.get(AutomationRuntimeProjection, automation_id)
        if projection is not None:
            route = await self.session.get(AutomationRoute, projection.route_id)
            if route is not None:
                if capability_status is None:
                    raise _error("automation_capability_unavailable", 409, "Capability status is unavailable.")
                await capability_status.require_available(
                    "source", route.source_id, "source", job_type="telegram.route.poll"
                )
                await capability_status.require_available(
                    "provider", route.ai_provider_profile_id, "generation", job_type="telegram.route.poll"
                )
                research_profile_id = (route.content_filters or {}).get("research_provider_profile_id")
                if route.research_mode != "off" and research_profile_id is not None:
                    try:
                        parsed_research_profile_id = UUID(str(research_profile_id))
                    except ValueError as exc:
                        raise _error(
                            "automation_resource_unavailable",
                            409,
                            "Research provider reference is invalid.",
                        ) from exc
                    await capability_status.require_available(
                        "provider",
                        parsed_research_profile_id,
                        "research",
                        job_type="telegram.route.poll",
                    )
                if route.publishing_policy == "auto_publish":
                    await capability_status.require_available(
                        "destination", route.destination_id, "publishing", job_type="telegram.route.poll"
                    )
                route.paused_at = None
        schedule = await self.session.scalar(
            select(WorkflowSchedule).where(WorkflowSchedule.schedule_key == f"automation:{automation.id}")
        )
        if schedule is not None and automation.lifecycle == "active":
            schedule.enabled = True
        _record_event(
            self.session,
            event_type="automation.resumed",
            principal=principal,
            automation_id=automation.id,
        )
        return await _materialize_automation(self.session, automation)

    async def activate(
        self,
        automation_id: UUID,
        *,
        expected_revision: int,
        principal: SecurityPrincipal,
        capability_status: CapabilityStatusService | None,
        idempotency_key: str,
    ) -> AutomationOut:
        automation = await _automation_for_update(self.session, automation_id)
        if (
            automation.activation_idempotency_key == idempotency_key
            and automation.active_version_id is not None
            and automation.active_version_id == automation.draft_version_id
        ):
            return await _materialize_automation(self.session, automation)
        _check_revision(automation, expected_revision)
        if automation.draft_version_id is None:
            raise _error("automation_activation_invalid", 409, "Automation has no saved draft version.")
        version = await self.session.get(AutomationVersion, automation.draft_version_id)
        if version is None:
            raise _error("automation_version_not_found", 404, "Draft version was not found.")
        validation = await self.validate_version(
            automation_id,
            version.version,
            capability_status=capability_status,
            principal=principal,
        )
        if not validation.valid:
            raise _error("automation_activation_invalid", 409, "Draft must pass server validation before activation.")
        graph = WorkflowGraphV1.model_validate(version.graph)
        plan = verify_compiled_plan(graph, version.compiled_plan)
        await materialize_runtime_projection(
            self.session,
            automation=automation,
            version=version,
            plan=plan,
        )
        automation.active_version_id = version.id
        automation.lifecycle = "active"
        automation.activation_idempotency_key = idempotency_key
        automation.revision += 1
        _record_event(
            self.session,
            event_type="automation.activated",
            principal=principal,
            automation_id=automation.id,
            data={"version": version.version, "graph_hash": version.graph_hash},
        )
        return await _materialize_automation(self.session, automation)

    async def duplicate(
        self,
        automation_id: UUID,
        *,
        name: str | None,
        description: str | None,
        principal: SecurityPrincipal,
        idempotency_key: str,
    ) -> AutomationDetailOut:
        source = await self.get_automation(automation_id)
        version = source.draft_version or source.active_version
        if version is None:
            raise _error("automation_version_not_found", 404, "Automation has no version to duplicate.")
        return await self.create_automation(
            AutomationCreate(
                name=name or f"{source.name} copy",
                description=description if description is not None else source.description,
                graph=version.graph,
                creation_reason=f"duplicated from {automation_id}",
            ),
            principal=principal,
            idempotency_key=idempotency_key,
        )

    async def create_from_template(
        self,
        template_key: str,
        *,
        name: str | None,
        description: str | None,
        principal: SecurityPrincipal,
        idempotency_key: str,
    ) -> AutomationDetailOut:
        template = await self.session.scalar(
            select(AutomationTemplate)
            .where(AutomationTemplate.seed_key == template_key, AutomationTemplate.archived_at.is_(None))
            .order_by(AutomationTemplate.seed_version.desc())
            .limit(1)
        )
        if template is None:
            raise _error("automation_template_not_found", 404, "Automation template was not found.")
        return await self.create_automation(
            AutomationCreate(
                name=name or template.name,
                description=description if description is not None else template.description,
                graph=WorkflowGraphV1.model_validate(template.graph_seed),
                creation_reason=f"created from template {template.seed_key}:{template.seed_version}",
            ),
            principal=principal,
            idempotency_key=idempotency_key,
        )


__all__ = ["AutomationDefinitionService"]
