from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, time, timedelta
from typing import cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.artifacts import make_artifact, normalize_artifact, summary_with_artifact
from app.automations.definitions.compiler import CompiledWorkflowPlan, verify_compiled_plan
from app.automations.definitions.errors import AutomationDefinitionError
from app.automations.definitions.models import (
    Automation,
    AutomationNodeRun,
    AutomationRun,
    AutomationVersion,
)
from app.automations.definitions.registry import PlatformName
from app.automations.definitions.schemas import (
    AutomationNodeRunOut,
    AutomationRunOut,
    AutomationRunPageOut,
    AutomationRunStart,
    WorkflowGraphV1,
)
from app.generation.commands import GeneratePackRequest
from app.generation.editorial_service import EditorialService
from app.generation.models import PromptTemplate, PromptTemplateVersion
from app.generation.multiplatform import PLATFORM_PROMPT_PURPOSE
from app.jobs.credential_capabilities import CapabilityStatusService
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowJob, WorkflowSchedule
from app.security.auth import SecurityPrincipal
from app.stories.models import StoryRevision


def _error(code: str, status: int, message: str) -> AutomationDefinitionError:
    return AutomationDefinitionError(code, status, message)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _uuid(value: object, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise _error("automation_activation_invalid", 409, f"Compiled {field} reference is invalid.") from None


def _stage(plan: CompiledWorkflowPlan, node_type: str):
    return next((item for item in plan.stages if item.node_type == node_type), None)


def _node_map(plan: CompiledWorkflowPlan) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for stage in plan.stages:
        result.setdefault(stage.node_type, []).append(stage.node_id)
    return result


_PRIVATE_PROJECTION_KEY = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|access[_-]?token|refresh[_-]?token|"
    r"raw[_-]?(?:prompt|response)|prompt[_-]?(?:body|text)|system[_-]?prompt|stack[_-]?trace|traceback|"
    r"request[_-]?headers|response[_-]?headers|messages)",
    re.IGNORECASE,
)


def _safe_projection_value(value: object, *, depth: int = 0) -> object:
    if depth >= 6:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(key): _safe_projection_value(item, depth=depth + 1)
            for key, item in value.items()
            if not _PRIVATE_PROJECTION_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [_safe_projection_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value[:2_000]
    return value


async def _materialize_run(session: AsyncSession, run: AutomationRun) -> AutomationRunOut:
    await session.flush()
    await session.refresh(run)
    nodes = list(
        await session.scalars(
            select(AutomationNodeRun)
            .where(AutomationNodeRun.automation_run_id == run.id)
            .order_by(AutomationNodeRun.created_at, AutomationNodeRun.node_id)
        )
    )
    run_data = AutomationRunOut.model_validate(run).model_dump(exclude={"nodes"})
    run_data["trigger_metadata"] = _safe_projection_value(run_data["trigger_metadata"])
    run_data["resource_snapshot"] = _safe_projection_value(run_data["resource_snapshot"])
    node_outputs: list[AutomationNodeRunOut] = []
    for item in nodes:
        node_data = AutomationNodeRunOut.model_validate(item).model_dump()
        for field in ("input_summary", "output_summary", "usage", "retry_metadata"):
            node_data[field] = _safe_projection_value(node_data[field])
        if isinstance(node_data.get("output_summary"), dict):
            artifact = normalize_artifact(
                node_data["output_summary"],
                source_node_id=item.node_id,
                workflow_id=str(run.automation_id),
                workflow_version_id=str(run.automation_version_id),
                run_id=str(run.id),
            )
            if artifact is not None:
                node_data["output_summary"] = summary_with_artifact(node_data["output_summary"], artifact)
                node_data["artifact"] = artifact.model_dump(mode="json")
        node_outputs.append(AutomationNodeRunOut.model_validate(node_data))
    return AutomationRunOut(**run_data, nodes=node_outputs)


def _next_schedule_run(config: dict[str, object], now: datetime) -> datetime:
    if config.get("schedule_kind") == "interval":
        return now + timedelta(minutes=int(str(config.get("interval_minutes") or 0)))
    zone = ZoneInfo(str(config.get("timezone") or "Asia/Tehran"))
    local_time = time.fromisoformat(str(config.get("local_time")))
    local_now = now.astimezone(zone)
    candidate = datetime.combine(local_now.date(), local_time, tzinfo=zone)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


async def require_exact_generation_prompts(
    session: AsyncSession,
    *,
    generate_config: dict[str, object],
) -> None:
    raw_platforms = generate_config.get("platforms")
    platforms: list[PlatformName] = (
        [cast(PlatformName, str(item)) for item in raw_platforms]
        if isinstance(raw_platforms, list)
        else ["telegram"]
    )
    raw_prompt_ids = generate_config.get("prompt_version_ids")
    prompt_id_values = raw_prompt_ids if isinstance(raw_prompt_ids, list) else []
    configured_prompt_ids = {
        _uuid(item, "prompt version") for item in prompt_id_values
    }
    raw_checksums = generate_config.get("prompt_checksums")
    checksum_values = raw_checksums if isinstance(raw_checksums, dict) else {}
    configured_checksums = {
        _uuid(key, "prompt version"): str(value)
        for key, value in checksum_values.items()
    }
    required_purposes = {"canonical_story", *(PLATFORM_PROMPT_PURPOSE[item] for item in platforms)}
    prompts = list(
        await session.scalars(
            select(PromptTemplateVersion)
            .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.prompt_template_id)
            .where(
                PromptTemplateVersion.id.in_(configured_prompt_ids),
                PromptTemplateVersion.is_active.is_(True),
                PromptTemplate.purpose_key.in_(required_purposes),
            )
        )
    )
    if (
        {item.id for item in prompts} != configured_prompt_ids
        or len(prompts) != len(required_purposes)
        or any(configured_checksums.get(item.id) != item.checksum_sha256 for item in prompts)
    ):
        raise _error(
            "automation_resource_unavailable",
            409,
            "Pinned prompt versions are not the exact active generation set.",
        )


