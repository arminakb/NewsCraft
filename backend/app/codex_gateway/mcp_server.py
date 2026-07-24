from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

LOGGER = logging.getLogger(__name__)
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_HEARTBEAT_SECONDS = 30


class GatewayClientError(RuntimeError):
    def __init__(
        self,
        code: str,
        status_code: int,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)

    def tool_message(self) -> str:
        return json.dumps(
            {
                "code": self.code,
                "retryable": self.status_code in {429, 502, 503, 504},
                "retry_after_seconds": self.retry_after_seconds,
            },
            separators=(",", ":"),
        )


def validate_gateway_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("NEWSCRAFT_BASE_URL must be a credential-free HTTP(S) origin")
    if parsed.scheme == "http" and parsed.hostname.casefold() not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise ValueError("remote NEWSCRAFT_BASE_URL must use HTTPS")
    return value.rstrip("/")


class GatewayRestClient:
    def __init__(
        self,
        *,
        base_url: str,
        credential: str,
        agent_version: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not credential or credential.strip() != credential:
            raise ValueError("NEWSCRAFT_CODEX_CREDENTIAL is required")
        self.base_url = validate_gateway_base_url(base_url)
        self.credential = credential
        self.agent_version = agent_version
        self.http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(30),
            trust_env=False,
        )

    @classmethod
    def from_environment(cls) -> GatewayRestClient:
        return cls(
            base_url=os.getenv("NEWSCRAFT_BASE_URL", DEFAULT_BASE_URL),
            credential=os.getenv("NEWSCRAFT_CODEX_CREDENTIAL", ""),
            agent_version=os.getenv(
                "NEWSCRAFT_MCP_AGENT_VERSION",
                "newscraft-mcp/0.1",
            ),
        )

    async def heartbeat(self) -> int:
        payload = await self._request(
            "POST",
            "/codex-gateway/heartbeat",
            json={"agent_version": self.agent_version},
        )
        if not isinstance(payload, dict):
            raise GatewayClientError("capability_unavailable", 503)
        value = payload.get("next_heartbeat_seconds", DEFAULT_HEARTBEAT_SECONDS)
        return value if isinstance(value, int) and value > 0 else DEFAULT_HEARTBEAT_SECONDS

    async def heartbeat_loop(self, interval_seconds: int) -> None:
        interval = interval_seconds
        while True:
            await asyncio.sleep(interval)
            try:
                interval = await self.heartbeat()
            except GatewayClientError as exc:
                LOGGER.warning("NewsCraft heartbeat failed: %s", exc.code)
                interval = DEFAULT_HEARTBEAT_SECONDS

    async def get(self, path: str) -> Any:
        return await self._request("GET", path)

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = await self.http.request(
                method,
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {self.credential}"},
                **kwargs,
            )
        except httpx.HTTPError:
            raise GatewayClientError("capability_unavailable", 503) from None
        if response.is_success:
            try:
                return response.json()
            except ValueError:
                raise GatewayClientError("capability_unavailable", 503) from None
        code = "capability_unavailable"
        try:
            body = response.json()
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, dict) and isinstance(detail.get("code"), str):
                code = detail["code"]
        except ValueError:
            pass
        retry_after = response.headers.get("Retry-After")
        raise GatewayClientError(
            code,
            response.status_code,
            retry_after_seconds=(
                int(retry_after)
                if retry_after is not None and retry_after.isdecimal()
                else None
            ),
        )

    async def aclose(self) -> None:
        await self.http.aclose()


async def _tool_call(client: GatewayRestClient, path: str) -> Any:
    try:
        return await client.get(path)
    except GatewayClientError as exc:
        raise ToolError(exc.tool_message()) from None


