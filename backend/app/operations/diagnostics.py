from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.automations.models import AutomationDispatch, AutomationRoute
from app.core.config import settings
from app.core.redaction import redact_secrets, redact_string
from app.db.models import Source
from app.generation.models import GenerationRun
from app.jobs.models import AutomationControl, WorkflowJob
from app.jobs.runtime import RuntimeHeartbeatService
from app.jobs.types import JobStatus
from app.operations.health import database_time, normalize_utc, snapshot_high_water
from app.publishing.models import Destination, Publication, PublishJob
from app.research.models import ResearchAttempt, ResearchRun

AttentionKind = Literal[
    "job",
    "route",
    "research",
    "generation",
    "publication",
    "destination",
    "source",
]


class ComponentHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy", "degraded", "down", "unknown"]
    observed_at: datetime | None
    last_success_at: datetime | None
    message: str
    action_url: str | None


class AttentionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    severity: Literal["warning", "error"]
    kind: AttentionKind
    title: str
    occurred_at: datetime
    action_url: str


class OperationsSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    global_paused: bool
    dry_run: bool
    components: dict[str, ComponentHealth]
    queue_counts: dict[str, int]
    attention: list[AttentionItem]


class Clock(Protocol):
    def now(self) -> datetime: ...


ClockSource = Clock | Callable[[], datetime]


