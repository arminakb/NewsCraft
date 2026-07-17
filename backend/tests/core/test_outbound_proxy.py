from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.core.outbound_proxy import (
    OutboundProxyPolicy,
    OutboundProxyTransport,
    ProxyConfigurationError,
    build_outbound_http_client,
    safe_proxy_diagnostics,
    telethon_proxy_from_policy,
)


def _policy(**environment: str) -> OutboundProxyPolicy:
    return OutboundProxyPolicy.from_environment(environment)


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "", "NO_PROXY": ""},
        {"HTTP_PROXY": "  ", "HTTPS_PROXY": "\t", "ALL_PROXY": "\n", "NO_PROXY": "  "},
    ],
)
def test_missing_empty_and_whitespace_values_resolve_to_direct(environment):
    policy = OutboundProxyPolicy.from_environment(environment)

    assert policy.mode == "direct"
    assert policy.endpoint_for_url("http://public.example") is None
    assert policy.endpoint_for_url("https://public.example") is None
    assert policy.bypass_rule_count == 0


def test_uppercase_and_lowercase_values_have_deterministic_precedence():
    upper = _policy(HTTPS_PROXY="https://upper.example:8443", ALL_PROXY="socks5://all.example:1080")
    lower = _policy(https_proxy="https://lower.example:8443", all_proxy="socks5://all.example:1080")
    equal = _policy(
        HTTPS_PROXY=" https://same.example:8443 ",
        https_proxy="https://same.example:8443",
    )

    assert upper.endpoint_for_url("https://target.example").host == "upper.example"
    assert upper.endpoint_for_url("http://target.example").host == "all.example"
    assert lower.endpoint_for_url("https://target.example").host == "lower.example"
    assert lower.endpoint_for_url("http://target.example").host == "all.example"
    assert equal.endpoint_for_url("https://target.example").host == "same.example"


@pytest.mark.parametrize(
    ("environment", "code"),
    [
        (
            {"HTTPS_PROXY": "https://one.example:8443", "https_proxy": "https://two.example:8443"},
            "proxy_environment_conflict",
        ),
        ({"HTTPS_PROXY": "not-a-url"}, "proxy_url_malformed"),
        ({"HTTPS_PROXY": "ftp://proxy.example:21"}, "proxy_scheme_unsupported"),
        ({"HTTPS_PROXY": "https://proxy.example:bad"}, "proxy_url_malformed"),
        ({"NO_PROXY": "https://not-a-host-rule.example"}, "no_proxy_rule_invalid"),
        ({"NO_PROXY": "one.example", "no_proxy": "two.example"}, "proxy_environment_conflict"),
    ],
)
def test_invalid_or_conflicting_configuration_fails_with_safe_codes(environment, code):
    with pytest.raises(ProxyConfigurationError) as caught:
        OutboundProxyPolicy.from_environment(environment)

    assert caught.value.code == code
    assert str(caught.value) == code
    assert "example" not in str(caught.value)


@pytest.mark.parametrize("scheme", ["http", "https", "socks5", "socks5h"])
def test_reviewed_proxy_schemes_are_accepted(scheme):
    policy = _policy(ALL_PROXY=f"{scheme}://proxy.example:1080")

    assert policy.mode == "proxy"
    assert policy.endpoint_for_url("https://target.example").scheme == scheme


def test_no_proxy_matches_ip_addresses_hostnames_suffixes_and_cidr():
    policy = _policy(
        ALL_PROXY="socks5://proxy.example:1080",
        NO_PROXY="192.0.2.10,2001:db8::10,exact.example,.suffix.example,198.51.100.0/24,2001:db8:abcd::/48",
    )

    assert policy.should_bypass("https://192.0.2.10")
    assert policy.should_bypass("https://[2001:db8::10]")
    assert policy.should_bypass("https://exact.example")
    assert not policy.should_bypass("https://child.exact.example")
    assert policy.should_bypass("https://suffix.example")
    assert policy.should_bypass("https://child.suffix.example")
    assert policy.should_bypass("https://198.51.100.42")
    assert policy.should_bypass("https://[2001:db8:abcd::42]")
    assert not policy.should_bypass("https://public.example")
    assert policy.bypass_rule_count == 6