def create_mcp_server(client: GatewayRestClient) -> FastMCP:
    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[dict[str, object]]:
        try:
            interval = await client.heartbeat()
        except GatewayClientError as exc:
            raise RuntimeError(f"NewsCraft gateway startup failed: {exc.code}") from None
        heartbeat_task = asyncio.create_task(client.heartbeat_loop(interval))
        try:
            yield {}
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            await client.aclose()

    server = FastMCP(
        name="NewsCraft",
        instructions=(
            "Read-only NewsCraft operations. Call status before diagnosing readiness. "
            "Never request or expose provider keys, Telegram tokens, proxy credentials, "
            "pairing credentials, or encryption material. Scope and revocation errors "
            "must be resolved by a NewsCraft operator."
        ),
        lifespan=lifespan,
    )
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        name="newscraft_get_status",
        title="Get NewsCraft status",
        description="Return server-calculated NewsCraft readiness and dependency checks.",
        annotations=read_only,
        structured_output=True,
    )
    async def get_status() -> dict[str, object]:
        return {"status": await _tool_call(client, "/codex-gateway/tools/status")}

    @server.tool(
        name="newscraft_get_content_settings_summary",
        title="Get Content Settings summary",
        description=(
            "Return safe readiness counts for Editorial Profiles, LLM Providers, "
            "Codex Connection, Telegram Destinations, Prompt Governance, automations, and jobs."
        ),
        annotations=read_only,
        structured_output=True,
    )
    async def get_content_settings_summary() -> dict[str, object]:
        return {
            "summary": await _tool_call(
                client,
                "/codex-gateway/tools/content-settings-summary",
            )
        }

    @server.tool(
        name="newscraft_list_llm_providers",
        title="List LLM providers",
        description="List safe LLM provider metadata and generation/research readiness.",
        annotations=read_only,
        structured_output=True,
    )
    async def list_llm_providers() -> dict[str, object]:
        return {
            "providers": await _tool_call(
                client,
                "/codex-gateway/tools/llm-providers",
            )
        }

    @server.tool(
        name="newscraft_get_llm_provider_status",
        title="Get LLM provider status",
        description="Return safe metadata and readiness for one LLM provider ID.",
        annotations=read_only,
        structured_output=True,
    )
    async def get_llm_provider_status(provider_id: UUID) -> dict[str, object]:
        return {
            "provider": await _tool_call(
                client,
                f"/codex-gateway/tools/llm-providers/{provider_id}",
            )
        }

    @server.tool(
        name="newscraft_list_telegram_destinations",
        title="List Telegram destinations",
        description=(
            "List safe Telegram destination metadata, route health, bot identity, "
            "target health, and administrator status."
        ),
        annotations=read_only,
        structured_output=True,
    )
    async def list_telegram_destinations() -> dict[str, object]:
        return {
            "destinations": await _tool_call(
                client,
                "/codex-gateway/tools/telegram-destinations",
            )
        }

    @server.tool(
        name="newscraft_get_telegram_destination_status",
        title="Get Telegram destination status",
        description="Return safe health and verification metadata for one destination ID.",
        annotations=read_only,
        structured_output=True,
    )
    async def get_telegram_destination_status(
        destination_id: UUID,
    ) -> dict[str, object]:
        return {
            "destination": await _tool_call(
                client,
                f"/codex-gateway/tools/telegram-destinations/{destination_id}",
            )
        }

    @server.tool(
        name="newscraft_list_automations",
        title="List automations",
        description="List safe Telegram Automation route state and scheduling metadata.",
        annotations=read_only,
        structured_output=True,
    )
    async def list_automations() -> dict[str, object]:
        return {
            "automations": await _tool_call(
                client,
                "/codex-gateway/tools/automations",
            )
        }

    @server.tool(
        name="newscraft_get_job_status",
        title="Get job status",
        description="Return safe lifecycle and progress metadata for one workflow job ID.",
        annotations=read_only,
        structured_output=True,
    )
    async def get_job_status(job_id: UUID) -> dict[str, object]:
        return {
            "job": await _tool_call(
                client,
                f"/codex-gateway/tools/jobs/{job_id}",
            )
        }

    return server


def main() -> None:
    create_mcp_server(GatewayRestClient.from_environment()).run(transport="stdio")


if __name__ == "__main__":
    main()


__all__ = [
    "GatewayClientError",
    "GatewayRestClient",
    "create_mcp_server",
    "main",
    "validate_gateway_base_url",
]
