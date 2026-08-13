from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.api.telegram_destinations import _mark_destination_checking
from app.api.telegram_schemas import TelegramDestinationCreate, TelegramProxyCreate
from app.core.config import Settings
from app.publishing.models import Destination, TelegramProxyProfile
from app.publishing.telegram.client import TelegramBotClient
from app.publishing.telegram.routing import (
    TelegramConfigurationError,
    TelegramRouteResolver,
    ValidatedProxyEndpoint,
    normalize_proxy_host,
    normalize_telegram_target,
    validate_proxy_endpoint,
)
from app.security.auth import SecurityPrincipal


@pytest.mark.parametrize(
    ("raw", "canonical", "target_type"),
    [
        (" @News_Channel ", "@news_channel", "username"),
        ("https://t.me/News_Channel", "@news_channel", "username"),
        ("https://telegram.me/News_Channel/", "@news_channel", "username"),
        ("-1001234567890", "-1001234567890", "numeric_id"),
    ],
)
def test_target_normalization(raw, canonical, target_type):
    result = normalize_telegram_target(raw)
    assert result.value == canonical
    assert result.target_type == target_type


@pytest.mark.parametrize(
    "raw",
    [
        "@bad",
        "+123",
        "0",
        "https://t.me/+invite",
        "https://t.me/channel/12",
        "https://t.me/channel?secret=value",
        "http://t.me/channel",
        "https://example.com/channel",
    ],
)
def test_target_normalization_rejects_unsupported_shapes(raw):
    with pytest.raises(TelegramConfigurationError, match="telegram_target_invalid"):
        normalize_telegram_target(raw)


def test_destination_schema_accepts_write_only_token_and_rejects_removed_permission():
    value = TelegramDestinationCreate.model_validate(
        {"name": "News", "target": "@news_channel", "bot_token": "123:secret-canary"}
    )
    assert value.bot_token.get_secret_value() == "123:secret-canary"
    assert "secret-canary" not in repr(value)
    with pytest.raises(ValidationError):
        TelegramDestinationCreate.model_validate(
            {
                "name": "News",
                "target": "@news_channel",
                "bot_token": "123:secret-canary",
                "allow_auto_publish": True,
            }
        )


def test_proxy_schema_requires_complete_credentials_and_plain_host():
    with pytest.raises(ValidationError, match="supplied together"):
        TelegramProxyCreate(
            name="Proxy",
            proxy_type="socks5",
            host="proxy.example",
            port=1080,
            username="operator",
        )
    with pytest.raises(TelegramConfigurationError, match="telegram_proxy_host_invalid"):
        normalize_proxy_host("http://proxy.example:8080")


async def test_proxy_resolution_blocks_any_private_or_metadata_address():
    async def private_result(_host, port):
        return [(2, 1, 6, "", ("10.0.0.2", port))]

    async def metadata_result(_host, port):
        return [(2, 1, 6, "", ("169.254.169.254", port))]

    config = Settings(_env_file=None, telegram_proxy_allowed_ports="1080")
    for resolver in (private_result, metadata_result):
        with pytest.raises(TelegramConfigurationError, match="telegram_proxy_address_blocked"):
            await validate_proxy_endpoint("proxy.example", 1080, config=config, resolver=resolver)


async def test_proxy_resolution_rejects_if_one_dns_answer_is_private():
    async def mixed_result(_host, port):
        return [
            (2, 1, 6, "", ("93.184.216.34", port)),
            (2, 1, 6, "", ("127.0.0.1", port)),
        ]

    config = Settings(_env_file=None, telegram_proxy_allowed_ports="8080")
    with pytest.raises(TelegramConfigurationError, match="telegram_proxy_address_blocked"):
        await validate_proxy_endpoint("proxy.example", 8080, config=config, resolver=mixed_result)


async def test_route_resolver_builds_http_connect_and_authenticated_socks5_routes(monkeypatch):
    async def validated(host, port, **_kwargs):
        return ValidatedProxyEndpoint(host, "93.184.216.34", port)

    monkeypatch.setattr("app.publishing.telegram.routing.validate_proxy_endpoint", validated)

    class Resolver(TelegramRouteResolver):
        async def proxy_credentials(self, _session, profile):
            return ("user name", "p@ss") if profile.proxy_type == "socks5" else (None, None)

    resolver = Resolver(
        key_ring=None,
        principal=SecurityPrincipal("internal_service", "test", frozenset({"destinations:read"})),
    )
    http_profile = TelegramProxyProfile(
        name="HTTP",
        proxy_type="http_connect",
        host="proxy.example",
        port=8080,
        enabled=True,
    )
    socks_profile = TelegramProxyProfile(
        name="SOCKS",
        proxy_type="socks5",
        host="proxy.example",
        port=1080,
        enabled=True,
    )

    assert await resolver.proxy_url(None, http_profile) == "http://93.184.216.34:8080"
    assert await resolver.proxy_url(None, socks_profile) == ("socks5h://user%20name:p%40ss@93.184.216.34:1080")


