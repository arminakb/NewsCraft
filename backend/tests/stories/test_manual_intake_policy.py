from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from typing import Any

import httpcore
import httpx
import pytest

from app.stories.manual_intake import (
    MAX_MANUAL_RESPONSE_BYTES,
    ManualIntakeFetchError,
    ManualIntakeHttpClient,
)


class ChunkedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk


class RecordingNetworkStream(httpcore.AsyncNetworkStream):
    def __init__(self, response: bytes, observations: dict[str, list[Any]]) -> None:
        self.response = [response]
        self.observations = observations

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self.response.pop(0) if self.response else b""

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.observations["writes"].append(buffer)

    async def aclose(self) -> None:
        return None

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self.observations["sni"].append(server_hostname)
        return self

    def get_extra_info(self, info: str) -> Any:
        return None


class RecordingNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.observations: dict[str, list[Any]] = {
            "connect_hosts": [],
            "writes": [],
            "sni": [],
        }

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ) -> httpcore.AsyncNetworkStream:
        self.observations["connect_hosts"].append(host)
        response = self.responses.get(host)
        if response is None:
            raise AssertionError(f"unexpected connection target: {host}")
        return RecordingNetworkStream(response, self.observations)

    async def connect_unix_socket(self, path: str, **kwargs) -> httpcore.AsyncNetworkStream:
        raise AssertionError("manual intake must not use Unix sockets")

    async def sleep(self, seconds: float) -> None:
        return None


def resolver(mapping: dict[str, list[str]] | None = None):
    answers = mapping or {}

    async def resolve(host: str) -> list[str]:
        return answers.get(host, ["8.8.8.8"])

    return resolve


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@public.example/report",
        "https://localhost/report",
        "http://127.0.0.1/report",
        "http://10.0.0.1/report",
        "http://169.254.10.20/report",
        "http://192.0.2.1/report",
        "http://[::1]/report",
        "http://[fc00::1]/report",
        "http://[fe80::1]/report",
        "http://[2001:db8::1]/report",
        "ftp://public.example/report",
    ],
)
async def test_manual_client_rejects_non_public_targets_before_transport(url):
    requested: list[str] = []

    async def send(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text="must not be requested")

    async with ManualIntakeHttpClient(
        resolver=resolver(),
        transport=httpx.MockTransport(send),
    ) as client:
        with pytest.raises(ManualIntakeFetchError, match="Manual URL request rejected"):
            await client.get(url)

    assert requested == []


