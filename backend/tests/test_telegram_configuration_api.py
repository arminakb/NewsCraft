from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.api.telegram_schemas import TelegramSourceCreate
from app.api.telegram_sources import create_telegram_source
from app.automations.models import TelegramSourceConfig
from app.db.models import Source
from tests.capability_fakes import AVAILABLE_CAPABILITIES


def test_public_source_rejects_every_mtproto_reference():
    for field in ("api_id_secret_ref", "api_hash_secret_ref", "session_secret_ref"):
        with pytest.raises(ValidationError, match="public_html"):
            TelegramSourceCreate.model_validate(
                {
                    "name": "Public",
                    "channel_ref": "public_channel",
                    field: "TELEGRAM_SECRET_REF",
                }
            )


def test_mtproto_source_requires_three_uppercase_secret_references():
    with pytest.raises(ValidationError, match="requires"):
        TelegramSourceCreate.model_validate(
            {
                "name": "Private",
                "channel_ref": "private_channel",
                "access_mode": "mtproto_user",
                "api_id_secret_ref": "TELEGRAM_API_ID",
            }
        )
    with pytest.raises(ValidationError):
        TelegramSourceCreate.model_validate(
            {
                "name": "Private",
                "channel_ref": "private_channel",
                "access_mode": "mtproto_user",
                "api_id_secret_ref": "telegram-api-id",
                "api_hash_secret_ref": "TELEGRAM_API_HASH",
                "session_secret_ref": "TELEGRAM_SESSION",
            }
        )


async def test_source_create_persists_transport_config_but_returns_no_secret_references():
    session = MemorySession()
    body = TelegramSourceCreate.model_validate(
        {
            "name": "Private source",
            "channel_ref": "private_channel",
            "access_mode": "mtproto_user",
            "api_id_secret_ref": "TELEGRAM_EDITOR_API_ID",
            "api_hash_secret_ref": "TELEGRAM_EDITOR_API_HASH",
            "session_secret_ref": "TELEGRAM_EDITOR_SESSION",
        }
    )

    result = await create_telegram_source(body, session, AVAILABLE_CAPABILITIES)

    source = session.one(Source)
    config = session.one(TelegramSourceConfig)
    assert source.platform == "telegram_public"
    assert config.source_id == source.id
    assert config.access_mode == "mtproto_user"
    assert config.session_secret_ref == "TELEGRAM_EDITOR_SESSION"
    assert result.capability_state.status == "available"
    assert "secret" not in str(result).lower()


async def test_conflicting_duplicate_source_creates_return_409():
    source_session = MemorySession()
    public = TelegramSourceCreate(name="Public", channel_ref="public_channel")
    first_source = await create_telegram_source(public, source_session, AVAILABLE_CAPABILITIES)
    same_source = await create_telegram_source(public, source_session, AVAILABLE_CAPABILITIES)
    assert same_source.id == first_source.id
    with pytest.raises(HTTPException) as source_conflict:
        await create_telegram_source(
            TelegramSourceCreate(name="Conflicting name", channel_ref="public_channel"),
            source_session,
            AVAILABLE_CAPABILITIES,
        )
    assert source_conflict.value.status_code == 409
    assert source_session.nested_count == 1


async def test_source_savepoint_race_reuses_matching_winner_and_rejects_conflict():
    winner = Source(
        id=uuid4(),
        platform="telegram_public",
        name="Public",
        telegram_username="public_channel",
        source_group="telegram",
        language_hint="fa",
    )
    winner_config = TelegramSourceConfig(
        source_id=winner.id,
        access_mode="public_html",
        channel_ref="public_channel",
    )
    body = TelegramSourceCreate(name="Public", channel_ref="public_channel")

    matching = SavepointRaceSession(winner, related=winner_config)
    reused = await create_telegram_source(body, matching, AVAILABLE_CAPABILITIES)
    assert reused.id == winner.id
    assert matching.integrity_errors == 1

    conflicting = SavepointRaceSession(winner, related=winner_config)
    with pytest.raises(HTTPException) as error:
        await create_telegram_source(
            TelegramSourceCreate(name="Different", channel_ref="public_channel"),
            conflicting,
            AVAILABLE_CAPABILITIES,
        )
    assert error.value.status_code == 409
    assert conflicting.integrity_errors == 1


class MemorySession:
    def __init__(self):
        self.values = []
        self.nested_count = 0

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        self.values.append(value)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        return next((value for value in self.values if isinstance(value, entity)), None)

    async def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        return [value for value in self.values if isinstance(value, entity)]

    async def get(self, model, identifier):
        return next(
            (
                value
                for value in self.values
                if isinstance(value, model)
                and (getattr(value, "id", None) == identifier or getattr(value, "source_id", None) == identifier)
            ),
            None,
        )

    def one(self, model):
        return next(value for value in self.values if isinstance(value, model))

    def begin_nested(self):
        self.nested_count += 1
        return AsyncNullContext()


class AsyncNullContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class SavepointRaceSession:
    def __init__(self, winner, *, related=None):
        self.winner = winner
        self.related = related
        self.race_exposed = False
        self.integrity_errors = 0

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if not self.race_exposed:
            return None
        return self.winner if isinstance(self.winner, entity) else None

    async def get(self, model, identifier):
        if self.race_exposed and self.related is not None and isinstance(self.related, model):
            return self.related
        return None

    def begin_nested(self):
        return AsyncNullContext()

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = uuid4()

    async def flush(self):
        if not self.race_exposed:
            self.race_exposed = True
            self.integrity_errors += 1
            raise IntegrityError("forced nested race", {}, RuntimeError("winner committed"))

    async def commit(self):
        return None