async def materialize_runtime_projection(
    session: AsyncSession,
    *,
    automation: Automation,
    version: AutomationVersion,
    plan: CompiledWorkflowPlan,
) -> None:
    if plan.trigger_kind == "schedule":
        trigger = _stage(plan, "schedule")
        select_content = _stage(plan, "select_content")
        generate = _stage(plan, "generate_content_pack")
        if trigger is None or select_content is None or generate is None:
            raise _error(
                "automation_activation_invalid",
                409,
                "Schedule workflow requires schedule, selection, generation, and output stages.",
            )
        await require_exact_generation_prompts(session, generate_config=generate.config)
        schedule = await session.scalar(
            select(WorkflowSchedule).where(WorkflowSchedule.schedule_key == f"automation:{automation.id}")
        )
        config = dict(trigger.config)
        now = datetime.now(UTC)
        if schedule is None:
            schedule = WorkflowSchedule(id=uuid4(), schedule_key=f"automation:{automation.id}")
            session.add(schedule)
        schedule.name = automation.name
        schedule.job_type = "automation.run.start"
        schedule.payload = {
            "automation_id": str(automation.id),
            "automation_version_id": str(version.id),
        }
        schedule.schedule_kind = str(config.get("schedule_kind") or "daily")
        schedule.timezone = str(config.get("timezone") or "Asia/Tehran")
        schedule.local_time = str(config["local_time"]) if config.get("local_time") is not None else None
        schedule.interval_minutes = (
            int(config["interval_minutes"]) if config.get("interval_minutes") is not None else None
        )
        schedule.next_run_at = _next_schedule_run(config, now)
        schedule.enabled = True
        schedule.pause_sensitive = True
        return None
    return None


class AutomationExecutionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def start(
        self,
        automation_id: UUID,
        body: AutomationRunStart,
        *,
        principal: SecurityPrincipal,
        capability_status: CapabilityStatusService | None,
        idempotency_key: str,
    ) -> AutomationRunOut:
        request_hash = _hash(body.model_dump(mode="json", exclude_none=True))
        existing = await self.session.scalar(
            select(AutomationRun).where(AutomationRun.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash or existing.automation_id != automation_id:
                raise _error("automation_run_conflict", 409, "Run idempotency key was used for different input.")
            return await _materialize_run(self.session, existing)

        automation = await self.session.scalar(
            select(Automation).where(Automation.id == automation_id).with_for_update()
        )
        if automation is None:
            raise _error("automation_not_found", 404, "Automation was not found.")
        control = await self.session.get(AutomationControl, "global")
        if automation.lifecycle == "paused" or (control is not None and control.global_pause):
            raise _error("automation_paused", 409, "Automation execution is paused.")
        version = None
        if body.version_number is not None:
            version = await self.session.scalar(
                select(AutomationVersion).where(
                    AutomationVersion.automation_id == automation.id,
                    AutomationVersion.version == body.version_number,
                )
            )
        elif automation.active_version_id is not None:
            version = await self.session.get(AutomationVersion, automation.active_version_id)
        elif automation.draft_version_id is not None and body.dry_run:
            version = await self.session.get(AutomationVersion, automation.draft_version_id)
        if version is None:
            raise _error("automation_version_not_found", 404, "Runnable Automation version was not found.")

        from app.automations.definitions.service import AutomationDefinitionService

        validation = await AutomationDefinitionService(self.session).validate_version(
            automation.id,
            version.version,
            capability_status=capability_status,
        )
        if not validation.valid:
            raise _error("automation_resource_unavailable", 409, "Run resources are not ready.")
        graph = WorkflowGraphV1.model_validate(version.graph)
        plan = verify_compiled_plan(graph, version.compiled_plan)
        if plan.trigger_kind == "manual":
            if body.source_message_id is not None:
                raise _error(
                    "automation_run_input_invalid",
                    422,
                    "Manual workflow input does not accept a Telegram source message ID.",
                )
            return await self._start_manual_content_pack(
                automation=automation,
                version=version,
                plan=plan,
                body=body,
                principal=principal,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        if plan.trigger_kind != "manual":
            raise _error(
                "automation_run_input_invalid",
                422,
                "On-demand workflow start supports Manual workflows only; scheduled or source-triggered "
                "workflows start from their trigger.",
            )

    async def _start_manual_content_pack(
        self,
        *,
        automation: Automation,
        version: AutomationVersion,
        plan: CompiledWorkflowPlan,
        body: AutomationRunStart,
        principal: SecurityPrincipal,
        idempotency_key: str,
        request_hash: str,
    ) -> AutomationRunOut:
        manual = _stage(plan, "manual")
        generate = _stage(plan, "generate_content_pack")
        if manual is None or generate is None:
            raise _error(
                "automation_run_input_invalid",
                422,
                "Manual workflow requires a content-package generation stage.",
            )
        if body.story_revision_id is not None:
            revision = await self.session.get(StoryRevision, body.story_revision_id)
        elif body.story_id is not None:
            revision = await self.session.scalar(
                select(StoryRevision)
                .where(StoryRevision.story_id == body.story_id)
                .order_by(StoryRevision.revision_number.desc(), StoryRevision.id.desc())
                .limit(1)
            )
        else:
            revision = await self.session.get(
                StoryRevision,
                _uuid(manual.config.get("story_revision_id"), "Story revision"),
            )
        if revision is None:
            raise _error("automation_resource_unavailable", 409, "Story revision is unavailable.")
        provider_id = _uuid(generate.config.get("provider_profile_id"), "provider")
        brand_id = _uuid(generate.config.get("editorial_profile_id"), "editorial profile")
        platforms = list(generate.config.get("platforms") or ["telegram"])
        await require_exact_generation_prompts(self.session, generate_config=generate.config)
        research = _stage(plan, "research")
        now = datetime.now(UTC)
        manual_artifact = make_artifact(
            kind="article",
            capabilities=["textual", "structured", "article", "reviewable", "generatable"],
            payload={"story_revision_id": str(revision.id), "story_id": str(revision.story_id)},
            source_node_id=manual.node_id,
            workflow_id=str(automation.id),
            workflow_version_id=str(version.id),
            trigger_type="manual",
            occurred_at=now,
        )
        run = AutomationRun(
            id=uuid4(),
            automation_id=automation.id,
            automation_version_id=version.id,
            trigger_kind="manual",
            trigger_metadata={
                "story_id": str(revision.story_id),
                "story_revision_id": str(revision.id),
                "input_source": "test_studio" if body.story_id or body.story_revision_id else "saved_workflow",
            },
            dry_run=body.dry_run,
            status="queued",
            current_node_id=generate.node_id,
            resource_snapshot={
                "automation_version": version.version,
                "graph_hash": version.graph_hash,
                "compiler_version": plan.compiler_version,
                "plan_hash": plan.plan_hash,
                "required_resources": list(plan.required_resources),
                "node_ids_by_type": _node_map(plan),
                "node_types_by_id": {stage.node_id: stage.node_type for stage in plan.stages},
                "node_order": [stage.node_id for stage in plan.stages],
                "current_artifact": manual_artifact.model_dump(mode="json"),
            },
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            started_at=now,
        )
        self.session.add(run)
        await self.session.flush()
        nodes: dict[str, AutomationNodeRun] = {}
        for stage in plan.stages:
            status = "succeeded" if stage.node_id == manual.node_id else "pending"
            if body.dry_run and stage.node_id in plan.publishing_node_ids:
                status = "skipped"
            row = AutomationNodeRun(
                id=uuid4(),
                automation_run_id=run.id,
                node_id=stage.node_id,
                status=status,
                started_at=now if status == "succeeded" else None,
                finished_at=now if status in {"succeeded", "skipped"} else None,
                input_summary={"story_revision_id": str(revision.id)} if stage.node_id == manual.node_id else {},
                output_summary=(
                    summary_with_artifact({"reason": "dry_run_publication_disabled"}, manual_artifact)
                    if status == "skipped"
                    else summary_with_artifact({}, manual_artifact) if stage.node_id == manual.node_id else {}
                ),
            )
            self.session.add(row)
            nodes[stage.node_id] = row
        await self.session.flush()
        request = GeneratePackRequest(
            brand_profile_id=brand_id,
            platforms=platforms,  # type: ignore[arg-type]
            generation_provider_profile_id=provider_id,
            research_mode=(str(research.config.get("mode")) if research is not None else "off"),  # type: ignore[arg-type]
            research_provider_profile_id=(
                _uuid(research.config.get("provider_profile_id"), "research provider")
                if research is not None
                else None
            ),
        )
        accepted = await EditorialService(self.session).request_content_pack(revision.story_id, request)
        job = await self.session.get(WorkflowJob, accepted.job_id)
        if job is None:
            raise _error("automation_capability_unavailable", 409, "Generation job was not created.")
        if job.automation_run_id is not None and job.automation_run_id != run.id:
            raise _error(
                "automation_run_conflict",
                409,
                "The exact generation request is already owned by another Automation run.",
            )
        target_stage = research if research is not None and job.job_type == "research_story" else generate
        target_node = nodes[target_stage.node_id]
        target_node.status = "queued"
        target_node.workflow_job_id = job.id
        job.automation_run_id = run.id
        job.automation_node_run_id = target_node.id
        run.root_workflow_job_id = job.id
        run.current_node_id = target_stage.node_id
        self.session.add(
            WorkflowEvent(
                workflow_job_id=job.id,
                event_type="automation.run.started",
                actor=f"{principal.principal_type}:{principal.principal_id}"[:255],
                event_data={
                    "automation_id": str(automation.id),
                    "automation_run_id": str(run.id),
                    "automation_version": version.version,
                    "dry_run": body.dry_run,
                },
            )
        )
        return await _materialize_run(self.session, run)

    async def get(self, run_id: UUID) -> AutomationRunOut:
        run = await self.session.get(AutomationRun, run_id)
        if run is None:
            raise _error("automation_run_not_found", 404, "Automation run was not found.")
        return await _materialize_run(self.session, run)

    async def list(
        self,
        automation_id: UUID,
        *,
        limit: int,
        cursor: UUID | None,
        status: str | None = None,
        dry_run: bool | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        failed_only: bool = False,
    ) -> AutomationRunPageOut:
        statement = select(AutomationRun).where(AutomationRun.automation_id == automation_id)
        if status is not None:
            statement = statement.where(AutomationRun.status == status)
        if dry_run is not None:
            statement = statement.where(AutomationRun.dry_run.is_(dry_run))
        if date_from is not None:
            statement = statement.where(AutomationRun.created_at >= date_from)
        if date_to is not None:
            statement = statement.where(AutomationRun.created_at <= date_to)
        if failed_only:
            statement = statement.where(AutomationRun.status == "failed")
        if cursor is not None:
            cursor_run = await self.session.get(AutomationRun, cursor)
            if cursor_run is None or cursor_run.automation_id != automation_id:
                raise _error("automation_run_not_found", 404, "Automation run cursor was not found.")
            statement = statement.where(
                or_(
                    AutomationRun.created_at < cursor_run.created_at,
                    and_(AutomationRun.created_at == cursor_run.created_at, AutomationRun.id < cursor_run.id),
                )
            )
        rows = list(
            await self.session.scalars(
                statement.order_by(AutomationRun.created_at.desc(), AutomationRun.id.desc()).limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        return AutomationRunPageOut(
            items=[await _materialize_run(self.session, item) for item in rows],
            next_cursor=str(rows[-1].id) if has_more and rows else None,
        )


__all__ = ["AutomationExecutionService", "materialize_runtime_projection"]
