from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "backend/scripts/export_openapi.py"
CONTRACT = ROOT / "contracts/openapi.json"


def _module():
    spec = importlib.util.spec_from_file_location("export_openapi", EXPORTER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_openapi_export_is_deterministic_and_matches_committed_contract() -> None:
    module = _module()
    first = module.render_openapi()
    second = module.render_openapi()

    assert first == second
    assert first == CONTRACT.read_text(encoding="utf-8")
    schema = json.loads(first)
    assert schema["x-newscraft-contract"] == {
        "schema": "newscraft-openapi-v1",
        "source": "backend/app/main.py",
    }
    assert "/operations/diagnostics" in schema["paths"]
    assert "/telegram/reconciliation" in schema["paths"]


def test_public_schema_does_not_expose_credential_values() -> None:
    schema_text = CONTRACT.read_text(encoding="utf-8").casefold()
    forbidden = (
        "openrouter_api_key",
        "telegram_source_editor_api_hash",
        "telegram_source_editor_session",
        "telegram_destination_news_token",
    )
    assert all(name not in schema_text for name in forbidden)


def test_actual_asgi_success_and_validation_error_match_openapi() -> None:
    schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
    client = TestClient(app)

    live = client.get("/health/live")
    invalid = client.get("/stories", params={"limit": 0})

    assert live.status_code == 200
    assert invalid.status_code == 422
    _validate_response(schema, "/health/live", "get", 200, live.json())
    _validate_response(schema, "/stories", "get", 422, invalid.json())


def _validate_response(
    openapi: dict[str, object],
    path: str,
    method: str,
    status: int,
    body: object,
) -> None:
    contract_uri = "urn:newscraft:openapi"
    registry = Registry().with_resource(
        contract_uri,
        Resource.from_contents(openapi, default_specification=DRAFT202012),
    )
    pointer = "/".join(
        part.replace("~", "~0").replace("/", "~1")
        for part in ("paths", path, method, "responses", str(status), "content", "application/json", "schema")
    )
    Draft202012Validator({"$ref": f"{contract_uri}#/{pointer}"}, registry=registry).validate(body)
