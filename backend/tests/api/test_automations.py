from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.automations import router
from app.main import app


def test_real_application_registers_phase_two_automation_contract():
    operations = {
        (path, method.upper())
        for path, row in app.openapi()["paths"].items()
        if path.startswith("/automation")
        for method in row
    }

    assert {
        ("/automation-node-catalog", "GET"),
        ("/automation-resource-catalog", "POST"),
        ("/automation-templates", "GET"),
        ("/automation-templates/{template_key}/create", "POST"),
        ("/automations", "GET"),
        ("/automations", "POST"),
        ("/automations/{automation_id}", "GET"),
        ("/automations/{automation_id}", "PATCH"),
        ("/automations/{automation_id}/archive", "POST"),
        ("/automations/{automation_id}/duplicate", "POST"),
        ("/automations/{automation_id}/activate", "POST"),
        ("/automations/{automation_id}/pause", "POST"),
        ("/automations/{automation_id}/resume", "POST"),
        ("/automations/{automation_id}/versions", "GET"),
        ("/automations/{automation_id}/versions", "POST"),
        ("/automations/{automation_id}/versions/{version_number}", "GET"),
        ("/automations/{automation_id}/versions/{version_number}/restore-as-draft", "POST"),
        ("/automations/{automation_id}/versions/{version_number}/validate", "POST"),
        ("/automations/{automation_id}/runs", "POST"),
        ("/automations/{automation_id}/runs", "GET"),
        ("/automation-runs/{run_id}", "GET"),
    }.issubset(operations)


async def test_node_catalog_route_is_strict_and_secret_free():
    api = FastAPI()
    api.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        response = await client.get("/automation-node-catalog")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    assert body["max_nodes"] == 30
    assert body["max_edges"] == 60
    node_types = {item["type"] for item in body["nodes"]}
    assert node_types >= {
        "manual",
        "research",
        "human_review",
        "save_drafts",
        "telegram_publish",
    }
    assert {"telegram_new_item", "generate_telegram"}.isdisjoint(node_types)
    assert next(item["display_name"] for item in body["nodes"] if item["type"] == "research") == "AI Research"
    serialized = response.text.casefold()
    for forbidden in ("api_key", "bot_token", "authorization", "secret_ref", "system_template"):
        assert forbidden not in serialized


def test_mutating_contract_requires_idempotency_and_explicit_revision_tokens():
    schema = app.openapi()
    create_parameters = schema["paths"]["/automations"]["post"]["parameters"]
    version_parameters = schema["paths"]["/automations/{automation_id}/versions"]["post"]["parameters"]
    activation_parameters = schema["paths"]["/automations/{automation_id}/activate"]["post"]["parameters"]
    run_parameters = schema["paths"]["/automations/{automation_id}/runs"]["post"]["parameters"]

    assert any(item["name"] == "Idempotency-Key" and item["required"] for item in create_parameters)
    assert any(item["name"] == "Idempotency-Key" and item["required"] for item in version_parameters)
    assert any(item["name"] == "Idempotency-Key" and item["required"] for item in activation_parameters)
    assert any(item["name"] == "Idempotency-Key" and item["required"] for item in run_parameters)
    patch_schema = schema["components"]["schemas"]["AutomationPatch"]
    assert "expected_revision" in patch_schema["required"]


def test_public_schemas_exclude_credentials_prompt_bodies_and_principal_fields():
    schemas = app.openapi()["components"]["schemas"]
    relevant = {
        name: schema
        for name, schema in schemas.items()
        if name.startswith("Automation") or name.startswith("Workflow") or name.startswith("NodeCatalog")
    }
    serialized = str(relevant).casefold()

    for forbidden in ("api_key", "bot_token", "authorization", "secret_ref", "system_template", "user_template"):
        assert forbidden not in serialized


def test_automation_list_contract_has_bounded_safe_preview_summary():
    schemas = app.openapi()["components"]["schemas"]
    automation = schemas["AutomationOut"]["properties"]
    preview = schemas["AutomationPreviewOut"]
    stage = schemas["AutomationPreviewStageOut"]

    assert automation["preview"]["anyOf"][0]["$ref"].endswith("/AutomationPreviewOut")
    assert preview["properties"]["stages"]["maxItems"] == 30
    assert preview["properties"]["output_platforms"]["maxItems"] == 4
    serialized = str({"preview": preview, "stage": stage}).casefold()
    for forbidden in ("config", "prompt", "credential", "payload", "secret"):
        assert forbidden not in serialized
