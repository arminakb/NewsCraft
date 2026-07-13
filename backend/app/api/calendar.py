from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import redact_secrets
from app.db.session import get_session
from app.manual_publication.calendar import (
    CalendarListOut,
    PublicationListOut,
    decode_publication_cursor,
    list_calendar_events,
    list_publications,
    validate_calendar_window,
    validate_external_url,
)
from app.manual_publication.service import ManualPublicationError, ManualPublicationService

router = APIRouter(tags=["publication-calendar"])
SessionDependency = Depends(get_session)

type ManualPlatform = Literal["instagram", "x", "blog"]
type Platform = Literal["telegram", "instagram", "x", "blog"]

_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _require_aware(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _require_iana(value: str) -> str:
    try:
        ZoneInfo(value)
    except (OSError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise ValueError("display_timezone must be a valid IANA timezone") from None
    return value


class ManualPublicationPlanCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: UUID
    scheduled_for: datetime
    display_timezone: str = Field(default="Asia/Tehran", min_length=1, max_length=255)

    @field_validator("scheduled_for")
    @classmethod
    def require_aware_schedule(cls, value: datetime) -> datetime:
        return _require_aware(value, field="scheduled_for")

    @field_validator("display_timezone")
    @classmethod
    def require_iana_timezone(cls, value: str) -> str:
        return _require_iana(value)


class ManualPublicationChecklistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checklist_state: dict[str, StrictBool] = Field(min_length=1, max_length=100)

    @field_validator("checklist_state")
    @classmethod
    def require_stable_keys(cls, value: dict[str, StrictBool]) -> dict[str, StrictBool]:
        if any(not key or len(key) > 100 for key in value):
            raise ValueError("checklist keys must be non-empty stable IDs")
        return value


class ManualPublicationCompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_url: str | None = Field(default=None, max_length=2048)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("external_url")
    @classmethod
    def require_safe_external_url(cls, value: str | None) -> str | None:
        return validate_external_url(value)


class ManualPublicationPlanOut(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    platform_variant_revision_id: UUID
    platform: ManualPlatform
    scheduled_for: datetime
    display_timezone: str
    status: Literal["planned", "ready", "manual_published", "cancelled"]
    checklist_state: dict[str, StrictBool]
    external_url: str | None
    operator_note: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_validator("scheduled_for", "created_at", "updated_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        return _require_aware(value, field="timestamp")

    @field_validator("completed_at")
    @classmethod
    def require_aware_completion(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_aware(value, field="completed_at")

    @field_validator("display_timezone")
    @classmethod
    def require_iana_timezone(cls, value: str) -> str:
        return _require_iana(value)

    @field_validator("external_url")
    @classmethod
    def require_safe_external_url(cls, value: str | None) -> str | None:
        return validate_external_url(value)


def _domain_http_error(exc: ManualPublicationError) -> HTTPException:
    status_code = getattr(exc, "status_code", 409)
    if status_code not in {404, 409, 422}:
        status_code = 409
    code = str(getattr(exc, "code", "manual_publication_conflict"))
    if _SAFE_ERROR_CODE.fullmatch(code) is None:
        code = "manual_publication_conflict"
    message = redact_secrets(str(exc))
    if not isinstance(message, str) or not message:
        message = "Manual publication request could not be completed"
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@router.get("/calendar", response_model=CalendarListOut)
async def get_calendar(
    start: datetime,
    end: datetime,
    timezone: str = Query(default="Asia/Tehran", min_length=1, max_length=255),
    session: AsyncSession = SessionDependency,
) -> CalendarListOut:
    try:
        validate_calendar_window(start=start, end=end, display_timezone=timezone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    items = await list_calendar_events(
        session,
        start=start,
        end=end,
        display_timezone=timezone,
    )
    return CalendarListOut(items=items, timezone=timezone)


@router.get("/publications", response_model=PublicationListOut)
async def get_publications(
    cursor: str | None = Query(default=None, min_length=1, max_length=1000),
    platform: Platform | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = SessionDependency,
) -> PublicationListOut:
    try:
        if cursor is not None:
            decode_publication_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return PublicationListOut.model_validate(
        await list_publications(
            session,
            cursor=cursor,
            platform=platform,
            limit=limit,
        )
    )


@router.post(
    "/manual-publication-plans",
    response_model=ManualPublicationPlanOut,
    status_code=201,
)
async def create_manual_publication_plan(
    payload: ManualPublicationPlanCreateIn,
    session: AsyncSession = SessionDependency,
) -> ManualPublicationPlanOut:
    try:
        plan = await ManualPublicationService(session).create_plan(
            revision_id=payload.revision_id,
            scheduled_for=payload.scheduled_for,
            display_timezone=payload.display_timezone,
        )
        response = ManualPublicationPlanOut.model_validate(plan)
    except ManualPublicationError as exc:
        raise _domain_http_error(exc) from None
    await session.commit()
    return response


@router.get(
    "/platform-variant-revisions/{revision_id}/manual-publication-plan",
    response_model=ManualPublicationPlanOut,
)
async def get_manual_publication_plan_for_revision(
    revision_id: UUID,
    session: AsyncSession = SessionDependency,
) -> ManualPublicationPlanOut:
    plan = await ManualPublicationService(session).latest_plan_for_revision(revision_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Manual publication plan not found")
    response = ManualPublicationPlanOut.model_validate(plan)
    if response.platform_variant_revision_id != revision_id:
        raise RuntimeError("manual publication plan revision identity mismatch")
    return response


@router.patch(
    "/manual-publication-plans/{plan_id}/checklist",
    response_model=ManualPublicationPlanOut,
)
async def update_manual_publication_checklist(
    plan_id: UUID,
    payload: ManualPublicationChecklistIn,
    session: AsyncSession = SessionDependency,
) -> ManualPublicationPlanOut:
    try:
        plan = await ManualPublicationService(session).update_checklist(
            plan_id=plan_id,
            checklist_state=payload.checklist_state,
        )
        response = ManualPublicationPlanOut.model_validate(plan)
    except ManualPublicationError as exc:
        raise _domain_http_error(exc) from None
    await session.commit()
    return response


@router.post(
    "/manual-publication-plans/{plan_id}/mark-published",
    response_model=ManualPublicationPlanOut,
)
async def mark_manual_publication_published(
    plan_id: UUID,
    payload: ManualPublicationCompleteIn,
    session: AsyncSession = SessionDependency,
) -> ManualPublicationPlanOut:
    try:
        plan = await ManualPublicationService(session).mark_published(
            plan_id=plan_id,
            external_url=payload.external_url,
            note=payload.note,
        )
        response = ManualPublicationPlanOut.model_validate(plan)
    except ManualPublicationError as exc:
        raise _domain_http_error(exc) from None
    await session.commit()
    return response


@router.post(
    "/manual-publication-plans/{plan_id}/cancel",
    response_model=ManualPublicationPlanOut,
)
async def cancel_manual_publication_plan(
    plan_id: UUID,
    session: AsyncSession = SessionDependency,
) -> ManualPublicationPlanOut:
    try:
        plan = await ManualPublicationService(session).cancel(plan_id=plan_id)
        response = ManualPublicationPlanOut.model_validate(plan)
    except ManualPublicationError as exc:
        raise _domain_http_error(exc) from None
    await session.commit()
    return response
