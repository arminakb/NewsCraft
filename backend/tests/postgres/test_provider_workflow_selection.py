from __future__ import annotations

import json
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.api.llm_providers as llm_api
from app.core.config import Settings
from app.db.session import get_session
from app.main import app
from tests.postgres.test_automation_definitions import _client


def _encoded(byte: int) -> str:
    import base64

    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


def _provider_api_config() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        secret_key_version="v1",
        secret_master_key=_encoded(2),
        security_internal_scopes="jobs:read,jobs:write,providers:read",
    )


def _research_graph(provider_id, prompt_id=None) -> dict[str, object]:
    generate_prompt_id = prompt_id or uuid4()
    return {
        "schema_version": 1,
        "entry_node_id": "trigger-1",
        "nodes": [
            {
                "id": "trigger-1",
                "type": "manual",
                "config": {"story_revision_id": str(uuid4())},
            },
            {
                "id": "research-1",
                "type": "research",
                "config": {
                    "provider_profile_id": str(provider_id),
                    "query_budget": 3,
                    "page_budget": 10,
                    "time_budget_seconds": 120,
                },
            },
            {
                "id": "generate-1",
                "type": "generate_content_pack",
                "config": {
                    "editorial_profile_id": str(uuid4()),
                    "provider_profile_id": str(provider_id),
                    "prompt_version_ids": [str(generate_prompt_id)],
                    "prompt_checksums": {str(generate_prompt_id): "a" * 64},
                    "platforms": ["telegram"],
                },
            },
            {"id": "draft-1", "type": "save_drafts", "config": {}},
        ],
        "edges": [
            {
                "source_node_id": "trigger-1",
                "source_port": "story",
                "target_node_id": "research-1",
                "target_port": "story",
            },
            {
                "source_node_id": "research-1",
                "source_port": "story",
                "target_node_id": "generate-1",
                "target_port": "story",
            },
            {
                "source_node_id": "generate-1",
                "source_port": "drafts",
                "target_node_id": "draft-1",
                "target_port": "drafts",
            },
        ],
        "output_node_ids": ["draft-1"],
        "metadata": {"layout": {}},
    }


async def _create_provider(db_session: AsyncSession, monkeypatch, name: str) -> dict:
    monkeypatch.setattr(llm_api, "settings", _provider_api_config())

    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/llm-providers",
                json={
                    "name": name,
                    "base_url": "https://llm.unreachable.invalid/v1",
                    "default_model": "vendor/model",
                    "api_key": "settings-created-api-key-canary",
                },
            )
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert response.status_code == 201, response.text
    return response.json()


async def test_node_catalog_labels_provider_field_llm_provider(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with _client(session_factory) as client:
        catalog = await client.get("/automation-node-catalog")
    assert catalog.status_code == 200, catalog.text
    by_type = {item["type"]: item for item in catalog.json()["nodes"]}
    for node_type in ("research", "generate_content_pack"):
        field = by_type[node_type]["config_schema"]["properties"]["provider_profile_id"]
        assert field["title"] == "LLM Provider"
    budgets = by_type["research"]["config_schema"]["properties"]
    assert budgets["query_budget"]["title"] == "Query Budget"
    assert budgets["page_budget"]["title"] == "Page Budget"
    assert budgets["time_budget_seconds"]["title"] == "Time Budget"


async def test_untested_provider_is_selectable_and_savable_but_blocked_before_run(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
):
    provider = await _create_provider(db_session, monkeypatch, "Untested Workflow Provider")

    listed = await _list_providers(db_session)
    entry = next(item for item in listed if item["id"] == provider["id"])
    assert entry["enabled"] is False
    assert entry["generation_capability"] == "unknown"

    async with _client(session_factory) as client:
        created = await client.post(
            "/automations",
            headers={"Idempotency-Key": f"untested-provider-{provider['id']}"},
            json={"name": "Untested provider workflow", "graph": _research_graph(provider["id"])},
        )
        assert created.status_code == 201, created.text
        automation_id = created.json()["id"]

        validation = await client.post(f"/automations/{automation_id}/versions/1/validate")
        assert validation.status_code == 200, validation.text
        findings = validation.json()["findings"]
        assert validation.json()["valid"] is False
        provider_findings = [
            item
            for item in findings
            if item.get("code") == "automation_resource_unavailable"
            and item.get("field_path") == "config.provider_profile_id"
            and item.get("node_id") in {"research-1", "generate-1"}
        ]
        assert {item["node_id"] for item in provider_findings} == {"research-1", "generate-1"}, (
            "unready provider must be reported before a run"
        )

        catalog = await client.post(
            "/automation-resource-catalog",
            json={
                "automation_id": automation_id,
                "resources": [{"kind": "provider", "id": provider["id"]}],
            },
        )
    assert catalog.status_code == 200, catalog.text
    resource = next(item for item in catalog.json()["resources"] if item["id"] == provider["id"])
    assert resource["display_name"] == "Untested Workflow Provider"
    assert resource["state"] in {"not_configured", "disabled"}
    assert resource["state"] != "unavailable"


async def _list_providers(db_session: AsyncSession) -> list[dict]:
    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/llm-providers")
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert response.status_code == 200, response.text
    return response.json()


async def test_failed_connectivity_test_keeps_provider_usable_for_configuration(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
):
    provider = await _create_provider(db_session, monkeypatch, "Failing Test Provider")

    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            tested = await client.post(f"/llm-providers/{provider['id']}/test")
            assert tested.status_code == 503, tested.text

            listed_response = await client.get("/llm-providers")
            assert listed_response.status_code == 200
            entry = next(item for item in listed_response.json() if item["id"] == provider["id"])
            assert entry["health_status"] == "unhealthy"
            assert entry["generation_capability"] == "unavailable"

            enabled = await client.post(f"/llm-providers/{provider['id']}/enable")
            assert enabled.status_code == 409, enabled.text
            assert enabled.json()["detail"]["code"] == "llm_provider_not_ready"

            saved = await client.post(
                "/automations",
                headers={"Idempotency-Key": f"failing-provider-{provider['id']}"},
                json={"name": "Failing provider workflow", "graph": _research_graph(provider["id"])},
            )
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert saved.status_code == 201, saved.text
