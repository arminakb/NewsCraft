from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, Text, and_, case, exists, or_, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.models import AutomationRun, AutomationVersion
from app.automations.models import AutomationDispatch
from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.publishing.models import PublishJob
from app.stories.models import StoryRevision

type HistoryCategory = Literal[
    "automation",
    "collection",
    "research",
    "generation",
    "edit",
    "approval",
    "schedule",
    "publish",
    "retry",
    "pause",
    "cancel",
    "reconcile",
]
type HistorySubjectType = Literal[
    "automation",
    "automation_version",
    "automation_run",
    "automation_node_run",
    "automation_route",
    "story",
    "job",
]

HISTORY_CATEGORIES: tuple[HistoryCategory, ...] = (
    "automation",
    "collection",
    "research",
    "generation",
    "edit",
    "approval",
    "schedule",
    "publish",
    "retry",
    "pause",
    "cancel",
    "reconcile",
)
HISTORY_SUBJECT_TYPES: tuple[HistorySubjectType, ...] = (
    "automation",
    "automation_version",
    "automation_run",
    "automation_node_run",
    "automation_route",
    "story",
    "job",
)

_RECONCILE_EVENT_TYPES = (
    "telegram.publish.reconciled_not_published",
    "telegram.publish.reconciled_published",
)
_RETRY_EVENT_TYPES = (
    "job.lease_expired",
    "job.retried",
    "job.retry_scheduled",
)
_CANCEL_EVENT_TYPES = (
    "job.cancelled",
    "manual_publication.plan.cancelled",
)
_PAUSE_EVENT_TYPES = ("automation.control_updated",)
_SCHEDULE_EVENT_TYPES = (
    "manual_publication.plan.created",
    "schedule.invalid",
    "telegram.publish.scheduled",
)
_RESEARCH_EVENT_TYPES = (
    "research.failed",
    "research.stale_attempt_ignored",
    "research.succeeded",
    "telegram.research.review_required",
)
_GENERATION_EVENT_TYPES = (
    "telegram.generation.completed",
    "telegram.generation.failed",
    "telegram.process.blocked",
    "telegram.process.deferred",
)
_APPROVAL_EVENT_TYPES = (
    "content_pack.revision.approved",
    "content_pack.revision.rejected",
    "telegram.revision.approved",
    "telegram.revision.auto_approved",
    "telegram.revision.rejected",
    "telegram.revision.review_required",
)
_EDIT_EVENT_TYPES = (
    "manual_publication.plan.checklist_updated",
    "story.editorial_state_changed",
    "telegram.revision.edited",
    "telegram.source_edit.revision_created",
)
_PUBLISH_EVENT_TYPES = (
    "manual_publication.plan.published",
    "telegram.publish.blocked",
    "telegram.publish.requested",
    "telegram.publish.succeeded",
    "telegram.revision.publish_requested",
)
_COLLECTION_EVENT_TYPES = (
    "manual_intake.completed",
    "telegram.source.captured",
)
_DOMAIN_JOB_EVENT_TYPES = (
    "job.claimed",
    "job.enqueued",
    "job.failed",
    "job.heartbeat",
    "job.needs_review",
    "job.succeeded",
)
_COLLECTION_JOB_TYPES = (
    "ingest.collect",
    "manual_intake",
    "story.group_pending",
    "telegram.route.backfill",
    "telegram.route.dry_run",
    "telegram.route.initialize",
    "telegram.route.poll",
)
_RESEARCH_JOB_TYPES = ("research_story",)
_GENERATION_JOB_TYPES = (
    "build_export",
    "content_pack.generate",
    "content_pack.generate_telegram",
    "content_pack.regenerate",
    "telegram.route.process",
)
# Destination health checks are publishing readiness in the locked history taxonomy.
_PUBLISH_JOB_TYPES = ("telegram.destination.check", "telegram.proxy.check", "telegram.publish")
_AUTOMATION_JOB_TYPES = ("automation.run.start",)


class HistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    occurred_at: datetime
    category: HistoryCategory
    status: str
    title: str
    summary: str
    job_id: UUID | None
    subject_url: str
    sanitized_metadata: dict[str, object]


class HistoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[HistoryEntry]
    next_cursor: str | None


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def encode_history_cursor(occurred_at: datetime, event_id: UUID) -> str:
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("history cursor timestamp must be timezone-aware")
    encoded = base64.urlsafe_b64encode(_canonical_json({"id": str(event_id), "occurred_at": occurred_at.isoformat()}))
    return encoded.rstrip(b"=").decode("ascii")


def decode_history_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict) or set(value) != {"id", "occurred_at"}:
            raise ValueError
        occurred_at = datetime.fromisoformat(value["occurred_at"])
        event_id = UUID(value["id"])
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError
    except binascii.Error, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError:
        raise ValueError("invalid history cursor") from None
    return occurred_at, event_id


