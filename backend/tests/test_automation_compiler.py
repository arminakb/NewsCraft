from __future__ import annotations

from uuid import uuid4

import pytest

from app.automations.definitions.compiler import CompilationError, compile_graph, verify_compiled_plan
from app.automations.definitions.schemas import WorkflowGraphV1


def _manual_graph() -> WorkflowGraphV1:
    prompt_id = uuid4()
    return WorkflowGraphV1.model_validate(
        {
            "schema_version": 1,
            "entry_node_id": "trigger-1",
            "nodes": [
                {"id": "trigger-1", "type": "manual", "config": {"story_revision_id": str(uuid4())}},
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
        }
    )


def _telegram_graph() -> WorkflowGraphV1:
    return WorkflowGraphV1.model_validate(
        {
            "schema_version": 1,
            "entry_node_id": "trigger-1",
            "nodes": [
                {
                    "id": "trigger-1",
                    "type": "telegram_new_item",
                    "config": {"source_id": str(uuid4())},
                },
                {
                    "id": "generate-1",
                    "type": "generate_telegram",
                    "config": {
                        "editorial_profile_id": str(uuid4()),
                        "provider_profile_id": str(uuid4()),
                        "prompt_template_version_id": str(uuid4()),
                        "prompt_checksum_sha256": "a" * 64,
                    },
                },
                {"id": "review-1", "type": "human_review", "config": {}},
                {
                    "id": "publish-1",
                    "type": "telegram_publish",
                    "config": {"destination_id": str(uuid4())},
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
                    "target_node_id": "review-1",
                    "target_port": "draft",
                },
                {
                    "source_node_id": "review-1",
                    "source_port": "approved",
                    "target_node_id": "publish-1",
                    "target_port": "draft",
                },
            ],
            "output_node_ids": ["publish-1"],
        }
    )


def test_compiler_is_deterministic_and_keeps_stable_node_ids():
    graph = _manual_graph()
    reordered = graph.model_copy(
        update={"nodes": list(reversed(graph.nodes)), "edges": list(reversed(graph.edges))}
    )

    first = compile_graph(graph)
    second = compile_graph(reordered)

    assert first.plan_hash == second.plan_hash
    assert [item.node_id for item in first.stages] == ["trigger-1", "generate-1", "draft-1"]
    assert first.trigger_kind == "manual"
    assert verify_compiled_plan(graph, first.model_dump(mode="json")) == first


def test_compiler_records_publication_boundary_for_server_owned_dry_run_skip():
    plan = compile_graph(_telegram_graph())

    assert plan.trigger_kind == "telegram_new_item"
    assert plan.publishing_node_ids == ("publish-1",)
    assert "telegram.publish" in plan.required_job_types
    assert plan.supports_dry_run is True


def test_compiler_rejects_stale_or_tampered_saved_plan():
    graph = _manual_graph()
    raw = compile_graph(graph).model_dump(mode="json")
    raw["plan_hash"] = "0" * 64

    with pytest.raises(CompilationError) as exc:
        verify_compiled_plan(graph, raw)

    assert exc.value.code == "automation_compiled_plan_stale"


def test_compiler_rejects_non_linear_fan_out_with_stable_error():
    graph = _manual_graph()
    raw = graph.model_dump(mode="json")
    raw["nodes"].append({"id": "draft-2", "type": "save_drafts", "config": {}})
    raw["edges"].append(
        {
            "source_node_id": "generate-1",
            "source_port": "drafts",
            "target_node_id": "draft-2",
            "target_port": "drafts",
        }
    )
    raw["output_node_ids"].append("draft-2")

    with pytest.raises(CompilationError) as exc:
        compile_graph(WorkflowGraphV1.model_validate(raw))

    assert exc.value.code in {"edge_cardinality_invalid", "automation_graph_not_linear"}
