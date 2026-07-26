from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
import idna
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.publishing.models import Destination, TelegramProxyProfile
from app.publishing.telegram.client import TelegramBotClient
from app.security.auth import SecurityPrincipal
from app.security.models import EncryptedSecret
from app.security.secret_store import EncryptedSecretStore, MasterKeyRing, SecretStoreError

_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_NUMERIC_ID = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
_HOST_LABEL = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)$")


class TelegramConfigurationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NormalizedTelegramTarget:
    value: str
    target_type: str


@dataclass(frozen=True, slots=True)
class ValidatedProxyEndpoint:
    host: str
    resolved_ip: str
    port: int


def normalize_telegram_target(raw: str) -> NormalizedTelegramTarget:
    value = raw.strip()
    if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise TelegramConfigurationError("telegram_target_invalid")
    if value.startswith("@"):
        username = value[1:]
        if not _USERNAME.fullmatch(username):
            raise TelegramConfigurationError("telegram_target_invalid")
        return NormalizedTelegramTarget(f"@{username.casefold()}", "username")
    if _NUMERIC_ID.fullmatch(value):
        numeric = int(value)
        if numeric == 0 or not -(2**63) <= numeric < 2**63:
            raise TelegramConfigurationError("telegram_target_invalid")
        return NormalizedTelegramTarget(str(numeric), "numeric_id")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise TelegramConfigurationError("telegram_target_invalid") from None
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() not in {"t.me", "telegram.me"}
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
    ):
        raise TelegramConfigurationError("telegram_target_invalid")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) != 1 or not _USERNAME.fullmatch(segments[0]):
        raise TelegramConfigurationError("telegram_target_invalid")
    return NormalizedTelegramTarget(f"@{segments[0].casefold()}", "username")


def normalize_proxy_host(raw: str) -> str:
    value = raw.strip().rstrip(".")
    if (
        not value
        or "://" in value
        or any(character.isspace() for character in value)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(character in value for character in "/?#@")
    ):
        raise TelegramConfigurationError("telegram_proxy_host_invalid")
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        pass
    try:
        ascii_host = idna.encode(value, uts46=True, std3_rules=True).decode("ascii").casefold()
    except idna.IDNAError:
        raise TelegramConfigurationError("telegram_proxy_host_invalid") from None
    if (
        len(ascii_host) > 253
        or ascii_host == "localhost"
        or any(not _HOST_LABEL.fullmatch(label) for label in ascii_host.split("."))
    ):
        raise TelegramConfigurationError("telegram_proxy_host_invalid")
    return ascii_host


def allowed_proxy_ports(config: Settings = settings) -> frozenset[int]:
    try:
        ports = frozenset(int(value.strip()) for value in config.telegram_proxy_allowed_ports.split(","))
    except ValueError:
        raise TelegramConfigurationError("telegram_proxy_egress_policy_invalid") from None
    if not ports or any(port < 1 or port > 65_535 for port in ports):
        raise TelegramConfigurationError("telegram_proxy_egress_policy_invalid")
    return ports


