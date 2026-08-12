from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.automations.definitions.errors import AutomationDefinitionError
from app.automations.definitions.registry import NODE_REGISTRY, GenerateContentPackConfig, node_catalog
from app.automations.definitions.schemas import WorkflowGraphV1, canonical_graph_json, graph_sha256
from app.automations.definitions.service import _require_saveable
from app.automations.definitions.validation import validate_graph
from app.main import automation_definition_error


def valid_graph() -> dict[str, object]:
    prompt_id = uuid4()
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
                "id": "generate-1",
                "type": "generate_content_pack",
                "config": {
                    "editorial_profile_id": str(uuid4()),
                    "provider_profile_id": str(uuid4()),
                    "prompt_version_ids": [str(prompt_id)],
                    "prompt_checksums": {str(prompt_id): "a" * 64},
                    "platforms": ["telegram"],
                },
            },
            {"id": "draft-1", "type": "save_drafts", "config": {}},
        ],
        "edges": [
            {
                "source_node_id": "trigger-1",
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
        "metadata": {
            "layout": {
                "trigger-1": {"x": 80, "y": 120},
                "generate-1": {"x": 340, "y": 120},
                "draft-1": {"x": 600, "y": 120},
            }
        },
    }


def codes(graph: dict[str, object]) -> set[str]:
    parsed = WorkflowGraphV1.model_validate(graph)
    return {finding.code for finding in validate_graph(parsed).findings}


def test_valid_graph_round_trips_and_hashes_canonically():
    raw = valid_graph()
    graph = WorkflowGraphV1.model_validate(raw)
    reordered = deepcopy(raw)
    reordered["nodes"] = list(reversed(reordered["nodes"]))  # type: ignore[index]
    reordered["edges"] = list(reversed(reordered["edges"]))  # type: ignore[index]

    assert validate_graph(graph).valid is True
    assert graph_sha256(graph) == graph_sha256(WorkflowGraphV1.model_validate(reordered))
    assert canonical_graph_json(graph) == canonical_graph_json(WorkflowGraphV1.model_validate(reordered))
    assert "viewport" not in canonical_graph_json(graph)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("nodes", [{"id": "bad id", "type": "manual", "config": {}}]),
        ("unknown", True),
    ],
)
def test_graph_schema_rejects_unknown_version_bounds_ids_and_fields(field, value):
    raw = valid_graph()
    raw[field] = value

    with pytest.raises(ValidationError):
        WorkflowGraphV1.model_validate(raw)


def test_empty_graph_is_schema_valid_but_not_runtime_valid():
    graph = WorkflowGraphV1.model_validate(
        {
            "schema_version": 1,
            "entry_node_id": "",
            "nodes": [],
            "edges": [],
            "output_node_ids": [],
            "metadata": {"layout": {}},
        }
    )

    result = validate_graph(graph)

    assert graph.nodes == []
    assert graph.edges == []
    assert result.valid is False
    assert "graph_entry_invalid" in {item.code for item in result.findings}


def test_empty_graph_rejects_stale_runtime_state():
    with pytest.raises(ValidationError):
        WorkflowGraphV1.model_validate(
            {
                "schema_version": 1,
                "entry_node_id": "trigger-1",
                "nodes": [],
                "edges": [],
                "output_node_ids": [],
            }
        )


def test_validator_returns_stable_findings_for_unknown_node_and_secret_input():
    raw = valid_graph()
    raw["nodes"][1]["type"] = "http_request"  # type: ignore[index]
    assert "node_type_unsupported" in codes(raw)

    raw = valid_graph()
    raw["nodes"][1]["config"]["api_key"] = "canary-secret"  # type: ignore[index]
    result = validate_graph(WorkflowGraphV1.model_validate(raw))

    assert "node_config_invalid" in {item.code for item in result.findings}
    assert "canary-secret" not in result.model_dump_json()


def test_missing_resources_remain_editable_but_unsupported_graphs_block_save():
    from app.automations.definitions.validation import save_blocking_findings

    raw = valid_graph()
    raw["nodes"][0]["config"] = {}  # type: ignore[index]
    missing = validate_graph(WorkflowGraphV1.model_validate(raw))
    assert "automation_resource_unavailable" in {item.code for item in missing.findings}
    assert save_blocking_findings(missing) == []

    raw = valid_graph()
    raw["nodes"][1]["type"] = "http_request"  # type: ignore[index]
    unsupported = validate_graph(WorkflowGraphV1.model_validate(raw))
    assert {item.code for item in save_blocking_findings(unsupported)} >= {"node_type_unsupported"}


