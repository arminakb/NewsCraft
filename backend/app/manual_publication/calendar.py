from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.models import PlatformVariant, PlatformVariantRevision
from app.jobs.models import WorkflowJob
from app.jobs.types import JobOrigin, JobType
from app.manual_publication.models import ManualPublicationPlan
from app.publishing.models import Publication, PublishJob

type Platform = Literal["telegram", "instagram", "x", "blog"]
type CalendarKind = Literal["telegram_publish", "manual_publication"]
type PublicationKind = Literal["telegram_publication", "manual_publication"]

MAX_CALENDAR_WINDOW = timedelta(days=93)


def _require_aware(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _safe_application_path(value: str) -> str:
    parsed = urlsplit(value)
    parts = parsed.path.split("/")
    if (
        not value.startswith("/")
        or value.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or "\\" in value
        or any(part in {".", ".."} for part in parts)
    ):
        raise ValueError("action URL must be a safe relative application path")
    return value


def validate_external_url(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or any(character.isspace() or character == "\x00" for character in value):
        raise ValueError("external URL must be safe HTTP without userinfo")
    try:
        parsed = urlsplit(value)
        invalid_port = parsed.port is None and ":" in parsed.netloc.split("@")[-1]
    except ValueError:
        invalid_port = True
        parsed = urlsplit("")
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or invalid_port
    ):
        raise ValueError("external URL must be safe HTTP without userinfo")
    return value


class CalendarEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    kind: CalendarKind
    platform: Platform
    revision_id: UUID
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    status: str = Field(min_length=1, max_length=64)
    action_url: str

    @field_validator("starts_at")
    @classmethod
    def require_aware_starts_at(cls, value: datetime) -> datetime:
        return _require_aware(value, field="starts_at")

    @field_validator("action_url")
    @classmethod
    def require_safe_action_url(cls, value: str) -> str:
        return _safe_application_path(value)


class CalendarListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CalendarEvent]
    timezone: str = Field(min_length=1, max_length=255)


class PublicationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: PublicationKind
    platform: Platform
    revision_id: UUID
    occurred_at: datetime
    status: str = Field(min_length=1, max_length=64)
    external_url: str | None
    action_url: str

    @field_validator("occurred_at")
    @classmethod
    def require_aware_occurred_at(cls, value: datetime) -> datetime:
        return _require_aware(value, field="occurred_at")

    @field_validator("external_url")
    @classmethod
    def require_safe_external_url(cls, value: str | None) -> str | None:
        return validate_external_url(value)

    @field_validator("action_url")
    @classmethod
    def require_safe_action_url(cls, value: str) -> str:
        return _safe_application_path(value)


class PublicationListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublicationRecord]
    next_cursor: str | None


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())


def _title_for(platform: Platform, content: Any) -> str:
    mapping = content if isinstance(content, dict) else {}
    candidate: Any = None
    if platform == "blog":
        candidate = mapping.get("title")
    elif platform == "instagram":
        candidate = mapping.get("hook")
    elif platform == "x":
        posts = mapping.get("posts")
        if isinstance(posts, list) and posts and isinstance(posts[0], dict):
            candidate = posts[0].get("text")
    else:
        candidate = mapping.get("body")
    title = _plain_text(candidate) if isinstance(candidate, str) else ""
    if not title:
        title = f"{platform.title()} publication"
    return title if len(title) <= 200 else f"{title[:197]}..."


def _review_action(revision_id: UUID) -> str:
    return f"/review/{revision_id}"


