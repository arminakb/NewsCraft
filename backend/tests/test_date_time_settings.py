from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import CheckConstraint

from app.api.date_time_settings import DateTimeSettingsInput, router
from app.db.model_registry import Base
from app.db.session import get_session
from app.operator_settings.models import DateTimeSettings

MIGRATION = Path("alembic/versions/0024_date_time_settings.py")


def test_date_time_settings_accepts_iana_timezones_and_rejects_unknown_values():
    for timezone in ("Asia/Tehran", "Europe/London", "America/New_York", "Asia/Tokyo", "UTC"):
        assert DateTimeSettingsInput(timezone=timezone).timezone == timezone

    for timezone in ("Mars/Olympus", "Asia Tehran", " Asia/Tehran", ""):
        with pytest.raises(ValidationError):
            DateTimeSettingsInput(timezone=timezone)


def test_date_time_settings_migration_follows_head_and_seeds_operator_default():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0024_date_time_settings"' in source
    assert 'down_revision = "0023_source_soft_deletion"' in source
    assert '"date_time_settings"' in source
    assert '{"id": "global", "timezone": "Asia/Tehran"}' in source
    assert 'op.drop_table("date_time_settings")' in source


def test_date_time_settings_metadata_is_a_guarded_global_singleton():
    table = Base.metadata.tables["date_time_settings"]

    assert set(table.columns.keys()) == {"id", "timezone", "created_at", "updated_at"}
    assert table.c.id.primary_key is True
    assert str(table.c.id.server_default.arg) == "'global'"
    assert str(table.c.timezone.server_default.arg) == "'Asia/Tehran'"
    assert {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    } >= {
        "ck_date_time_settings_singleton",
        "ck_date_time_settings_timezone_shape",
    }


@pytest.mark.asyncio
async def test_date_time_settings_api_persists_and_reloads_the_selected_timezone():
    session = _Session()
    api = FastAPI()
    api.include_router(router)

    async def override_session():
        yield session

    api.dependency_overrides[get_session] = override_session
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        initial = await client.get("/operator-settings/date-time")
        saved = await client.put(
            "/operator-settings/date-time",
            json={"timezone": "Europe/London"},
        )
        reloaded = await client.get("/operator-settings/date-time")
        invalid = await client.put(
            "/operator-settings/date-time",
            json={"timezone": "Mars/Olympus"},
        )

    assert initial.json() == {"timezone": "Asia/Tehran", "updated_at": None}
    assert saved.json()["timezone"] == "Europe/London"
    assert reloaded.json()["timezone"] == "Europe/London"
    assert invalid.status_code == 422
    assert session.commit_count == 1


class _Session:
    def __init__(self):
        self.row: DateTimeSettings | None = None
        self.commit_count = 0

    async def get(self, model, item_id):
        assert model is DateTimeSettings
        assert item_id == "global"
        return self.row

    async def scalar(self, _statement):
        return self.row

    def add(self, row):
        self.row = row

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _row):
        pass
