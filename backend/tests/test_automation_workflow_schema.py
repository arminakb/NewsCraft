from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.automations.definitions.registry import NODE_REGISTRY, node_catalog
from app.automations.definitions.schemas import WorkflowGraphV1, canonical_graph_json, graph_sha256
from app.automations.definitions.validation import validate_graph


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


def test_telegram_publish_requires_exact_human_review_boundary():
    source_id = uuid4()
    profile_id = uuid4()
    provider_id = uuid4()
    prompt_id = uuid4()
    destination_id = uuid4()
    raw = {
        "schema_version": 1,
        "entry_node_id": "trigger-1",
        "nodes": [
            {
                "id": "trigger-1",
                "type": "telegram_new_item",
                "config": {"source_id": str(source_id)},
            },
            {
                "id": "generate-1",
                "type": "generate_telegram",
                "config": {
                    "editorial_profile_id": str(profile_id),
                    "provider_profile_id": str(provider_id),
                    "prompt_template_version_id": str(prompt_id),
                    "prompt_checksum_sha256": "a" * 64,
                },
            },
            {
                "id": "publish-1",
                "type": "telegram_publish",
                "config": {"destination_id": str(destination_id)},
            },
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
                "source_port": "draft",
                "target_node_id": "publish-1",
                "target_port": "draft",
            },
        ],
        "output_node_ids": ["publish-1"],
    }

    result = validate_graph(WorkflowGraphV1.model_validate(raw))

    assert "automation_activation_invalid" in {item.code for item in result.findings}


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
