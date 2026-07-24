from __future__ import annotations

import base64

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.telegram_destinations as telegram_api
from app.core.config import Settings
from app.db.session import get_session
from app.main import app
from app.publishing.models import Destination, TelegramProxyProfile
from app.security.models import EncryptedSecret


def _encoded(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


def _config() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        secret_key_version="v1",
        secret_master_key=_encoded(7),
        telegram_proxy_allowed_ports="1080,8080",
        security_internal_scopes="jobs:read,jobs:write,providers:read,destinations:read",
    )


async def test_destination_and_proxy_api_store_only_encrypted_credentials(
    db_session: AsyncSession,
    monkeypatch,
):
    monkeypatch.setattr(telegram_api, "settings", _config())
    proxy_response = await _request(
        db_session,
        "POST",
        "/telegram/proxies",
        json={
            "name": "Regional route",
            "proxy_type": "socks5",
            "host": "proxy.example",
            "port": 1080,
            "username": "proxy-user-canary",
            "password": "proxy-password-canary",
        },
    )
    assert proxy_response.status_code == 202, proxy_response.text
    proxy_payload = proxy_response.json()["proxy"]
    assert proxy_payload["credentials_configured"] is True
    assert "proxy-user-canary" not in proxy_response.text
    assert "proxy-password-canary" not in proxy_response.text

    profile = await db_session.get(TelegramProxyProfile, proxy_payload["id"])
    profile.reachability_status = "healthy"
    await db_session.commit()
    enabled_proxy = await _request(
        db_session,
        "POST",
        f"/telegram/proxies/{profile.id}/enable",
    )
    assert enabled_proxy.status_code == 200

    destination_response = await _request(
        db_session,
        "POST",
        "/telegram/destinations",
        json={
            "name": "News channel",
            "target": "https://t.me/News_Channel",
            "bot_token": "123:bot-token-canary",
            "proxy_profile_id": str(profile.id),
        },
    )
    assert destination_response.status_code == 202
    destination_payload = destination_response.json()["destination"]
    assert destination_payload["canonical_target"] == "@news_channel"
    assert destination_payload["connection_route"] == "proxy"
    assert destination_payload["enabled"] is False
    assert "bot-token-canary" not in destination_response.text
    assert "secret_id" not in destination_payload

    destination = await db_session.get(Destination, destination_payload["id"])
    secret = await db_session.get(EncryptedSecret, destination.secret_id)
    assert destination.settings == {}
    assert destination.secret_ref.startswith("encrypted:")
    assert b"bot-token-canary" not in secret.ciphertext


async def test_destination_enable_requires_every_health_stage(
    db_session: AsyncSession,
    monkeypatch,
):
    monkeypatch.setattr(telegram_api, "settings", _config())
    created = await _request(
        db_session,
        "POST",
        "/telegram/destinations",
        json={"name": "News", "target": "@news_channel", "bot_token": "123:bot-token-canary"},
    )
    assert created.status_code == 202, created.text
    destination_id = created.json()["destination"]["id"]
    blocked = await _request(db_session, "POST", f"/telegram/destinations/{destination_id}/enable")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "telegram_destination_not_ready"

    destination = await db_session.get(Destination, destination_id)
    destination.health_status = "healthy"
    destination.proxy_health_status = "direct"
    destination.telegram_health_status = "healthy"
    destination.bot_health_status = "healthy"
    destination.target_health_status = "healthy"
    destination.administrator_status = "administrator"
    await db_session.commit()
    enabled = await _request(db_session, "POST", f"/telegram/destinations/{destination_id}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True


async def _request(session: AsyncSession, method: str, path: str, **kwargs):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    finally:
        app.dependency_overrides.pop(get_session, None)