def test_wildcard_no_proxy_forces_explicit_direct_routing():
    policy = _policy(ALL_PROXY="http://proxy.example:8080", NO_PROXY="*")

    assert policy.mode == "proxy"
    assert policy.should_bypass("https://anything.example")
    assert policy.endpoint_for_url("https://anything.example") is None


def test_proxy_credentials_and_hosts_never_appear_in_safe_surfaces():
    canaries = ("proxy-user-canary", "proxy-password-canary", "secret-proxy.example")
    environment = {
        "ALL_PROXY": "socks5h://proxy-user-canary:proxy-password-canary@secret-proxy.example:1080",
        "NO_PROXY": "localhost,.internal.example",
    }
    policy = OutboundProxyPolicy.from_environment(environment)
    rendered = "\n".join(
        (
            repr(policy),
            repr(policy.endpoint_for_url("https://public.example")),
            json.dumps(safe_proxy_diagnostics(environment).model_dump(mode="json"), sort_keys=True),
        )
    )

    assert all(canary not in rendered for canary in canaries)
    assert safe_proxy_diagnostics(environment).mode == "proxy"
    assert safe_proxy_diagnostics(environment).scheme == "socks5h"
    assert safe_proxy_diagnostics(environment).bypass_rule_count == 2


def test_safe_diagnostics_reports_only_a_sanitized_configuration_error():
    diagnostics = safe_proxy_diagnostics(
        {"HTTPS_PROXY": "https://user-canary:password-canary@proxy-canary.example:bad"}
    )
    rendered = diagnostics.model_dump_json()

    assert diagnostics.mode == "proxy"
    assert diagnostics.configuration_error_code == "proxy_url_malformed"
    assert diagnostics.last_connectivity_status == "not_checked"
    assert "canary" not in rendered


@pytest.mark.asyncio
async def test_http_client_factory_disables_environment_proxy_inheritance():
    async with build_outbound_http_client(policy=_policy(), timeout=3.0) as client:
        assert client._trust_env is False
        assert client._transport.__class__.__name__ == "OutboundProxyTransport"


def test_http_client_factory_rejects_independent_proxy_interpretation():
    with pytest.raises(ProxyConfigurationError, match="proxy_client_configuration_forbidden"):
        build_outbound_http_client(policy=_policy(), proxy="http://other.example:8080")
    with pytest.raises(ProxyConfigurationError, match="proxy_client_configuration_forbidden"):
        build_outbound_http_client(policy=_policy(), trust_env=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["http", "https", "socks5", "socks5h"])
