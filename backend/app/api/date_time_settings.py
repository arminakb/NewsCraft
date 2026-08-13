from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import SessionDependency
from app.operator_settings.models import (
    DATE_TIME_SETTINGS_ID,
    DEFAULT_OPERATOR_TIMEZONE,
    DateTimeSettings,
)

router = APIRouter(prefix="/operator-settings", tags=["operator-settings"])


def validate_iana_timezone(value: str) -> str:
    if value != value.strip():
        raise ValueError("timezone must not contain leading or trailing whitespace")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return value


class DateTimeSettingsInput(BaseModel):
    timezone: str = Field(min_length=1, max_length=255)

    @field_validator("timezone")
    @classmethod
    def require_iana_timezone(cls, value: str) -> str:
        return validate_iana_timezone(value)


class DateTimeSettingsOut(DateTimeSettingsInput):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime | None = None


@router.get("/date-time", response_model=DateTimeSettingsOut)
async def get_date_time_settings(
    session: AsyncSession = SessionDependency,
) -> DateTimeSettings | DateTimeSettingsOut:
    row = await session.get(DateTimeSettings, DATE_TIME_SETTINGS_ID)
    if row is not None:
        return row
    return DateTimeSettingsOut(timezone=DEFAULT_OPERATOR_TIMEZONE)


@router.put("/date-time", response_model=DateTimeSettingsOut)
async def update_date_time_settings(
    body: DateTimeSettingsInput,
    session: AsyncSession = SessionDependency,
) -> DateTimeSettings:
    row = await session.scalar(
        select(DateTimeSettings)
        .where(DateTimeSettings.id == DATE_TIME_SETTINGS_ID)
        .with_for_update()
    )
    if row is None:
        row = DateTimeSettings(id=DATE_TIME_SETTINGS_ID, timezone=body.timezone)
        session.add(row)
    else:
        row.timezone = body.timezone
    await session.commit()
    await session.refresh(row)
    return row