def validate_calendar_window(
    *,
    start: datetime,
    end: datetime,
    display_timezone: str,
) -> tuple[datetime, datetime, ZoneInfo]:
    start = _require_aware(start, field="start").astimezone(UTC)
    end = _require_aware(end, field="end").astimezone(UTC)
    if end <= start:
        raise ValueError("calendar end must be after start")
    if end - start > MAX_CALENDAR_WINDOW:
        raise ValueError("calendar window cannot exceed 93 days")
    try:
        timezone = ZoneInfo(display_timezone)
    except (OSError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise ValueError("timezone must be a valid IANA timezone") from None
    return start, end, timezone


async def list_calendar_events(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    display_timezone: str,
) -> list[CalendarEvent]:
    start_utc, end_utc, timezone = validate_calendar_window(
        start=start,
        end=end,
        display_timezone=display_timezone,
    )
    manual_rows = (
        await session.execute(
            select(ManualPublicationPlan, PlatformVariantRevision)
            .join(
                PlatformVariantRevision,
                PlatformVariantRevision.id
                == ManualPublicationPlan.platform_variant_revision_id,
            )
            .where(
                ManualPublicationPlan.scheduled_for >= start_utc,
                ManualPublicationPlan.scheduled_for < end_utc,
            )
            .order_by(
                ManualPublicationPlan.scheduled_for,
                ManualPublicationPlan.id,
            )
        )
    ).all()
    telegram_rows = (
        await session.execute(
            select(PublishJob, WorkflowJob, PlatformVariantRevision)
            .join(WorkflowJob, WorkflowJob.id == PublishJob.workflow_job_id)
            .join(
                PlatformVariantRevision,
                PlatformVariantRevision.id == PublishJob.platform_variant_revision_id,
            )
            .join(
                PlatformVariant,
                PlatformVariant.id == PlatformVariantRevision.platform_variant_id,
            )
            .where(
                PublishJob.scheduled_for >= start_utc,
                PublishJob.scheduled_for < end_utc,
                WorkflowJob.origin == JobOrigin.MANUAL.value,
                WorkflowJob.job_type == JobType.TELEGRAM_PUBLISH.value,
                PlatformVariant.platform == "telegram",
            )
            .order_by(PublishJob.scheduled_for, PublishJob.id)
        )
    ).all()

    events = [
        CalendarEvent(
            id=f"manual:{plan.id}",
            kind="manual_publication",
            platform=plan.platform,
            revision_id=plan.platform_variant_revision_id,
            title=_title_for(plan.platform, revision.content),
            starts_at=_require_aware(plan.scheduled_for, field="scheduled_for").astimezone(
                timezone
            ),
            status=plan.status,
            action_url=_review_action(plan.platform_variant_revision_id),
        )
        for plan, revision in manual_rows
    ]
    for publish_job, workflow_job, revision in telegram_rows:
        if (
            workflow_job.origin != JobOrigin.MANUAL.value
            or workflow_job.job_type != JobType.TELEGRAM_PUBLISH.value
        ):
            continue
        events.append(
            CalendarEvent(
                id=f"telegram:{publish_job.id}",
                kind="telegram_publish",
                platform="telegram",
                revision_id=publish_job.platform_variant_revision_id,
                title=_title_for("telegram", revision.content),
                starts_at=_require_aware(
                    publish_job.scheduled_for,
                    field="scheduled_for",
                ).astimezone(timezone),
                status=publish_job.status,
                action_url=_review_action(publish_job.platform_variant_revision_id),
            )
        )
    return sorted(
        events,
        key=lambda item: (item.starts_at.astimezone(UTC), item.kind, item.id),
    )


def _canonical_json(value: dict[str, str]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def encode_publication_cursor(
    occurred_at: datetime,
    kind: PublicationKind,
    record_id: UUID,
) -> str:
    occurred_at = _require_aware(occurred_at, field="occurred_at").astimezone(UTC)
    value = {
        "id": str(record_id),
        "kind": kind,
        "occurred_at": occurred_at.isoformat(),
    }
    return base64.urlsafe_b64encode(_canonical_json(value)).rstrip(b"=").decode("ascii")


def decode_publication_cursor(cursor: str) -> tuple[datetime, PublicationKind, UUID]:
    try:
        if not cursor:
            raise ValueError
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"id", "kind", "occurred_at"}:
            raise ValueError
        kind = value["kind"]
        if kind not in {"telegram_publication", "manual_publication"}:
            raise ValueError
        occurred_at = datetime.fromisoformat(value["occurred_at"])
        occurred_at = _require_aware(occurred_at, field="occurred_at").astimezone(UTC)
        record_id = UUID(value["id"])
    except (
        binascii.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ):
        raise ValueError("invalid publication cursor") from None
    return occurred_at, kind, record_id


def _cursor_sql_condition(
    timestamp_column: Any,
    id_column: Any,
    *,
    kind: PublicationKind,
    cursor: tuple[datetime, PublicationKind, UUID] | None,
):
    if cursor is None:
        return true()
    occurred_at, cursor_kind, record_id = cursor
    if kind < cursor_kind:
        equal_time_condition = true()
    elif kind > cursor_kind:
        equal_time_condition = false()
    else:
        equal_time_condition = id_column < record_id
    return or_(
        timestamp_column < occurred_at,
        and_(timestamp_column == occurred_at, equal_time_condition),
    )


def _is_before_cursor(
    item: PublicationRecord,
    cursor: tuple[datetime, PublicationKind, UUID] | None,
) -> bool:
    if cursor is None:
        return True
    occurred_at, kind, record_id = cursor
    return (
        item.occurred_at.astimezone(UTC),
        item.kind,
        str(item.id),
    ) < (occurred_at, kind, str(record_id))


async def list_publications(
    session: AsyncSession,
    *,
    cursor: str | None,
    platform: Platform | None,
    limit: int,
) -> PublicationListOut:
    if limit < 1 or limit > 100:
        raise ValueError("publication limit must be between 1 and 100")
    cursor_value = decode_publication_cursor(cursor) if cursor is not None else None
    fetch_limit = limit + 1
    records: list[PublicationRecord] = []

    if platform in {None, "telegram"}:
        telegram_rows = (
            await session.execute(
                select(Publication, PlatformVariantRevision)
                .join(
                    PlatformVariantRevision,
                    PlatformVariantRevision.id
                    == Publication.platform_variant_revision_id,
                )
                .where(
                    Publication.reconciliation_status == "confirmed",
                    _cursor_sql_condition(
                        Publication.published_at,
                        Publication.id,
                        kind="telegram_publication",
                        cursor=cursor_value,
                    ),
                )
                .order_by(Publication.published_at.desc(), Publication.id.desc())
                .limit(fetch_limit)
            )
        ).all()
        for publication, _revision in telegram_rows:
            if publication.reconciliation_status != "confirmed":
                continue
            try:
                external_url = validate_external_url(publication.permalink)
            except ValueError:
                external_url = None
            records.append(
                PublicationRecord(
                    id=publication.id,
                    kind="telegram_publication",
                    platform="telegram",
                    revision_id=publication.platform_variant_revision_id,
                    occurred_at=publication.published_at,
                    status=publication.reconciliation_status,
                    external_url=external_url,
                    action_url=_review_action(publication.platform_variant_revision_id),
                )
            )

    if platform is None or platform in {"instagram", "x", "blog"}:
        manual_conditions = [
            ManualPublicationPlan.status == "manual_published",
            ManualPublicationPlan.completed_at.is_not(None),
            _cursor_sql_condition(
                ManualPublicationPlan.completed_at,
                ManualPublicationPlan.id,
                kind="manual_publication",
                cursor=cursor_value,
            ),
        ]
        if platform is not None:
            manual_conditions.append(ManualPublicationPlan.platform == platform)
        manual_rows = (
            await session.execute(
                select(ManualPublicationPlan, PlatformVariantRevision)
                .join(
                    PlatformVariantRevision,
                    PlatformVariantRevision.id
                    == ManualPublicationPlan.platform_variant_revision_id,
                )
                .where(*manual_conditions)
                .order_by(
                    ManualPublicationPlan.completed_at.desc(),
                    ManualPublicationPlan.id.desc(),
                )
                .limit(fetch_limit)
            )
        ).all()
        for plan, _revision in manual_rows:
            if plan.status != "manual_published" or plan.completed_at is None:
                continue
            try:
                external_url = validate_external_url(plan.external_url)
            except ValueError:
                external_url = None
            if external_url is None:
                raise ValueError("manual publication evidence URL is missing or invalid")
            records.append(
                PublicationRecord(
                    id=plan.id,
                    kind="manual_publication",
                    platform=plan.platform,
                    revision_id=plan.platform_variant_revision_id,
                    occurred_at=plan.completed_at,
                    status=plan.status,
                    external_url=external_url,
                    action_url=_review_action(plan.platform_variant_revision_id),
                )
            )

    records = [item for item in records if _is_before_cursor(item, cursor_value)]
    records.sort(
        key=lambda item: (
            item.occurred_at.astimezone(UTC),
            item.kind,
            str(item.id),
        ),
        reverse=True,
    )
    has_more = len(records) > limit
    page = records[:limit]
    next_cursor = (
        encode_publication_cursor(page[-1].occurred_at, page[-1].kind, page[-1].id)
        if has_more and page
        else None
    )
    return PublicationListOut(items=page, next_cursor=next_cursor)
