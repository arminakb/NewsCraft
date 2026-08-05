from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.automations.definitions.collection_events import (
    COLLECTION_ARTICLE_ADDED_EVENT,
    COLLECTION_ARTICLE_ADDED_TRIGGER,
    collection_article_event_id,
    collection_article_run_idempotency_key,
)
from app.automations.definitions.collection_execution import CollectionArticleAddedJobPayload
from app.automations.definitions.compiler import compile_graph
from app.automations.definitions.schemas import WorkflowGraphV1
from app.automations.definitions.validation import validate_graph


def _graph(collection_id: str) -> WorkflowGraphV1:
    return WorkflowGraphV1.model_validate(
        {
            "schema_version": 1,
            "entry_node_id": "collection-trigger-1",
            "nodes": [
                {
                    "id": "collection-trigger-1",
                    "type": COLLECTION_ARTICLE_ADDED_TRIGGER,
                    "config": {"collection_id": collection_id},
                }
            ],
            "edges": [],
            "output_node_ids": ["collection-trigger-1"],
            "metadata": {"layout": {}},
        }
    )


def test_collection_event_contract_and_run_key_are_stable() -> None:
    collection_id = uuid4()
    article_id = uuid4()
    source_event_id = collection_article_event_id(collection_id=collection_id, article_id=article_id)

    assert source_event_id == f"{COLLECTION_ARTICLE_ADDED_EVENT}:{collection_id}:{article_id}"
    key = collection_article_run_idempotency_key(
        automation_id=uuid4(),
        version_id=uuid4(),
        trigger_node_id="collection-trigger-1",
        article_id=article_id,
        collection_id=collection_id,
        source_event_id=source_event_id,
    )
    assert all(value in key for value in ("version:", "trigger:collection-trigger-1", "article:", "event:"))

    payload = CollectionArticleAddedJobPayload.model_validate(
        {
            "trigger_kind": COLLECTION_ARTICLE_ADDED_TRIGGER,
            "automation_id": str(uuid4()),
            "automation_version_id": str(uuid4()),
            "trigger_node_id": "collection-trigger-1",
            "article_id": str(article_id),
            "collection_id": str(collection_id),
            "source_event_id": source_event_id,
            "event_type": COLLECTION_ARTICLE_ADDED_EVENT,
            "occurred_at": datetime.now(UTC).isoformat(),
            "actor_id": "operator",
        }
    )
    assert payload.event_type == COLLECTION_ARTICLE_ADDED_EVENT
    assert payload.article_id == article_id


def test_collection_trigger_is_a_valid_first_node_and_compiles_to_durable_start_job() -> None:
    graph = _graph(str(uuid4()))

    validation = validate_graph(graph)
    plan = compile_graph(graph)

    assert validation.valid
    assert plan.entry_node_id == "collection-trigger-1"
    assert plan.trigger_kind == COLLECTION_ARTICLE_ADDED_TRIGGER
    assert plan.required_job_types == ("automation.run.start",)
    assert plan.output_node_ids == ("collection-trigger-1",)


def test_collection_trigger_rejects_incoming_edges() -> None:
    graph = WorkflowGraphV1.model_validate(
        {
            "schema_version": 1,
            "entry_node_id": "manual-1",
            "nodes": [
                {"id": "manual-1", "type": "manual", "config": {"story_revision_id": str(uuid4())}},
                {
                    "id": "collection-trigger-1",
                    "type": COLLECTION_ARTICLE_ADDED_TRIGGER,
                    "config": {"collection_id": str(uuid4())},
                },
            ],
            "edges": [
                {
                    "source_node_id": "manual-1",
                    "source_port": "story",
                    "target_node_id": "collection-trigger-1",
                    "target_port": "article",
                }
            ],
            "output_node_ids": ["collection-trigger-1"],
            "metadata": {"layout": {}},
        }
    )

    findings = validate_graph(graph).findings
    assert any(finding.code == "graph_entry_invalid" for finding in findings)
    assert any(finding.code == "edge_port_invalid" for finding in findings)
