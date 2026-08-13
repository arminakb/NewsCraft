from datetime import datetime
from typing import Self

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import SessionDependency
from app.core.redaction import redact_string
from app.jobs.control import AutomationControlService

router = APIRouter()


class AutomationControlOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    global_pause: bool
    dry_run: bool
    pause_reason: str | None
    paused_at: datetime | None
    updated_at: datetime

    @field_validator("pause_reason", mode="before")
    @classmethod
    def redact_pause_reason(cls, value: object) -> str | None:
        return None if value is None else redact_string(str(value))


class AutomationControlPatch(BaseModel):
    global_pause: bool | None = None
    dry_run: bool | None = None
    pause_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one automation control field is required")
        if "global_pause" in self.model_fields_set and self.global_pause is None:
            raise ValueError("global_pause may not be null")
        if "dry_run" in self.model_fields_set and self.dry_run is None:
            raise ValueError("dry_run may not be null")
        return self


@router.get("/automation-control", response_model=AutomationControlOut)
async def get_automation_control(session: AsyncSession = SessionDependency):
    return await AutomationControlService(session).get_control()


@router.patch("/automation-control", response_model=AutomationControlOut)
async def patch_automation_control(
    patch: AutomationControlPatch,
    session: AsyncSession = SessionDependency,
):
    control = await AutomationControlService(session).update_control(**patch.model_dump(exclude_unset=True))
    await session.commit()
    return control