def _event_text(key: str):
    return WorkflowEvent.event_data[key].as_string()


def _job_text(key: str):
    return WorkflowJob.payload[key].as_string()


def _matches_event_or_job_id(column: Any, *keys: str):
    serialized = sql_cast(column, Text)
    return or_(*(serialized == value for key in keys for value in (_event_text(key), _job_text(key))))


def _dispatch_link_criterion():
    return or_(
        _matches_event_or_job_id(AutomationDispatch.id, "dispatch_id"),
        _matches_event_or_job_id(AutomationDispatch.publish_job_id, "publish_job_id"),
        _matches_event_or_job_id(
            AutomationDispatch.variant_revision_id,
            "platform_variant_revision_id",
            "revision_id",
            "variant_revision_id",
        ),
        _matches_event_or_job_id(AutomationDispatch.generation_run_id, "generation_run_id"),
    )


def _route_subject_criterion(route_id: UUID):
    route_text = str(route_id)
    dispatch_link = exists(
        select(1)
        .select_from(AutomationDispatch)
        .where(
            AutomationDispatch.route_id == route_id,
            _dispatch_link_criterion(),
        )
    )
    return or_(
        _event_text("route_id") == route_text,
        _job_text("route_id") == route_text,
        dispatch_link,
    )


def _story_subject_criterion(story_id: UUID):
    story_text = str(story_id)
    story_revision_link = exists(
        select(1)
        .select_from(StoryRevision)
        .where(
            StoryRevision.story_id == story_id,
            _matches_event_or_job_id(
                StoryRevision.id,
                "result_revision_id",
                "revision_id",
                "story_revision_id",
            ),
        )
    )
    dispatch_link = exists(
        select(1)
        .select_from(AutomationDispatch)
        .join(StoryRevision, StoryRevision.id == AutomationDispatch.story_revision_id)
        .where(
            StoryRevision.story_id == story_id,
            _dispatch_link_criterion(),
        )
    )
    platform_revision_link = exists(
        select(1)
        .select_from(PlatformVariantRevision)
        .join(
            PlatformVariant,
            PlatformVariant.id == PlatformVariantRevision.platform_variant_id,
        )
        .join(ContentPack, ContentPack.id == PlatformVariant.content_pack_id)
        .join(StoryRevision, StoryRevision.id == ContentPack.story_revision_id)
        .outerjoin(
            PublishJob,
            PublishJob.platform_variant_revision_id == PlatformVariantRevision.id,
        )
        .where(
            StoryRevision.story_id == story_id,
            or_(
                _matches_event_or_job_id(
                    PlatformVariantRevision.id,
                    "platform_variant_revision_id",
                    "revision_id",
                    "variant_revision_id",
                ),
                _matches_event_or_job_id(
                    PlatformVariant.id,
                    "platform_variant_id",
                    "variant_id",
                ),
                _matches_event_or_job_id(ContentPack.id, "content_pack_id"),
                _matches_event_or_job_id(PublishJob.id, "publish_job_id"),
                PublishJob.workflow_job_id == WorkflowEvent.workflow_job_id,
            ),
        )
    )
    return or_(
        _event_text("story_id") == story_text,
        _job_text("story_id") == story_text,
        story_revision_link,
        dispatch_link,
        platform_revision_link,
    )


def _subject_criterion(subject_type: HistorySubjectType, subject_id: UUID):
    if subject_type == "job":
        return WorkflowEvent.workflow_job_id == subject_id
    if subject_type == "story":
        return _story_subject_criterion(subject_id)
    subject_text = str(subject_id)
    if subject_type == "automation_run":
        return or_(
            WorkflowJob.automation_run_id == subject_id,
            _event_text("automation_run_id") == subject_text,
            _job_text("automation_run_id") == subject_text,
        )
    if subject_type == "automation_node_run":
        return or_(
            WorkflowJob.automation_node_run_id == subject_id,
            _event_text("automation_node_run_id") == subject_text,
            _job_text("automation_node_run_id") == subject_text,
        )
    if subject_type == "automation_version":
        run_link = exists(
            select(1)
            .select_from(AutomationRun)
            .where(
                AutomationRun.id == WorkflowJob.automation_run_id,
                AutomationRun.automation_version_id == subject_id,
            )
        )
        event_link = exists(
            select(1)
            .select_from(AutomationVersion)
            .where(
                AutomationVersion.id == subject_id,
                _event_text("automation_id") == sql_cast(AutomationVersion.automation_id, Text),
                _event_text("version") == sql_cast(AutomationVersion.version, Text),
            )
        )
        return or_(run_link, event_link)
    if subject_type == "automation":
        run_link = exists(
            select(1)
            .select_from(AutomationRun)
            .where(
                AutomationRun.id == WorkflowJob.automation_run_id,
                AutomationRun.automation_id == subject_id,
            )
        )
        return or_(
            _event_text("automation_id") == subject_text,
            _job_text("automation_id") == subject_text,
            run_link,
        )
    return _route_subject_criterion(subject_id)


