from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

SUPPORTED_PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})
_DEFAULT_PROXY_PORTS = {"http": 80, "https": 443, "socks5": 1080, "socks5h": 1080}
_PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
_HOST_LABEL = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)$")


class ProxyConfigurationError(RuntimeError):
    """A proxy configuration is unsafe or cannot be represented deterministically."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"ProxyConfigurationError(code={self.code!r})"


@dataclass(frozen=True, slots=True, repr=False)
class ProxyEndpoint:
    scheme: str
    host: str = field(repr=False)
    port: int = field(repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    _url: str = field(default="", repr=False)

    @classmethod
    def parse(cls, raw_value: str) -> ProxyEndpoint:
        if any(ord(character) < 32 or ord(character) == 127 for character in raw_value):
            raise ProxyConfigurationError("proxy_url_malformed")
        try:
            parsed = urlsplit(raw_value)
            scheme = parsed.scheme.casefold()
            host = parsed.hostname
            port = parsed.port
        except TypeError, ValueError:
            raise ProxyConfigurationError("proxy_url_malformed") from None
        if not scheme or host is None:
            raise ProxyConfigurationError("proxy_url_malformed")
        if scheme not in SUPPORTED_PROXY_SCHEMES:
            raise ProxyConfigurationError("proxy_scheme_unsupported")
        if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ProxyConfigurationError("proxy_url_malformed")
        if port is None:
            port = _DEFAULT_PROXY_PORTS[scheme]
        if not 1 <= port <= 65_535:
            raise ProxyConfigurationError("proxy_url_malformed")
        try:
            httpx.URL(raw_value)
        except TypeError, ValueError:
            raise ProxyConfigurationError("proxy_url_malformed") from None
        return cls(
            scheme=scheme,
            host=host.casefold().rstrip("."),
            port=port,
            username=unquote(parsed.username) if parsed.username is not None else None,
            password=unquote(parsed.password) if parsed.password is not None else None,
            _url=raw_value,
        )

    def __repr__(self) -> str:
        return f"ProxyEndpoint(scheme={self.scheme!r})"


@dataclass(frozen=True, slots=True, repr=False)
class _BypassRule:
    kind: Literal["all", "ip", "network", "host", "suffix"]
    value: object = field(repr=False)
    port: int | None = field(default=None, repr=False)

    def matches(self, host: str, port: int | None) -> bool:
        if self.port is not None and port != self.port:
            return False
        if self.kind == "all":
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if self.kind == "ip":
            return address == self.value
        if self.kind == "network":
            return address is not None and address in self.value
        normalized = host.casefold().rstrip(".")
        if self.kind == "host":
            return normalized == self.value
        return normalized == self.value or normalized.endswith(f".{self.value}")


@dataclass(frozen=True, slots=True, repr=False)
class OutboundProxyPolicy:
    http: ProxyEndpoint | None = field(default=None, repr=False)
    https: ProxyEndpoint | None = field(default=None, repr=False)
    all: ProxyEndpoint | None = field(default=None, repr=False)
    bypass_rules: tuple[_BypassRule, ...] = field(default=(), repr=False)
    _no_proxy_value: str | None = field(default=None, repr=False)

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> OutboundProxyPolicy:
        source = os.environ if environment is None else environment
        http_value = _paired_environment_value(source, "HTTP_PROXY")
        https_value = _paired_environment_value(source, "HTTPS_PROXY")
        all_value = _paired_environment_value(source, "ALL_PROXY")
        no_proxy_value = _paired_environment_value(source, "NO_PROXY")
        rules = _parse_no_proxy(no_proxy_value)
        return cls(
            http=ProxyEndpoint.parse(http_value) if http_value is not None else None,
            https=ProxyEndpoint.parse(https_value) if https_value is not None else None,
            all=ProxyEndpoint.parse(all_value) if all_value is not None else None,
            bypass_rules=rules,
            _no_proxy_value=no_proxy_value,
        )

    @property
    def mode(self) -> Literal["direct", "proxy"]:
        return "proxy" if self.endpoints else "direct"

    @property
    def endpoints(self) -> tuple[ProxyEndpoint, ...]:
        unique: dict[str, ProxyEndpoint] = {}
        for endpoint in (self.http, self.https, self.all):
            if endpoint is not None:
                unique.setdefault(endpoint._url, endpoint)
        return tuple(unique.values())

    @property
    def bypass_rule_count(self) -> int:
        return len(self.bypass_rules)

    @property
    def diagnostic_scheme(self) -> str | None:
        schemes = {endpoint.scheme for endpoint in self.endpoints}
        if not schemes:
            return None
        return next(iter(schemes)) if len(schemes) == 1 else "mixed"

    def should_bypass(self, target_url: str | httpx.URL) -> bool:
        try:
            parsed = httpx.URL(target_url)
            host = parsed.host
            port = parsed.port
        except TypeError, ValueError:
            return False
        if not host:
            return False
        return any(rule.matches(host, port) for rule in self.bypass_rules)

    def endpoint_for_url(self, target_url: str | httpx.URL) -> ProxyEndpoint | None:
        if self.should_bypass(target_url):
            return None
        try:
            scheme = httpx.URL(target_url).scheme.casefold()
        except TypeError, ValueError:
            return None
        if scheme == "http":
            return self.http or self.all
        if scheme == "https":
            return self.https or self.all
        return self.all

    def explicit_proxy_url(self, target_url: str | httpx.URL) -> str | None:
        endpoint = self.endpoint_for_url(target_url)
        return endpoint._url if endpoint is not None else None

    def canonical_environment(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, endpoint in (("HTTP_PROXY", self.http), ("HTTPS_PROXY", self.https), ("ALL_PROXY", self.all)):
            if endpoint is not None:
                result[name] = endpoint._url
        if self._no_proxy_value is not None:
            result["NO_PROXY"] = self._no_proxy_value
        return result

    def __repr__(self) -> str:
        return (
            "OutboundProxyPolicy("
            f"mode={self.mode!r}, scheme={self.diagnostic_scheme!r}, "
            f"bypass_rule_count={self.bypass_rule_count})"
        )


class ProxyDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["direct", "proxy"]
    scheme: str | None = None
    bypass_rule_count: int = Field(ge=0)
    last_connectivity_status: Literal["not_checked", "ok", "failed"]
    configuration_error_code: str | None = None


@dataclass(slots=True)
class _ConnectivityState:
    status: Literal["not_checked", "ok", "failed"] = "not_checked"


_CONNECTIVITY = _ConnectivityState()


def safe_proxy_diagnostics(environment: Mapping[str, str] | None = None) -> ProxyDiagnostics:
    source = os.environ if environment is None else environment
    configured = _has_nonempty_proxy_value(source)
    try:
        policy = OutboundProxyPolicy.from_environment(source)
    except ProxyConfigurationError as exc:
        return ProxyDiagnostics(
            mode="proxy" if configured else "direct",
            scheme=None,
            bypass_rule_count=0,
            last_connectivity_status=_CONNECTIVITY.status,
            configuration_error_code=exc.code,
        )
    return ProxyDiagnostics(
        mode=policy.mode,
        scheme=policy.diagnostic_scheme,
        bypass_rule_count=policy.bypass_rule_count,
        last_connectivity_status=_CONNECTIVITY.status,
        configuration_error_code=None,
    )


class OutboundProxyTransport(httpx.AsyncBaseTransport):
    """Route requests through explicit direct/proxy pools after policy resolution."""

    def __init__(
        self,
        policy: OutboundProxyPolicy,
        *,
        transport_factory: Callable[..., httpx.AsyncBaseTransport] = httpx.AsyncHTTPTransport,
    ) -> None:
        self.policy = policy
        try:
            self._direct = transport_factory(trust_env=False)
            self._proxy_transports = {
                endpoint._url: transport_factory(proxy=endpoint._url, trust_env=False) for endpoint in policy.endpoints
            }
        except Exception:
            raise ProxyConfigurationError("proxy_client_initialization_failed") from None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        endpoint = self.policy.endpoint_for_url(request.url)
        transport = self._direct if endpoint is None else self._proxy_transports[endpoint._url]
        try:
            response = await transport.handle_async_request(request)
        except BaseException as exc:
            _CONNECTIVITY.status = "failed"
            if endpoint is not None and isinstance(exc, Exception):
                raise httpx.ProxyError("outbound_proxy_connect_failed") from None
            raise
        _CONNECTIVITY.status = "ok"
        return response

    async def aclose(self) -> None:
        transports = (self._direct, *self._proxy_transports.values())
        failure: BaseException | None = None
        for transport in transports:
            try:
                await transport.aclose()
            except BaseException as exc:  # noqa: BLE001 - close every owned pool
                failure = failure or exc
        if failure is not None:
            raise failure

    def __repr__(self) -> str:
        return f"OutboundProxyTransport(policy={self.policy!r})"


def build_outbound_http_client(
    *,
    policy: OutboundProxyPolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    **configuration: Any,
) -> httpx.AsyncClient:
    if "proxy" in configuration or "mounts" in configuration or configuration.get("trust_env") is True:
        raise ProxyConfigurationError("proxy_client_configuration_forbidden")
    configuration.pop("trust_env", None)
    resolved_policy = policy or OutboundProxyPolicy.from_environment()
    selected_transport = transport or OutboundProxyTransport(resolved_policy)
    return httpx.AsyncClient(
        transport=selected_transport,
        trust_env=False,
        **configuration,
    )


def telethon_proxy_from_policy(policy: OutboundProxyPolicy) -> dict[str, object] | None:
    endpoint = _mtproto_endpoint(policy)
    if endpoint is None:
        return None
    if endpoint.scheme == "https":
        raise ProxyConfigurationError("proxy_mtproto_scheme_unsupported")
    return {
        "proxy_type": "socks5" if endpoint.scheme in {"socks5", "socks5h"} else "http",
        "addr": endpoint.host,
        "port": endpoint.port,
        "rdns": endpoint.scheme != "socks5",
        "username": endpoint.username,
        "password": endpoint.password,
    }


def _mtproto_endpoint(policy: OutboundProxyPolicy) -> ProxyEndpoint | None:
    if policy.all is not None:
        return policy.all
    candidates = [endpoint for endpoint in (policy.http, policy.https) if endpoint is not None]
    if not candidates:
        return None
    if len({endpoint._url for endpoint in candidates}) > 1:
        raise ProxyConfigurationError("proxy_mtproto_ambiguous")
    return candidates[0]


def _paired_environment_value(environment: Mapping[str, str], uppercase_name: str) -> str | None:
    upper = _normalized_environment_value(environment.get(uppercase_name))
    lower = _normalized_environment_value(environment.get(uppercase_name.casefold()))
    if upper is not None and lower is not None and upper != lower:
        raise ProxyConfigurationError("proxy_environment_conflict")
    return upper if upper is not None else lower


def _normalized_environment_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _parse_no_proxy(value: str | None) -> tuple[_BypassRule, ...]:
    if value is None:
        return ()
    rules: list[_BypassRule] = []
    for raw_rule in value.split(","):
        normalized = raw_rule.strip()
        if not normalized:
            continue
        rules.append(_parse_bypass_rule(normalized))
    return tuple(rules)


def _parse_bypass_rule(value: str) -> _BypassRule:
    if value == "*":
        return _BypassRule("all", "*")
    if "://" in value or any(character.isspace() for character in value) or "@" in value:
        raise ProxyConfigurationError("no_proxy_rule_invalid")
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError:
        network = None
    if network is not None and "/" in value:
        return _BypassRule("network", network)
    host, port = _split_bypass_host_port(value)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        return _BypassRule("ip", address, port)
    suffix = host.startswith(".")
    normalized_host = host.removeprefix(".").casefold().rstrip(".")
    if not _valid_hostname(normalized_host):
        raise ProxyConfigurationError("no_proxy_rule_invalid")
    return _BypassRule("suffix" if suffix else "host", normalized_host, port)


def _split_bypass_host_port(value: str) -> tuple[str, int | None]:
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            raise ProxyConfigurationError("no_proxy_rule_invalid")
        host = value[1:end]
        remainder = value[end + 1 :]
        if not remainder:
            return host, None
        if not remainder.startswith(":"):
            raise ProxyConfigurationError("no_proxy_rule_invalid")
        return host, _parse_bypass_port(remainder[1:])
    if value.count(":") == 1:
        host, possible_port = value.rsplit(":", 1)
        if possible_port.isdigit():
            return host, _parse_bypass_port(possible_port)
    return value, None


def _parse_bypass_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise ProxyConfigurationError("no_proxy_rule_invalid") from None
    if not 1 <= port <= 65_535:
        raise ProxyConfigurationError("no_proxy_rule_invalid")
    return port


def _valid_hostname(value: str) -> bool:
    if not value or len(value) > 253 or "/" in value:
        return False
    return all(_HOST_LABEL.fullmatch(label) for label in value.split("."))


def _has_nonempty_proxy_value(environment: Mapping[str, str]) -> bool:
    return any(
        _normalized_environment_value(environment.get(name)) is not None
        or _normalized_environment_value(environment.get(name.casefold())) is not None
        for name in _PROXY_VARIABLES[:3]
    )


__all__ = [
    "OutboundProxyPolicy",
    "OutboundProxyTransport",
    "ProxyConfigurationError",
    "ProxyDiagnostics",
    "build_outbound_http_client",
    "safe_proxy_diagnostics",
    "telethon_proxy_from_policy",
]
