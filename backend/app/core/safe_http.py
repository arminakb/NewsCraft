from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
import idna

MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

type Resolver = Callable[[str], Awaitable[Sequence[str]]]


class SafeHttpError(RuntimeError):
    """A fixed-message failure from the credential-free public HTTP boundary."""


async def _resolve_public_addresses(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    answers = await loop.getaddrinfo(
        host,
        None,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    return list(dict.fromkeys(str(answer[4][0]) for answer in answers))


def _normalized_host(value: str) -> str:
    candidate = value.rstrip(".")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pass
    try:
        return idna.encode(candidate, uts46=True).decode("ascii").lower()
    except idna.IDNAError as exc:
        raise SafeHttpError("Manual URL request rejected") from exc


class _PinnedAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, backend: httpcore.AsyncNetworkBackend) -> None:
        self._backend = backend
        self._addresses: dict[str, tuple[str, ...]] = {}

    def pin(self, host: str, addresses: Sequence[str]) -> None:
        self._addresses[_normalized_host(host)] = tuple(addresses)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = self._addresses.get(_normalized_host(host), ())
        if not addresses:
            raise httpcore.ConnectError("Manual URL request rejected")

        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._backend.connect_tcp(
                    host=address,
                    port=port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise httpcore.ConnectError("Manual URL request rejected") from last_error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Manual URL request rejected")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _HttpcoreResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: AsyncIterator[bytes]) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._stream:
            yield chunk

    async def aclose(self) -> None:
        if hasattr(self._stream, "aclose"):
            await self._stream.aclose()


class _PinnedAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, network_backend: _PinnedAsyncNetworkBackend) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpcore.default_ssl_context(),
            network_backend=network_backend,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = await self._pool.handle_async_request(core_request)
        except Exception as exc:
            raise SafeHttpError("Manual URL request failed") from exc
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_HttpcoreResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


class SafeHttpClient:
    network_policy = "direct_pinned_ssrf"

    def __init__(
        self,
        *,
        timeout: float = 30,
        resolver: Resolver = _resolve_public_addresses,
        transport: httpx.AsyncBaseTransport | None = None,
        network_backend: httpcore.AsyncNetworkBackend | None = None,
        max_redirects: int = MAX_REDIRECTS,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        self._resolver = resolver
        self._max_redirects = max_redirects
        self._max_response_bytes = max_response_bytes
        if transport is not None and network_backend is not None:
            raise ValueError("transport and network_backend are mutually exclusive")
        self._pinned_backend = _PinnedAsyncNetworkBackend(
            network_backend or httpcore.AnyIOBackend()
        )
        effective_transport = transport or _PinnedAsyncTransport(self._pinned_backend)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            proxy=None,
            trust_env=False,
            transport=effective_transport,
        )

    async def __aenter__(self) -> SafeHttpClient:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.__aexit__(*args)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._request("POST", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        follow_redirects = bool(kwargs.pop("follow_redirects", False))
        current_url = str(url)
        current_method = method
        for redirect_count in range(self._max_redirects + 1):
            current_url = await self.validate_public_url(current_url)
            response = await self._send_bounded(current_method, current_url, **kwargs)
            if not follow_redirects or not response.is_redirect:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            if redirect_count == self._max_redirects:
                raise SafeHttpError("Too many manual URL redirects")
            current_url = urljoin(str(response.url), location)
            if response.status_code == 303 or (
                response.status_code in {301, 302} and current_method == "POST"
            ):
                current_method = "GET"
                kwargs.pop("content", None)
                kwargs.pop("data", None)
                kwargs.pop("json", None)
        raise SafeHttpError("Too many manual URL redirects")

    async def validate_public_url(self, value: str) -> str:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"}:
                raise ValueError
            if parsed.username is not None or parsed.password is not None:
                raise ValueError
            if not parsed.hostname:
                raise ValueError
            host = _normalized_host(parsed.hostname)
            if host == "localhost" or host.endswith(".localhost"):
                raise ValueError
        except ValueError as exc:
            raise SafeHttpError("Manual URL request rejected") from exc

        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            try:
                answers = await self._resolver(host)
            except (OSError, socket.gaierror) as exc:
                raise SafeHttpError("Manual URL request rejected") from exc
            if not answers:
                raise SafeHttpError("Manual URL request rejected") from None
            try:
                addresses = [ipaddress.ip_address(answer) for answer in answers]
            except ValueError as exc:
                raise SafeHttpError("Manual URL request rejected") from exc
        else:
            addresses = [literal]
        if not all(address.is_global for address in addresses):
            raise SafeHttpError("Manual URL request rejected")
        self._pinned_backend.pin(host, tuple(str(address) for address in addresses))
        return str(httpx.URL(value).copy_with(host=host))

    async def _send_bounded(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async with self._client.stream(
            method,
            url,
            follow_redirects=False,
            **kwargs,
        ) as response:
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except ValueError as exc:
                    raise SafeHttpError("Manual URL response is too large") from exc
                if declared_length > self._max_response_bytes:
                    raise SafeHttpError("Manual URL response is too large")

            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > self._max_response_bytes:
                    raise SafeHttpError("Manual URL response is too large")
                body.extend(chunk)
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(body),
                request=response.request,
                extensions=response.extensions,
            )


__all__ = [
    "MAX_REDIRECTS",
    "MAX_RESPONSE_BYTES",
    "SafeHttpClient",
    "SafeHttpError",
]
