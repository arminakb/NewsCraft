from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_connected_server_and_client_session

from app.codex_gateway.mcp_server import (
    GatewayRestClient,
    create_mcp_server,
    validate_gateway_base_url,
)


@pytest.mark.asyncio
async def test_mcp_discovers_only_bounded_read_only_tools_and_forwards_bearer():
    credential = "ncg_test_credential"
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/codex-gateway/heartbeat":
            return httpx.Response(200, json={"next_heartbeat_seconds": 30})
        return httpx.Response(200, json={"status": "ready"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GatewayRestClient(
        base_url="http://127.0.0.1:8000",
        credential=credential,
        agent_version="test",
        http_client=http,
    )
    server = create_mcp_server(client)

    async with create_connected_server_and_client_session(server) as session:
        listed = await session.list_tools()
        result = await session.call_tool("newscraft_get_status", {})
    tools = listed.tools
    assert [tool.name for tool in tools] == [
        "newscraft_get_status",
        "newscraft_get_content_settings_summary",
        "newscraft_list_llm_providers",
        "newscraft_get_llm_provider_status",
        "newscraft_list_telegram_destinations",
        "newscraft_get_telegram_destination_status",
        "newscraft_list_automations",
        "newscraft_get_job_status",
    ]
    assert all(tool.annotations.readOnlyHint is True for tool in tools)
    assert all(tool.annotations.destructiveHint is False for tool in tools)
    assert result.isError is False
    assert result.structuredContent == {"status": {"status": "ready"}}
    assert [request.url.path for request in requests] == [
        "/codex-gateway/heartbeat",
        "/codex-gateway/tools/status",
    ]
    assert all(request.headers["Authorization"] == f"Bearer {credential}" for request in requests)


@pytest.mark.asyncio
async def test_mcp_uses_typed_resource_ids_and_returns_safe_scope_error():
    credential = "ncg_do_not_echo_this"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"detail": {"code": "scope_denied"}},
        )

    client = GatewayRestClient(
        base_url="https://newscraft.example",
        credential=credential,
        agent_version="test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    server = create_mcp_server(client)

    with pytest.raises(ToolError) as captured:
        await server.call_tool(
            "newscraft_get_llm_provider_status",
            {"provider_id": str(uuid4())},
        )
    assert "scope_denied" in str(captured.value)
    assert credential not in str(captured.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_gateway_client_heartbeat_uses_server_interval_without_exposing_secret():
    credential = "ncg_heartbeat_secret"
    request_body: dict | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_body
        request_body = json.loads(request.content)
        return httpx.Response(200, json={"next_heartbeat_seconds": 17})

    client = GatewayRestClient(
        base_url="http://localhost:8000",
        credential=credential,
        agent_version="newscraft-mcp/test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await client.heartbeat() == 17
    assert request_body == {"agent_version": "newscraft-mcp/test"}
    await client.aclose()


@pytest.mark.parametrize(
    "value",
    [
        "http://newscraft.example",
        "https://user:pass@newscraft.example",
        "https://newscraft.example?credential=bad",
        "file:///tmp/socket",
    ],
)
def test_gateway_base_url_rejects_credential_leaks_and_remote_plaintext(value):
    with pytest.raises(ValueError):
        validate_gateway_base_url(value)