async def test_locked_httpx_stack_can_initialize_every_claimed_proxy_scheme(scheme):
    client = build_outbound_http_client(
        policy=_policy(ALL_PROXY=f"{scheme}://proxy.example:1080"),
        timeout=3.0,
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_routing_transport_uses_proxy_or_bypass_without_direct_fallback():
    created: list[_RecordingTransport] = []

    def factory(**configuration):
        transport = _RecordingTransport(proxy=configuration.get("proxy"))
        created.append(transport)
        return transport

    policy = _policy(
        ALL_PROXY="http://user-canary:password-canary@proxy-canary.example:8080",
        NO_PROXY="internal.example",
    )
    transport = OutboundProxyTransport(policy, transport_factory=factory)
    direct, proxied = created

    direct_response = await transport.handle_async_request(httpx.Request("GET", "https://internal.example/health"))
    assert direct_response.status_code == 200
    assert direct.requests == ["https://internal.example/health"]
    assert proxied.requests == []

    proxied.failure = httpx.ConnectError("user-canary password-canary proxy-canary.example")
    with pytest.raises(httpx.ProxyError) as caught:
        await transport.handle_async_request(httpx.Request("GET", "https://public.example/feed"))

    assert str(caught.value) == "outbound_proxy_connect_failed"
    assert direct.requests == ["https://internal.example/health"]
    assert proxied.requests == ["https://public.example/feed"]
    assert "canary" not in repr(caught.value)
    await transport.aclose()
    assert direct.closed is True
    assert proxied.closed is True


@pytest.mark.asyncio
async def test_real_socket_proxy_routing_bypass_and_dead_proxy_never_falls_back():
    async with _RecordingHttpServer("origin") as origin, _RecordingHttpServer("proxy") as proxy:
        proxied_policy = _policy(ALL_PROXY=proxy.url)
        async with build_outbound_http_client(policy=proxied_policy, timeout=1.0) as client:
            response = await client.get(f"{origin.url}/through-proxy")

        assert response.text == "proxy"
        assert proxy.requests == [f"GET {origin.url}/through-proxy HTTP/1.1"]
        assert origin.requests == []

        bypass_policy = _policy(ALL_PROXY=proxy.url, NO_PROXY="127.0.0.1")
        async with build_outbound_http_client(policy=bypass_policy, timeout=1.0) as client:
            response = await client.get(f"{origin.url}/bypassed")

        assert response.text == "origin"
        assert origin.requests == ["GET /bypassed HTTP/1.1"]
        assert len(proxy.requests) == 1

        dead_proxy_url = await _unused_loopback_url()
        dead_policy = _policy(ALL_PROXY=dead_proxy_url)
        async with build_outbound_http_client(policy=dead_policy, timeout=0.2) as client:
            with pytest.raises(httpx.ProxyError, match="outbound_proxy_connect_failed"):
                await client.get(f"{origin.url}/must-not-go-direct")

        assert origin.requests == ["GET /bypassed HTTP/1.1"]


def test_telethon_translates_http_and_socks_with_remote_dns_and_credentials():
    http_proxy = telethon_proxy_from_policy(_policy(ALL_PROXY="http://http-user:http-pass@proxy.example:8080"))
    socks_proxy = telethon_proxy_from_policy(_policy(ALL_PROXY="socks5://socks-user:socks-pass@proxy.example:1080"))
    socks_h_proxy = telethon_proxy_from_policy(_policy(ALL_PROXY="socks5h://proxy.example:1080"))

    assert http_proxy == {
        "proxy_type": "http",
        "addr": "proxy.example",
        "port": 8080,
        "rdns": True,
        "username": "http-user",
        "password": "http-pass",
    }
    assert socks_proxy["proxy_type"] == "socks5"
    assert socks_proxy["rdns"] is False
    assert socks_proxy["username"] == "socks-user"
    assert socks_proxy["password"] == "socks-pass"
    assert socks_h_proxy["proxy_type"] == "socks5"
    assert socks_h_proxy["rdns"] is True


def test_telethon_rejects_https_and_ambiguous_scheme_specific_proxy_without_leaking():
    with pytest.raises(ProxyConfigurationError) as unsupported:
        telethon_proxy_from_policy(_policy(ALL_PROXY="https://mt-user:mt-pass@mt-secret.example:8443"))
    with pytest.raises(ProxyConfigurationError) as ambiguous:
        telethon_proxy_from_policy(
            _policy(
                HTTP_PROXY="http://http-proxy.example:8080",
                HTTPS_PROXY="http://https-proxy.example:8080",
            )
        )

    assert unsupported.value.code == "proxy_mtproto_scheme_unsupported"
    assert ambiguous.value.code == "proxy_mtproto_ambiguous"
    rendered = f"{unsupported.value!r} {unsupported.value} {ambiguous.value!r} {ambiguous.value}"
    assert "mt-user" not in rendered
    assert "mt-pass" not in rendered
    assert "mt-secret" not in rendered


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, proxy):
        self.proxy = proxy
        self.requests: list[str] = []
        self.failure: Exception | None = None
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if self.failure is not None:
            raise self.failure
        return httpx.Response(200, request=request)

    async def aclose(self) -> None:
        self.closed = True


class _RecordingHttpServer:
    def __init__(self, response_body: str) -> None:
        self.response_body = response_body.encode()
        self.requests: list[str] = []
        self.server: asyncio.Server | None = None
        self.url = ""

    async def __aenter__(self) -> _RecordingHttpServer:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        assert self.server is not None
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            self.requests.append(request.split(b"\r\n", 1)[0].decode("ascii"))
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                + f"Content-Length: {len(self.response_body)}\r\n".encode()
                + b"Connection: close\r\n\r\n"
                + self.response_body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


async def _unused_loopback_url() -> str:
    server = await asyncio.start_server(lambda _reader, _writer: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return f"http://127.0.0.1:{port}"