def _domain_job_event_for(job_types: tuple[str, ...]):
    return and_(
        WorkflowEvent.event_type.in_(_DOMAIN_JOB_EVENT_TYPES),
        WorkflowJob.job_type.in_(job_types),
    )


def _category_expression():
    event_type = WorkflowEvent.event_type
    return case(
        (event_type.in_(_RECONCILE_EVENT_TYPES), "reconcile"),
        (event_type.in_(_RETRY_EVENT_TYPES), "retry"),
        (event_type.in_(_CANCEL_EVENT_TYPES), "cancel"),
        (event_type.in_(_PAUSE_EVENT_TYPES), "pause"),
        (event_type.in_(_SCHEDULE_EVENT_TYPES), "schedule"),
        (event_type.in_(_RESEARCH_EVENT_TYPES), "research"),
        (event_type.in_(_GENERATION_EVENT_TYPES), "generation"),
        (event_type.in_(_APPROVAL_EVENT_TYPES), "approval"),
        (event_type.in_(_EDIT_EVENT_TYPES), "edit"),
        (event_type.in_(_PUBLISH_EVENT_TYPES), "publish"),
        (event_type.in_(_COLLECTION_EVENT_TYPES), "collection"),
        (event_type.like("automation.%"), "automation"),
        (_domain_job_event_for(_COLLECTION_JOB_TYPES), "collection"),
        (_domain_job_event_for(_RESEARCH_JOB_TYPES), "research"),
        (_domain_job_event_for(_GENERATION_JOB_TYPES), "generation"),
        (_domain_job_event_for(_PUBLISH_JOB_TYPES), "publish"),
        (_domain_job_event_for(_AUTOMATION_JOB_TYPES), "automation"),
        else_="unknown",
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _status_criterion(status: str):
    return or_(
        _event_text("status") == status,
        _event_text("new_state") == status,
        WorkflowEvent.event_type.like(f"%.{_escape_like(status)}", escape="\\"),
    )


def history_statement(
    *,
    cursor: tuple[datetime, UUID] | None,
    subject_type: HistorySubjectType | None,
    subject_id: UUID | None,
    category: HistoryCategory | None,
    status: str | None,
    limit: int,
) -> Select:
    statement = select(WorkflowEvent, WorkflowJob).outerjoin(
        WorkflowJob,
        WorkflowJob.id == WorkflowEvent.workflow_job_id,
    )
    if cursor is not None:
        occurred_at, event_id = cursor
        statement = statement.where(
            or_(
                WorkflowEvent.created_at < occurred_at,
                and_(WorkflowEvent.created_at == occurred_at, WorkflowEvent.id < event_id),
            )
        )
    if subject_type is not None and subject_id is not None:
        statement = statement.where(_subject_criterion(subject_type, subject_id))
    category_expression = _category_expression()
    statement = statement.where(
        category_expression == category if category is not None else category_expression.in_(HISTORY_CATEGORIES)
    )
    if status is not None:
        statement = statement.where(_status_criterion(status))
    return statement.order_by(WorkflowEvent.created_at.desc(), WorkflowEvent.id.desc()).limit(limit + 1)


def _category_for(event_type: str, job_type: str | None) -> HistoryCategory | None:
    if event_type in _RECONCILE_EVENT_TYPES:
        return "reconcile"
    if event_type in _RETRY_EVENT_TYPES:
        return "retry"
    if event_type in _CANCEL_EVENT_TYPES:
        return "cancel"
    if event_type in _PAUSE_EVENT_TYPES:
        return "pause"
    if event_type in _SCHEDULE_EVENT_TYPES:
        return "schedule"
    if event_type in _RESEARCH_EVENT_TYPES:
        return "research"
    if event_type in _GENERATION_EVENT_TYPES:
        return "generation"
    if event_type in _APPROVAL_EVENT_TYPES:
        return "approval"
    if event_type in _EDIT_EVENT_TYPES:
        return "edit"
    if event_type in _PUBLISH_EVENT_TYPES:
        return "publish"
    if event_type in _COLLECTION_EVENT_TYPES:
        return "collection"
    if event_type.startswith("automation."):
        return "automation"
    if event_type in _DOMAIN_JOB_EVENT_TYPES and job_type is not None:
        if job_type in _COLLECTION_JOB_TYPES:
            return "collection"
        if job_type in _RESEARCH_JOB_TYPES:
            return "research"
        if job_type in _GENERATION_JOB_TYPES:
            return "generation"
        if job_type in _PUBLISH_JOB_TYPES:
            return "publish"
        if job_type in _AUTOMATION_JOB_TYPES:
            return "automation"
    return None


def _status_for(event_type: str, metadata: dict[str, object]) -> str:
    for key in ("status", "new_state"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return event_type.rsplit(".", 1)[-1]


def _title_for(event_type: str) -> str:
    title = " ".join(event_type.replace(".", " ").replace("_", " ").split())
    return title.capitalize()


def _summary_for(title: str, actor: object, metadata: dict[str, object]) -> str:
    for key in (
        "operator_note",
        "error_message",
        "reason",
        "note",
        "pause_reason",
        "error_code",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:500]
    actor_text = " ".join(str(actor).split())
    return f"{title} · recorded by {actor_text or 'unknown'}"


def _uuid_text(value: object) -> str | None:
    try:
        return str(UUID(str(value)))
    except TypeError, ValueError:
        return None


def _subject_url(
    metadata: dict[str, object],
    job_id: UUID | None,
    category: HistoryCategory,
    automation_run_id: UUID | None = None,
) -> str:
    route_id = _uuid_text(metadata.get("route_id"))
    if route_id is not None:
        return f"/automations/{route_id}"
    story_id = _uuid_text(metadata.get("story_id"))
    if story_id is not None:
        return f"/inbox?story_id={story_id}"
    revision_id = _uuid_text(metadata.get("revision_id") or metadata.get("result_revision_id"))
    if revision_id is not None:
        return f"/review/{revision_id}"
    run_id = _uuid_text(metadata.get("automation_run_id")) or (
        str(automation_run_id) if automation_run_id is not None else None
    )
    automation_id = _uuid_text(metadata.get("automation_id"))
    if run_id is not None:
        suffix = f"&automationId={automation_id}" if automation_id is not None else ""
        return f"/automations/runs?runId={run_id}{suffix}"
    if automation_id is not None:
        return f"/automations/{automation_id}"
    if category == "reconcile":
        return "/"
    if job_id is not None:
        return "/jobs"
    if category in {"schedule", "publish", "reconcile"}:
        return "/calendar"
    return "/diagnostics"


def _entry(event: Any, job: Any | None) -> HistoryEntry | None:
    raw_metadata = event.event_data if isinstance(event.event_data, dict) else {}
    metadata = cast(dict[str, object], redact_event_data(raw_metadata))
    job_id = event.workflow_job_id if isinstance(event.workflow_job_id, UUID) else None
    job_type = job.job_type if job is not None and isinstance(job.job_type, str) else None
    automation_run_id = (
        job.automation_run_id
        if job is not None and isinstance(getattr(job, "automation_run_id", None), UUID)
        else None
    )
    category = _category_for(str(event.event_type), job_type)
    if category is None:
        return None
    title = _title_for(str(event.event_type))
    return HistoryEntry(
        id=str(event.id),
        occurred_at=event.created_at,
        category=category,
        status=_status_for(str(event.event_type), metadata),
        title=title,
        summary=_summary_for(title, event.actor, metadata),
        job_id=job_id,
        subject_url=_subject_url(metadata, job_id, category, automation_run_id),
        sanitized_metadata=metadata,
    )


class HistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        *,
        subject_type: HistorySubjectType | None = None,
        subject_id: UUID | str | None = None,
        category: HistoryCategory | None = None,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> HistoryPage:
        if not 1 <= limit <= 100:
            raise ValueError("history limit must be between 1 and 100")
        if (subject_type is None) != (subject_id is None):
            raise ValueError("subject_type and subject_id must be supplied together")
        if subject_type is not None and subject_type not in HISTORY_SUBJECT_TYPES:
            raise ValueError("unsupported history subject type")
        normalized_subject_id: UUID | None = None
        if subject_id is not None:
            try:
                normalized_subject_id = UUID(str(subject_id))
            except TypeError, ValueError:
                raise ValueError("history subject_id must be a UUID") from None
        if category is not None and category not in HISTORY_CATEGORIES:
            raise ValueError("unsupported history category")
        decoded_cursor = decode_history_cursor(cursor) if cursor is not None else None
        rows = (
            await self.session.execute(
                history_statement(
                    cursor=decoded_cursor,
                    subject_type=subject_type,
                    subject_id=normalized_subject_id,
                    category=category,
                    status=status,
                    limit=limit,
                )
            )
        ).all()
        page = rows[:limit]
        items = [entry for row in page if (entry := _entry(row[0], row[1])) is not None]
        next_cursor = None
        if len(rows) > limit and page:
            last_event = page[-1][0]
            next_cursor = encode_history_cursor(last_event.created_at, last_event.id)
        return HistoryPage(items=items, next_cursor=next_cursor)