@pytest.mark.asyncio
async def test_manual_client_rejects_dns_name_when_any_answer_is_not_global():
    requested = False

    async def send(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(200, text="must not be requested")

    async with ManualIntakeHttpClient(
        resolver=resolver({"public.example": ["8.8.8.8", "10.0.0.1"]}),
        transport=httpx.MockTransport(send),
    ) as client:
        with pytest.raises(ManualIntakeFetchError):
            await client.get("https://public.example/report")

    assert requested is False


@pytest.mark.asyncio
async def test_manual_client_validates_redirect_target_before_requesting_it():
    requested: list[str] = []

    async def send(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    async with ManualIntakeHttpClient(
        resolver=resolver(),
        transport=httpx.MockTransport(send),
    ) as client:
        with pytest.raises(ManualIntakeFetchError):
            await client.get("https://public.example/report", follow_redirects=True)

    assert requested == ["https://public.example/report"]


@pytest.mark.asyncio
async def test_manual_client_caps_redirect_count():
    requested: list[str] = []

    async def send(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        index = len(requested)
        return httpx.Response(302, headers={"Location": f"https://public.example/{index}"})

    async with ManualIntakeHttpClient(
        resolver=resolver(),
        transport=httpx.MockTransport(send),
        max_redirects=2,
    ) as client:
        with pytest.raises(ManualIntakeFetchError, match="Too many manual URL redirects"):
            await client.get("https://public.example/start", follow_redirects=True)

    assert len(requested) == 3


@pytest.mark.asyncio
async def test_manual_client_rejects_content_length_over_limit_before_reading():
    stream = ChunkedStream([b"must not be read"])

    async def send(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(MAX_MANUAL_RESPONSE_BYTES + 1)},
            stream=stream,
        )

    async with ManualIntakeHttpClient(
        resolver=resolver(),
        transport=httpx.MockTransport(send),
    ) as client:
        with pytest.raises(ManualIntakeFetchError, match="Manual URL response is too large"):
            await client.get("https://public.example/report")


@pytest.mark.asyncio
async def test_manual_client_aborts_stream_when_body_crosses_limit():
    stream = ChunkedStream([b"a" * MAX_MANUAL_RESPONSE_BYTES, b"b"])

    async def send(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with ManualIntakeHttpClient(
        resolver=resolver(),
        transport=httpx.MockTransport(send),
    ) as client:
        with pytest.raises(ManualIntakeFetchError, match="Manual URL response is too large"):
            await client.get("https://public.example/report")


@pytest.mark.asyncio
async def test_manual_client_normalizes_unicode_host_before_resolving():
    resolved: list[str] = []

    async def resolve(host: str) -> list[str]:
        resolved.append(host)
        return ["8.8.8.8"]

    async def send(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="public response")

    async with ManualIntakeHttpClient(
        resolver=resolve,
        transport=httpx.MockTransport(send),
    ) as client:
        response = await client.get("https://bücher.example/report")

    assert response.text == "public response"
    assert resolved == ["xn--bcher-kva.example"]


@pytest.mark.asyncio
async def test_manual_client_preserves_post_interface_for_google_news_decode_requests():
    observed: list[tuple[str, bytes]] = []

    async def send(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, await request.aread()))
        return httpx.Response(200, text='[["decoded"]]')

    async with ManualIntakeHttpClient(
        resolver=resolver({"news.google.com": ["8.8.8.8"]}),
        transport=httpx.MockTransport(send),
    ) as client:
        response = await client.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            content=b"f.req=payload",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.text == '[["decoded"]]'
    assert observed == [("POST", b"f.req=payload")]


@pytest.mark.asyncio
async def test_production_transport_pins_validated_ip_and_preserves_host_and_tls_sni(
    monkeypatch,
):
    dns_answers = iter([["93.184.216.34"], ["127.0.0.1"]])
    resolver_calls: list[str] = []

    async def rebinding_resolver(host: str) -> list[str]:
        resolver_calls.append(host)
        return next(dns_answers)

    backend = RecordingNetworkBackend(
        {
            "93.184.216.34": (
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
            ),
            "127.0.0.1": (
                b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\nConnection: close\r\n\r\nprivate"
            ),
        }
    )
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9999")

    async with ManualIntakeHttpClient(
        resolver=rebinding_resolver,
        network_backend=backend,
    ) as client:
        response = await client.get("https://public.example/report")
        assert client._client._trust_env is False

    request_bytes = b"".join(backend.observations["writes"])
    assert response.text == "ok"
    assert resolver_calls == ["public.example"]
    assert backend.observations["connect_hosts"] == ["93.184.216.34"]
    assert b"Host: public.example" in request_bytes
    assert backend.observations["sni"] == ["public.example"]


@pytest.mark.asyncio
async def test_public_redirect_revalidates_and_pins_each_original_hostname():
    async def resolve(host: str) -> list[str]:
        return {
            "first.example": ["93.184.216.34"],
            "second.example": ["1.1.1.1"],
        }[host]

    backend = RecordingNetworkBackend(
        {
            "93.184.216.34": (
                b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nConnection: close\r\n"
                b"Location: https://second.example/final\r\n\r\n"
            ),
            "1.1.1.1": (
                b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\ndone"
            ),
        }
    )

    async with ManualIntakeHttpClient(
        resolver=resolve,
        network_backend=backend,
    ) as client:
        response = await client.get(
            "https://first.example/start",
            follow_redirects=True,
        )

    request_bytes = b"".join(backend.observations["writes"])
    assert response.text == "done"
    assert backend.observations["connect_hosts"] == ["93.184.216.34", "1.1.1.1"]
    assert backend.observations["sni"] == ["first.example", "second.example"]
    assert b"Host: first.example" in request_bytes
    assert b"Host: second.example" in request_bytes


@pytest.mark.asyncio
async def test_policy_and_httpx_use_same_uts46_idna_hostname():
    resolved: list[str] = []

    async def resolve(host: str) -> list[str]:
        resolved.append(host)
        return ["93.184.216.34"]

    async def send(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    async with ManualIntakeHttpClient(
        resolver=resolve,
        transport=httpx.MockTransport(send),
    ) as client:
        await client.get("https://faß.example/report")

    assert resolved == ["xn--fa-hia.example"]