async def test_bot_health_calls_validate_identity_target_and_admin_without_leaking_token():
    token = "123:secret-canary"
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        method = request.url.path.rsplit("/", 1)[-1]
        payloads = {
            "getMe": {"ok": True, "result": {"id": 99, "is_bot": True, "username": "news_bot"}},
            "getChat": {
                "ok": True,
                "result": {"id": -1001, "type": "channel", "username": "news", "title": "News"},
            },
            "getChatMember": {"ok": True, "result": {"status": "administrator"}},
        }
        return httpx.Response(200, json=payloads[method])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TelegramBotClient(http)
        bot = await client.get_me(token)
        chat = await client.get_chat("@news", token)
        member = await client.get_chat_member("@news", bot["id"], token)

    assert bot == {"id": 99, "username": "news_bot"}
    assert chat["id"] == -1001
    assert member == {"status": "administrator", "administrator": True}
    assert json.loads(requests[-1].content) == {"chat_id": "@news", "user_id": 99}
    assert token not in repr((bot, chat, member))


async def test_test_environment_route_resolver_uses_no_network_bot_client():
    resolver = TelegramRouteResolver(
        key_ring=None,
        principal=SecurityPrincipal("internal_service", "test", frozenset({"destinations:read"})),
        config=Settings(
            _env_file=None,
            app_env="test",
            telegram_acceptance_fixture_path="/acceptance-fixtures/telegram_public_album.html",
        ),
    )
    destination = Destination(
        platform="telegram",
        name="Smoke",
        target_ref="@newscraft_smoke",
        secret_ref="encrypted:test",
    )

    async with resolver.client_for_destination(None, destination) as client:
        bot = await client.get_me("synthetic-token")
        chat = await client.get_chat(destination.target_ref, "synthetic-token")
        member = await client.get_chat_member(destination.target_ref, bot["id"], "synthetic-token")

    assert bot == {"id": 9001, "username": "newscraft_test_bot"}
    assert chat["username"] == "newscraft_smoke"
    assert member == {"status": "administrator", "administrator": True}


async def test_client_for_destination_does_not_swallow_caller_body_errors():
    """A ValueError from the publish body must not be reclassified as proxy init failure.

    ``client_for_destination`` is an async context manager, so an exception
    raised in the caller's ``async with`` body is thrown back in at the
    ``yield``. Keeping the ``yield`` outside the ValueError/ImportError handler
    is what stops a body error (e.g. a pydantic ``ValidationError``, which
    subclasses ``ValueError``) from becoming a non-retryable
    ``telegram_proxy_client_initialization_failed`` permanent failure.
    """

    resolver = TelegramRouteResolver(
        key_ring=None,
        principal=SecurityPrincipal("internal_service", "test", frozenset({"destinations:read"})),
        config=Settings(_env_file=None, app_env="test"),
    )
    destination = Destination(
        platform="telegram",
        name="Live",
        target_ref="@newscraft_live",
        secret_ref="encrypted:test",
    )

    with pytest.raises(ValueError, match="body failure"):
        async with resolver.client_for_destination(None, destination):
            raise ValueError("body failure")

    with pytest.raises(ImportError, match="body import failure"):
        async with resolver.client_for_destination(None, destination):
            raise ImportError("body import failure")


def _destination(**overrides) -> Destination:
    fields = {
        "platform": "telegram",
        "name": "Live",
        "target_ref": "@newscraft_live",
        "secret_ref": "encrypted:test",
    }
    fields.update(overrides)
    return Destination(**fields)


def test_mark_destination_checking_clears_stale_proxy_verdict():
    """A proxy-less destination reports ``direct``, never a stale proxy verdict.

    Create/patch/rotate used to leave ``proxy_health_status`` untouched when the
    destination had no proxy, so a destination whose proxy was removed kept its
    old ``healthy``/``unhealthy`` value while every other stage said
    ``checking``. The check handler projects ``direct`` for a proxy-less
    destination, so the API now agrees with it up front.
    """

    destination = _destination(
        proxy_profile_id=None,
        proxy_health_status="healthy",
        health_status="healthy",
        failure_code="telegram_bot_unauthorized",
    )

    _mark_destination_checking(destination)

    assert destination.proxy_health_status == "direct"
    assert destination.telegram_health_status == "checking"
    assert destination.bot_health_status == "checking"
    assert destination.target_health_status == "checking"
    assert destination.administrator_status == "checking"
    # Without reset_outcome the aggregate verdict survives: only the explicit
    # recheck route clears it.
    assert destination.health_status == "healthy"
    assert destination.failure_code == "telegram_bot_unauthorized"


def test_mark_destination_checking_with_proxy_and_outcome_reset():
    destination = _destination(
        proxy_profile_id=uuid4(),
        proxy_health_status="healthy",
        health_status="unhealthy",
        failure_code="telegram_target_not_found",
    )

    _mark_destination_checking(destination, reset_outcome=True)

    assert destination.proxy_health_status == "checking"
    assert destination.health_status == "unknown"
    assert destination.failure_code is None