def _public_address(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise TelegramConfigurationError("telegram_proxy_dns_invalid") from None
    if not address.is_global:
        raise TelegramConfigurationError("telegram_proxy_address_blocked")
    return address.compressed


async def validate_proxy_endpoint(
    host: str,
    port: int,
    *,
    config: Settings = settings,
    resolver: Callable[..., object] | None = None,
) -> ValidatedProxyEndpoint:
    normalized = normalize_proxy_host(host)
    if port not in allowed_proxy_ports(config):
        raise TelegramConfigurationError("telegram_proxy_port_blocked")
    try:
        literal = ipaddress.ip_address(normalized)
    except ValueError:
        literal = None
    if literal is not None:
        return ValidatedProxyEndpoint(normalized, _public_address(literal.compressed), port)
    infos: Any
    try:
        if resolver is None:
            infos = await asyncio.get_running_loop().getaddrinfo(
                normalized,
                port,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        else:
            result = resolver(normalized, port)
            infos = await result if hasattr(result, "__await__") else result
    except OSError, UnicodeError:
        raise TelegramConfigurationError("telegram_proxy_dns_failed") from None
    addresses = sorted({_public_address(item[4][0]) for item in infos})
    if not addresses:
        raise TelegramConfigurationError("telegram_proxy_dns_failed")
    return ValidatedProxyEndpoint(normalized, addresses[0], port)


async def check_proxy_reachability(
    endpoint: ValidatedProxyEndpoint,
    *,
    config: Settings = settings,
) -> None:
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(endpoint.resolved_ip, endpoint.port),
            timeout=config.telegram_proxy_connect_timeout_seconds,
        )
        writer.close()
        await writer.wait_closed()
    except OSError, TimeoutError:
        raise TelegramConfigurationError("telegram_proxy_unreachable") from None


class TelegramRouteResolver:
    def __init__(
        self,
        *,
        key_ring: MasterKeyRing | None,
        principal: SecurityPrincipal,
        config: Settings = settings,
    ) -> None:
        self.key_ring = key_ring
        self.principal = principal
        self.config = config

    def _store(self, session: AsyncSession) -> EncryptedSecretStore:
        if self.key_ring is None:
            raise TelegramConfigurationError("secret_store_unavailable")
        return EncryptedSecretStore(session, self.key_ring)

    async def _secret(self, session: AsyncSession, secret_id) -> str:
        if secret_id is None:
            raise TelegramConfigurationError("telegram_credential_missing")
        record = await session.get(EncryptedSecret, secret_id)
        if record is None:
            raise TelegramConfigurationError("telegram_credential_missing")
        try:
            return self._store(session).decrypt(
                record,
                principal=self.principal,
                required_scope="destinations:read",
            )
        except SecretStoreError:
            raise TelegramConfigurationError("telegram_credential_unavailable") from None

    async def destination_token(self, session: AsyncSession, destination: Destination) -> str:
        return await self._secret(session, destination.secret_id)

    async def proxy_credentials(
        self,
        session: AsyncSession,
        profile: TelegramProxyProfile,
    ) -> tuple[str | None, str | None]:
        if profile.username_secret_id is None and profile.password_secret_id is None:
            return None, None
        if profile.username_secret_id is None or profile.password_secret_id is None:
            raise TelegramConfigurationError("telegram_proxy_credentials_incomplete")
        return (
            await self._secret(session, profile.username_secret_id),
            await self._secret(session, profile.password_secret_id),
        )

    async def proxy_url(self, session: AsyncSession, profile: TelegramProxyProfile) -> str:
        if not profile.enabled:
            raise TelegramConfigurationError("telegram_proxy_disabled")
        endpoint = await validate_proxy_endpoint(profile.host, profile.port, config=self.config)
        username, password = await self.proxy_credentials(session, profile)
        credentials = ""
        if username is not None and password is not None:
            credentials = f"{quote(username, safe='')}:{quote(password, safe='')}@"
        scheme = "http" if profile.proxy_type == "http_connect" else "socks5h"
        address = f"[{endpoint.resolved_ip}]" if ":" in endpoint.resolved_ip else endpoint.resolved_ip
        return f"{scheme}://{credentials}{address}:{endpoint.port}"

    @asynccontextmanager
    async def client_for_destination(
        self,
        session: AsyncSession,
        destination: Destination,
    ) -> AsyncIterator[TelegramBotClient]:
        proxy_url: str | None = None
        if destination.proxy_profile_id is not None:
            profile = await session.get(TelegramProxyProfile, destination.proxy_profile_id)
            if profile is None:
                raise TelegramConfigurationError("telegram_proxy_missing")
            proxy_url = await self.proxy_url(session, profile)
        timeout = httpx.Timeout(
            self.config.telegram_api_read_timeout_seconds,
            connect=self.config.telegram_proxy_connect_timeout_seconds,
        )
        try:
            async with httpx.AsyncClient(
                proxy=proxy_url,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            ) as http:
                yield TelegramBotClient(http)
        except ValueError, ImportError:
            raise TelegramConfigurationError("telegram_proxy_client_initialization_failed") from None


__all__ = [
    "NormalizedTelegramTarget",
    "TelegramConfigurationError",
    "TelegramRouteResolver",
    "ValidatedProxyEndpoint",
    "allowed_proxy_ports",
    "check_proxy_reachability",
    "normalize_proxy_host",
    "normalize_telegram_target",
    "validate_proxy_endpoint",
]