class OperationsDiagnostics:
    """Build a read-only operational projection from already-durable state."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: ClockSource | None = None,
        expected_runtime_component_ids: str | None = None,
    ) -> None:
        self.session = session
        self.clock = clock
        self.expected_runtime_component_ids = (
            settings.expected_runtime_component_ids
            if expected_runtime_component_ids is None
            else expected_runtime_component_ids
        )

    async def snapshot(self) -> OperationsSnapshot:
        heartbeats = await RuntimeHeartbeatService(self.session).list_recent(limit=10_000)
        control = await self.session.get(AutomationControl, "global")
        queue_counts = await self._queue_counts()
        attention = await self._attention()
        generated_at = await self._generated_at(heartbeats, attention)
        return OperationsSnapshot(
            generated_at=generated_at,
            global_paused=bool(control and control.global_pause),
            dry_run=bool(control and control.dry_run),
            components=_component_health(
                heartbeats,
                generated_at=generated_at,
                expected_component_ids=self.expected_runtime_component_ids,
            ),
            queue_counts=queue_counts,
            attention=attention,
        )

    async def _generated_at(
        self,
        heartbeats: Sequence[object],
        attention: Sequence[AttentionItem],
    ) -> datetime:
        # Read the clock only after all projected rows. Under PostgreSQL's
        # READ COMMITTED visibility a heartbeat may commit while this snapshot
        # is being assembled; the final database clock/high-water boundary
        # guarantees that no returned observation postdates generated_at.
        observed_at = _now(self.clock) if self.clock is not None else await database_time(self.session)
        timestamps = [observed_at]
        timestamps.extend(heartbeat.observed_at for heartbeat in heartbeats)
        timestamps.extend(item.occurred_at for item in attention)
        return snapshot_high_water(*timestamps)

    async def _queue_counts(self) -> dict[str, int]:
        rows = await self.session.execute(select(WorkflowJob.status, func.count()).group_by(WorkflowJob.status))
        counts = {status.value: 0 for status in JobStatus}
        for status, count in rows:
            counts[_status_text(status)] = int(count)
        return counts

    async def _attention(self) -> list[AttentionItem]:
        workflow_jobs = list(
            await self.session.scalars(
                select(WorkflowJob)
                .where(WorkflowJob.status.in_((JobStatus.FAILED, JobStatus.NEEDS_REVIEW)))
                .order_by(WorkflowJob.updated_at.desc(), WorkflowJob.id.desc())
                .limit(100)
            )
        )
        sources = list(
            await self.session.scalars(
                select(Source)
                .where(
                    Source.active.is_(True),
                    or_(Source.health_status != "healthy", Source.failure_count > 0),
                )
                .order_by(func.coalesce(Source.last_failure_at, Source.updated_at).desc(), Source.id.desc())
                .limit(100)
            )
        )
        destinations = list(
            await self.session.scalars(
                select(Destination)
                .where(Destination.enabled.is_(True), Destination.health_status != "healthy")
                .order_by(
                    func.coalesce(Destination.last_health_check_at, Destination.updated_at).desc(),
                    Destination.id.desc(),
                )
                .limit(100)
            )
        )
        paused_routes = list(
            await self.session.scalars(
                select(AutomationRoute)
                .where(AutomationRoute.enabled.is_(True), AutomationRoute.paused_at.is_not(None))
                .order_by(AutomationRoute.paused_at.desc(), AutomationRoute.id.desc())
                .limit(100)
            )
        )
        latest_problem_dispatch = aliased(AutomationDispatch)
        latest_problem_dispatch_id = (
            select(AutomationDispatch.id)
            .where(
                AutomationDispatch.route_id == latest_problem_dispatch.route_id,
                AutomationDispatch.status.in_(("failed", "needs_review")),
            )
            .order_by(AutomationDispatch.updated_at.desc(), AutomationDispatch.id.desc())
            .limit(1)
            .correlate(latest_problem_dispatch)
            .scalar_subquery()
        )
        problem_dispatches = list(
            await self.session.scalars(
                select(latest_problem_dispatch)
                .where(
                    latest_problem_dispatch.status.in_(("failed", "needs_review")),
                    latest_problem_dispatch.id == latest_problem_dispatch_id,
                )
                .order_by(
                    latest_problem_dispatch.updated_at.desc(),
                    latest_problem_dispatch.id.desc(),
                )
                .limit(100)
            )
        )
        latest_research_attempt = aliased(ResearchAttempt)
        latest_research_attempt_number = (
            select(func.max(ResearchAttempt.attempt_number))
            .where(ResearchAttempt.research_run_id == ResearchRun.id)
            .correlate(ResearchRun)
            .scalar_subquery()
        )
        research_rows = list(
            (
                await self.session.execute(
                    select(ResearchRun, latest_research_attempt)
                    .outerjoin(
                        latest_research_attempt,
                        and_(
                            latest_research_attempt.research_run_id == ResearchRun.id,
                            latest_research_attempt.attempt_number == latest_research_attempt_number,
                        ),
                    )
                    .where(ResearchRun.status.in_(("failed", "needs_review")))
                    .order_by(
                        func.coalesce(
                            ResearchRun.finished_at,
                            latest_research_attempt.finished_at,
                            latest_research_attempt.started_at,
                            ResearchRun.started_at,
                            ResearchRun.created_at,
                        ).desc(),
                        ResearchRun.id.desc(),
                    )
                    .limit(100)
                )
            ).all()
        )
        generation_runs = list(
            await self.session.scalars(
                select(GenerationRun)
                .where(GenerationRun.status.in_(("failed", "needs_review")))
                .order_by(
                    func.coalesce(
                        GenerationRun.finished_at,
                        GenerationRun.started_at,
                        GenerationRun.created_at,
                    ).desc(),
                    GenerationRun.id.desc(),
                )
                .limit(100)
            )
        )
        publish_jobs = list(
            await self.session.scalars(
                select(PublishJob)
                .where(PublishJob.status.in_(("attention", "reconciliation_required")))
                .order_by(PublishJob.updated_at.desc(), PublishJob.id.desc())
                .limit(100)
            )
        )
        publication_rows = list(
            (
                await self.session.execute(
                    select(Publication, PublishJob.workflow_job_id)
                    .join(PublishJob, PublishJob.id == Publication.publish_job_id)
                    .where(Publication.reconciliation_status != "confirmed")
                    .order_by(Publication.published_at.desc(), Publication.id.desc())
                    .limit(100)
                )
            ).all()
        )

        links = _attention_links(workflow_jobs)
        candidates = [_job_attention(job) for job in workflow_jobs]
        for source in sources:
            item = _source_attention(source)
            if _newer_than_links(item.occurred_at, links["source"].get(str(source.id))):
                candidates.append(item)
        for destination in destinations:
            item = _destination_attention(destination)
            if _newer_than_links(
                item.occurred_at,
                links["destination"].get(str(destination.id)),
            ):
                candidates.append(item)
        for route in paused_routes:
            item = _paused_route_attention(route)
            if _newer_than_links(item.occurred_at, links["route"].get(str(route.id))):
                candidates.append(item)
        for dispatch in problem_dispatches:
            item = _dispatch_attention(dispatch)
            if _newer_than_links(
                item.occurred_at,
                links["route"].get(str(dispatch.route_id)),
                links["dispatch"].get(str(dispatch.id)),
            ):
                candidates.append(item)
        for run, attempt in research_rows:
            item = _research_attention(run, attempt)
            if _newer_than_links(item.occurred_at, links["research"].get(str(run.id))):
                candidates.append(item)
        for run in generation_runs:
            item = _generation_attention(run)
            if _newer_than_links(
                item.occurred_at,
                links["generation"].get(str(run.id)),
                links["workflow_job"].get(_generation_workflow_job_id(run)),
            ):
                candidates.append(item)
        for job in publish_jobs:
            item = _publish_job_attention(job)
            if _newer_than_links(
                item.occurred_at,
                links["workflow_job"].get(str(job.workflow_job_id)),
            ):
                candidates.append(item)
        for publication, workflow_job_id in publication_rows:
            item = _publication_attention(publication)
            if _newer_than_links(
                item.occurred_at,
                links["workflow_job"].get(str(workflow_job_id)),
            ):
                candidates.append(item)
        return _newest_distinct(candidates, limit=100)


def _now(clock: ClockSource | None) -> datetime:
    if clock is None:
        value = datetime.now(UTC)
    elif callable(clock):
        value = clock()
    else:
        value = clock.now()
    return normalize_utc(value, field="clock")


def _component_health(
    heartbeats: list[object],
    *,
    generated_at: datetime,
    expected_component_ids: str,
) -> dict[str, ComponentHealth]:
    expected = {value.strip() for value in expected_component_ids.split(",") if value.strip()}
    by_id: dict[str, object] = {}
    for heartbeat in heartbeats:
        by_id.setdefault(str(heartbeat.component_id), heartbeat)

    components: dict[str, ComponentHealth] = {}
    for component_id in sorted(expected | set(by_id)):
        heartbeat = by_id.get(component_id)
        if heartbeat is None:
            components[component_id] = ComponentHealth(
                status="unknown",
                observed_at=None,
                last_success_at=None,
                message="No persisted heartbeat has been observed",
                action_url=_component_action_url(component_id, None),
            )
            continue
        observed_at = normalize_utc(heartbeat.observed_at, field="heartbeat observed_at")
        age = generated_at - observed_at
        if age <= timedelta(seconds=30):
            status = "healthy"
            message = "Heartbeat observed within 30 seconds"
        elif age <= timedelta(seconds=90):
            status = "degraded"
            message = "Heartbeat is older than 30 seconds"
        else:
            status = "down"
            message = "Heartbeat is older than 90 seconds"
        components[component_id] = ComponentHealth(
            status=status,
            observed_at=observed_at,
            last_success_at=None,
            message=message,
            action_url=_component_action_url(component_id, heartbeat),
        )
    return components


def _job_attention(job: WorkflowJob) -> AttentionItem:
    kind = _job_kind(job.job_type)
    detail = job.error_message or job.error_code or "Operator review required"
    return AttentionItem(
        id=str(job.id),
        severity="error" if _status_text(job.status) == JobStatus.FAILED else "warning",
        kind=kind,
        title=_safe_text(job.job_type, ": ", detail),
        occurred_at=job.updated_at,
        action_url="/jobs",
    )


def _source_attention(source: Source) -> AttentionItem:
    detail = source.last_error_message or source.last_error_type or source.health_status
    return AttentionItem(
        id=f"source:{source.id}",
        severity="error" if source.health_status in {"broken", "unhealthy", "failed"} else "warning",
        kind="source",
        title=_safe_text("Source ", source.name, ": ", detail),
        occurred_at=source.last_failure_at or source.updated_at,
        action_url="/sources",
    )


def _destination_attention(destination: Destination) -> AttentionItem:
    return AttentionItem(
        id=f"destination:{destination.id}",
        severity="error" if destination.health_status in {"broken", "unhealthy", "failed"} else "warning",
        kind="destination",
        title=_safe_text("Destination ", destination.name, ": ", destination.health_status),
        occurred_at=destination.last_health_check_at or destination.updated_at,
        action_url="/automations",
    )


def _paused_route_attention(route: AutomationRoute) -> AttentionItem:
    return AttentionItem(
        id=f"route:{route.id}",
        severity="warning",
        kind="route",
        title=_safe_text("Automation ", route.name, " is paused"),
        occurred_at=route.paused_at,
        action_url=f"/automations/{route.id}",
    )


def _dispatch_attention(dispatch: AutomationDispatch) -> AttentionItem:
    detail = dispatch.error_message or dispatch.error_code or dispatch.status
    return AttentionItem(
        id=f"route:{dispatch.route_id}",
        severity="error" if dispatch.status == "failed" else "warning",
        kind="route",
        title=_safe_text("Automation dispatch: ", detail),
        occurred_at=dispatch.updated_at,
        action_url=f"/automations/{dispatch.route_id}",
    )


def _research_attention(run: ResearchRun, attempt: ResearchAttempt | None) -> AttentionItem:
    detail = (
        (attempt.error_message or attempt.error_code or attempt.error_class) if attempt is not None else None
    ) or run.status
    occurred_at = (
        run.finished_at
        or ((attempt.finished_at or attempt.started_at) if attempt is not None else None)
        or run.started_at
        or run.created_at
    )
    return AttentionItem(
        id=f"research:{run.id}",
        severity="error" if run.status == "failed" else "warning",
        kind="research",
        title=_safe_text("Research run: ", detail),
        occurred_at=occurred_at,
        action_url="/inbox",
    )


def _generation_attention(run: GenerationRun) -> AttentionItem:
    detail = run.error_message or run.error_code or run.error_class or run.status
    return AttentionItem(
        id=f"generation:{run.id}",
        severity="error" if run.status == "failed" else "warning",
        kind="generation",
        title=_safe_text("Generation run: ", detail),
        occurred_at=run.finished_at or run.started_at or run.created_at,
        action_url="/drafts",
    )


def _publish_job_attention(job: PublishJob) -> AttentionItem:
    return AttentionItem(
        id=f"publication:{job.id}",
        severity="error" if job.status == "attention" else "warning",
        kind="publication",
        title=_safe_text("Publish job requires attention: ", job.status),
        occurred_at=job.updated_at,
        action_url="/jobs",
    )


def _publication_attention(publication: Publication) -> AttentionItem:
    return AttentionItem(
        id=f"publication:{publication.publish_job_id}",
        severity="warning",
        kind="publication",
        title=_safe_text("Publication requires reconciliation: ", publication.reconciliation_status),
        occurred_at=publication.published_at,
        action_url="/jobs",
    )


def _newest_distinct(candidates: list[AttentionItem], *, limit: int) -> list[AttentionItem]:
    ordered = sorted(candidates, key=lambda item: (item.occurred_at, item.id), reverse=True)
    result: list[AttentionItem] = []
    seen: set[str] = set()
    for candidate in ordered:
        if candidate.id in seen:
            continue
        seen.add(candidate.id)
        result.append(candidate)
        if len(result) == limit:
            break
    return result


def _component_action_url(component_id: str, heartbeat: object | None) -> str:
    component_type = str(getattr(heartbeat, "component_type", "")).casefold()
    capabilities = {str(capability).casefold() for capability in (getattr(heartbeat, "capabilities", None) or ())}
    normalized_id = component_id.casefold()
    if component_type == "scheduler" or "scheduling" in capabilities or "scheduler" in normalized_id:
        return "/automations"
    if (
        component_type == "worker"
        or capabilities
        & {
            "generation",
            "ingestion",
            "publishing",
            "source",
        }
        or "worker" in normalized_id
    ):
        return "/jobs"
    return "/diagnostics"


def _attention_links(workflow_jobs: list[WorkflowJob]) -> dict[str, dict[str, datetime]]:
    links: dict[str, dict[str, datetime]] = {
        "workflow_job": {str(job.id): job.updated_at for job in workflow_jobs},
        "source": {},
        "destination": {},
        "route": {},
        "dispatch": {},
        "research": {},
        "generation": {},
    }
    for job in workflow_jobs:
        payloads = (getattr(job, "payload", None), getattr(job, "result", None))
        kind = _job_kind(job.job_type)
        if kind == "source":
            _record_links(
                links["source"],
                _nested_ids(payloads, {"source_id", "source_ids"}),
                job.updated_at,
            )
        elif kind == "destination":
            _record_links(
                links["destination"],
                _nested_ids(payloads, {"destination_id"}),
                job.updated_at,
            )
        elif kind == "route":
            _record_links(
                links["route"],
                _nested_ids(payloads, {"route_id"}),
                job.updated_at,
            )
            _record_links(
                links["dispatch"],
                _nested_ids(payloads, {"dispatch_id"}),
                job.updated_at,
            )
        elif kind == "research":
            _record_links(
                links["research"],
                _nested_ids(payloads, {"run_id", "research_run_id"}),
                job.updated_at,
            )
        elif kind == "generation":
            _record_links(
                links["generation"],
                _nested_ids(payloads, {"run_id", "generation_run_id"}),
                job.updated_at,
            )
    return links


def _record_links(target: dict[str, datetime], identifiers: set[str], occurred_at: datetime) -> None:
    for identifier in identifiers:
        previous = target.get(identifier)
        if previous is None or occurred_at > previous:
            target[identifier] = occurred_at


def _newer_than_links(occurred_at: datetime, *linked_at: datetime | None) -> bool:
    persisted_links = [value for value in linked_at if value is not None]
    return not persisted_links or occurred_at > max(persisted_links)


def _nested_ids(value: object, keys: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in keys:
                found.update(_id_values(item))
            found.update(_nested_ids(item, keys))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            found.update(_nested_ids(item, keys))
    return found


def _id_values(value: object) -> set[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return {str(item) for item in value if item is not None}
    return {str(value)} if value is not None else set()


def _generation_workflow_job_id(run: GenerationRun) -> str | None:
    request_payload = getattr(run, "request_payload", None)
    if not isinstance(request_payload, Mapping):
        return None
    execution = request_payload.get("execution")
    if not isinstance(execution, Mapping):
        return None
    value = execution.get("workflow_job_id")
    return str(value) if value is not None else None


def _job_kind(job_type: str) -> AttentionKind:
    normalized = job_type.casefold()
    if "research" in normalized:
        return "research"
    if "generation" in normalized or normalized == "story.group_pending":
        return "generation"
    if "publish" in normalized:
        return "publication"
    if "destination" in normalized:
        return "destination"
    if "route" in normalized:
        return "route"
    if "source" in normalized or "ingest" in normalized or "collect" in normalized:
        return "source"
    return "job"


def _safe_text(*values: object) -> str:
    parts: list[str] = []
    for value in values:
        sanitized = redact_secrets(value)
        parts.append(sanitized if isinstance(sanitized, str) else str(sanitized))
    return redact_string("".join(parts))


def _status_text(value: object) -> str:
    return value.value if isinstance(value, JobStatus) else str(value)
