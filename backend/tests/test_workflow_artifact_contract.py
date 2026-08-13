from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.automations.definitions.artifacts import (
    artifact_for_result,
    legacy_artifact_shape,
    make_artifact,
    match_input_contract,
    normalize_artifact,
    review_artifact,
    shape_for_output_contract,
)
from app.automations.definitions.compiler import compile_graph
from app.automations.definitions.registry import NODE_REGISTRY, node_catalog
from app.automations.definitions.schemas import WorkflowArtifact, WorkflowGraphV1
from app.automations.definitions.validation import validate_graph


def _config(node_type: str) -> dict[str, object]:
    if node_type == "collection_article_added":
        return {"collection_id": str(uuid4())}
    if node_type == "new_source_item":
        return {"source_ids": [str(uuid4())]}
    if node_type == "research":
        return {"provider_profile_id": str(uuid4())}
    if node_type == "generate_content_pack":
        prompt_id = uuid4()
        return {
            "editorial_profile_id": str(uuid4()),
            "provider_profile_id": str(uuid4()),
            "prompt_version_ids": [str(prompt_id)],
            "prompt_checksums": {str(prompt_id): "a" * 64},
            "platforms": ["telegram"],
        }
    return {}


def _graph(nodes: list[tuple[str, str]], edges: list[tuple[str, str, str, str]], output: str) -> WorkflowGraphV1:
    return WorkflowGraphV1.model_validate(
        {
            "schema_version": 1,
            "entry_node_id": nodes[0][0],
            "nodes": [{"id": node_id, "type": node_type, "config": _config(node_type)} for node_id, node_type in nodes],
            "edges": [
                {
                    "source_node_id": source,
                    "source_port": source_port,
                    "target_node_id": target,
                    "target_port": target_port,
                }
                for source, source_port, target, target_port in edges
            ],
            "output_node_ids": [output],
        }
    )


def test_envelope_is_versioned_and_rejects_duplicate_capabilities() -> None:
    artifact = make_artifact(
        kind="research",
        capabilities=["research", "textual", "structured", "reviewable", "generatable"],
        payload={"story_revision_id": str(uuid4())},
        source_node_id="research-1",
        workflow_id="workflow-1",
        workflow_version_id="version-1",
        run_id="run-1",
        trigger_type="collection_article_added",
    )

    assert artifact.schema_version == 1
    assert artifact.context.source_node_id == "research-1"
    assert artifact.context.trigger is not None
    assert artifact.payload["story_revision_id"]
    with pytest.raises(ValidationError):
        WorkflowArtifact[object].model_validate(
            artifact.model_dump(mode="json") | {"capabilities": ["research", "research"]}
        )


def test_empty_input_contract_fails_closed() -> None:
    with pytest.raises(ValidationError):
        from app.automations.definitions.schemas import ArtifactInputContract

        ArtifactInputContract()


def test_legacy_artifact_values_normalize_without_rewriting_payload() -> None:
    normalized = normalize_artifact(
        {"artifact_type": "research_package", "story_revision_id": "revision-1"},
        source_node_id="legacy-1",
    )

    assert normalized is not None
    assert normalized.kind == "research"
    assert "reviewable" in normalized.capabilities
    assert normalized.payload["story_revision_id"] == "revision-1"
    assert legacy_artifact_shape("package").kind == "draft"
    assert legacy_artifact_shape("unknown-legacy-type").known is False


def test_trigger_result_keeps_trigger_context_in_the_envelope() -> None:
    artifact = artifact_for_result(
        {
            "output": {
                "article": {"id": "article-1"},
                "trigger": {
                    "type": "collection_article_added",
                    "occurred_at": "2026-08-06T10:00:00+00:00",
                },
            }
        },
        node_type="collection_article_added",
        source_node_id="trigger-1",
    )

    assert artifact is not None
    assert artifact.context.trigger is not None
    assert artifact.context.trigger.type == "collection_article_added"
    assert artifact.context.trigger.occurred_at.isoformat() == "2026-08-06T10:00:00+00:00"


def test_catalog_assigns_explicit_contracts_to_every_active_port() -> None:
    catalog = node_catalog()
    assert catalog.artifact_schema_version == 1
    assert catalog.capability_vocabulary_version == 1
    assert {item.type for item in catalog.nodes} == set(NODE_REGISTRY)
    for definition in NODE_REGISTRY.values():
        item = next(candidate for candidate in catalog.nodes if candidate.type == definition.type)
        if definition.entry:
            assert not definition.inputs
        for port in (*item.inputs, *item.outputs):
            assert port.input_contract is not None or port.output_contract is not None


def test_required_capability_paths_compile_and_incompatible_edges_fail() -> None:
    graph = _graph(
        [
            ("trigger-1", "collection_article_added"),
            ("research-1", "research"),
            ("review-1", "human_review"),
            ("generate-1", "generate_content_pack"),
            ("drafts-1", "save_drafts"),
        ],
        [
            ("trigger-1", "article", "research-1", "story"),
            ("research-1", "story", "review-1", "draft"),
            ("review-1", "approved", "generate-1", "story"),
            ("generate-1", "drafts", "drafts-1", "drafts"),
        ],
        "drafts-1",
    )
    assert validate_graph(graph).valid
    assert [stage.node_type for stage in compile_graph(graph).stages] == [
        "collection_article_added",
        "research",
        "human_review",
        "generate_content_pack",
        "save_drafts",
    ]

    incompatible = _graph(
        [("trigger-1", "collection_article_added"), ("drafts-1", "save_drafts")],
        [("trigger-1", "article", "drafts-1", "drafts")],
        "drafts-1",
    )
    assert any(item.code == "edge_port_invalid" for item in validate_graph(incompatible).findings)


def test_trigger_incoming_connection_remains_structural_error() -> None:
    graph = _graph(
        [("trigger-1", "collection_article_added"), ("trigger-2", "manual")],
        [("trigger-1", "article", "trigger-2", "story")],
        "trigger-1",
    )
    assert any(item.message.startswith("Trigger nodes cannot receive") for item in validate_graph(graph).findings)


def test_review_preserves_research_payload_and_only_adds_publishability_when_eligible() -> None:
    artifact = make_artifact(
        kind="research",
        capabilities=["research", "textual", "structured", "reviewable", "generatable"],
        payload={"evidence": [{"url": "https://example.test"}]},
        source_node_id="research-1",
    )
    reviewed = review_artifact(artifact, approved=True)
    publishable = review_artifact(artifact, approved=True, eligible_for_publication=True)

    assert reviewed.payload == artifact.payload
    assert set(artifact.capabilities).issubset(reviewed.capabilities)
    assert "approved" in reviewed.capabilities
    assert "publishable" not in reviewed.capabilities
    assert "publishable" in publishable.capabilities
    assert reviewed.metadata == {"review": {"approved": True}}


def test_research_output_satisfies_generate_input_without_node_pair_rules() -> None:
    research = NODE_REGISTRY["research"].outputs["story"].output_contract
    generate_input = NODE_REGISTRY["generate_content_pack"].inputs["story"].input_contract
    assert research is not None
    assert generate_input is not None
    assert match_input_contract(shape_for_output_contract(research), generate_input) == "compatible"