def test_factory_default_array_mismatch_reports_exact_node_and_field():
    raw = valid_graph()
    raw["nodes"][1]["config"]["platforms"] = []  # type: ignore[index]

    result = validate_graph(WorkflowGraphV1.model_validate(raw))
    finding = next(item for item in result.findings if item.code == "node_config_invalid")

    assert finding.node_id == "generate-1"
    assert finding.field_path == "config.platforms"
    assert finding.message == "Generate content package: configuration.platforms must contain at least 1 item."


def test_catalog_exposes_factory_array_constraint_without_its_runtime_default():
    schema = next(item for item in node_catalog().nodes if item.type == "generate_content_pack").config_schema

    assert schema["properties"]["platforms"]["minItems"] == 1  # type: ignore[index]
    assert "default" not in schema["properties"]["platforms"]  # type: ignore[index]
    assert GenerateContentPackConfig.model_validate({}).platforms == ["telegram"]


def test_save_rejection_keeps_node_context_in_422_response():
    raw = valid_graph()
    raw["nodes"][1]["config"]["platforms"] = []  # type: ignore[index]
    graph = WorkflowGraphV1.model_validate(raw)

    with pytest.raises(AutomationDefinitionError) as raised:
        _require_saveable(validate_graph(graph), graph)

    error = raised.value
    assert error.status_code == 422
    assert error.node_id == "generate-1"
    assert error.node_type == "generate_content_pack"
    assert error.field_path == "config.platforms"

    response = asyncio.run(automation_definition_error(None, error))
    assert response.status_code == 422
    assert json.loads(response.body) == {
        "detail": {
            "code": "node_config_invalid",
            "message": "Generate content package: configuration.platforms must contain at least 1 item.",
            "node_id": "generate-1",
            "node_type": "generate_content_pack",
            "field_path": "config.platforms",
        }
    }


def test_validator_rejects_invalid_ports_cardinality_cycles_and_unreachable_nodes():
    raw = valid_graph()
    raw["edges"][0]["source_port"] = "missing"  # type: ignore[index]
    assert "edge_port_invalid" in codes(raw)

    raw = valid_graph()
    raw["edges"].append(deepcopy(raw["edges"][0]))  # type: ignore[union-attr]
    assert "edge_cardinality_invalid" in codes(raw)

    raw = valid_graph()
    raw["nodes"].append(  # type: ignore[union-attr]
        {"id": "filter-1", "type": "filter_content", "config": {}}
    )
    assert "graph_unreachable_node" in codes(raw)

    raw = valid_graph()
    raw["edges"].append(  # type: ignore[union-attr]
        {
            "source_node_id": "generate-1",
            "source_port": "drafts",
            "target_node_id": "generate-1",
            "target_port": "story",
        }
    )
    assert "graph_cycle" in codes(raw)


def test_retired_telegram_workflow_nodes_are_explicitly_invalid():
    raw = valid_graph()
    raw["nodes"][0]["type"] = "telegram_new_item"  # type: ignore[index]
    raw["nodes"][1]["type"] = "generate_telegram"  # type: ignore[index]

    result = validate_graph(WorkflowGraphV1.model_validate(raw))

    unsupported = [item for item in result.findings if item.code == "node_type_unsupported"]
    assert {item.node_id for item in unsupported} == {"trigger-1", "generate-1"}
    assert all(item.recovery_action and "not applied automatically" in item.recovery_action for item in unsupported)


def test_node_catalog_is_allowlisted_secret_free_and_matches_registry():
    catalog = node_catalog()
    serialized = catalog.model_dump_json()

    assert {item.type for item in catalog.nodes} == set(NODE_REGISTRY)
    assert all(item.config_schema.get("additionalProperties") is False for item in catalog.nodes)
    publish = next(item for item in catalog.nodes if item.type == "telegram_publish")
    assert publish.runtime_owner == "publishing"
    assert publish.runtime_job_types == ["telegram.publish"]
    for forbidden in ("api_key", "bot_token", "authorization", "secret_ref", "system_template"):
        assert forbidden not in serialized
