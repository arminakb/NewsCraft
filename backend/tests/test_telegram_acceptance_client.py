from __future__ import annotations

import pytest

from app.automations.telegram.acceptance_fixture import (
    AcceptanceFixtureMisconfigured,
    AcceptanceTelegramBotClient,
)
from app.core.config import Settings
from app.publishing.models import Destination
from app.publishing.telegram.routing import TelegramRouteResolver, build_acceptance_bot_client
from app.security.auth import SecurityPrincipal

pytestmark = pytest.mark.anyio


def _principal() -> SecurityPrincipal:
    return SecurityPrincipal("internal_service", "test", frozenset({"destinations:read"}))


def _fixture_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        telegram_acceptance_fixture_path="/acceptance-fixtures/telegram_public_album.html",
    )


def test_acceptance_bot_client_refuses_to_build_without_a_fixture_run():
    """The no-network publish double must never be constructible in a real env.

    Before the fixture double moved out of ``routing`` it had a bare
    ``__init__``, so any caller could instantiate it and report publishes as
    succeeded without touching the Bot API.
    """

    with pytest.raises(AcceptanceFixtureMisconfigured):
        AcceptanceTelegramBotClient(config=Settings(_env_file=None, app_env="test"))

    with pytest.raises(AcceptanceFixtureMisconfigured):
        build_acceptance_bot_client(Settings(_env_file=None, app_env="production"))


async def test_resolver_uses_the_injected_acceptance_client_factory():
    """The env branch is a seam, not a hard-wired class reference."""

    built: list[Settings] = []

    def factory(config: Settings):
        built.append(config)
        return AcceptanceTelegramBotClient(config=config)

    config = _fixture_settings()
    resolver = TelegramRouteResolver(
        key_ring=None,
        principal=_principal(),
        config=config,
        acceptance_client_factory=factory,
    )
    destination = Destination(
        platform="telegram",
        name="Smoke",
        target_ref="@newscraft_smoke",
        secret_ref="encrypted:test",
    )

    async with resolver.client_for_destination(None, destination) as client:
        assert await client.get_me("synthetic-token") == {
            "id": 9001,
            "username": "newscraft_test_bot",
        }

    assert built == [config]


def test_resolver_does_not_take_the_acceptance_branch_for_proxied_destinations():
    resolver = TelegramRouteResolver(
        key_ring=None,
        principal=_principal(),
        config=_fixture_settings(),
    )
    direct = Destination(
        platform="telegram",
        name="Smoke",
        target_ref="@newscraft_smoke",
        secret_ref="encrypted:test",
    )
    assert resolver._uses_acceptance_client(direct) is True

    live = Destination(
        platform="telegram",
        name="Live",
        target_ref="@newscraft_live",
        secret_ref="encrypted:test",
    )
    live.proxy_profile_id = "00000000-0000-0000-0000-000000000001"
    assert resolver._uses_acceptance_client(live) is False

    plain = TelegramRouteResolver(
        key_ring=None,
        principal=_principal(),
        config=Settings(_env_file=None, app_env="test"),
    )
    assert plain._uses_acceptance_client(direct) is False
