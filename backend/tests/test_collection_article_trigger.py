from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.automations.definitions.collection_events import (
    COLLECTION_ARTICLE_ADDED_EVENT,
    COLLECTION_ARTICLE_ADDED_TRIGGER,
    collection_article_event_id,
    collection_article_run_idempotency_key,
)
from app.automations.definitions.collection_execution import (
    CollectionArticleAddedJobPayload,
    CollectionArticleAddedOutput,
    _start_collection_downstream,
)
from app.automations.definitions.compiler import compile_graph
from app.automations.definitions.registry import COLLECTION_ARTICLE_ARTIFACT, node_catalog
from app.automations.definitions.runtime_state import sync_automation_job_succeeded
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


def test_collection_article_output_contract_carries_article_collection_and_event_context() -> None:
    output = CollectionArticleAddedOutput.model_validate(
        {
            "article": {
                "id": str(uuid4()),
                "title": "Saved article",
                "content": "Article body",
                "url": "https://example.test/article",
                "source_id": None,
                "published_at": None,
                "primary_media": None,
            },
            "collection": {"id": str(uuid4()), "name": "Reading queue"},
            "trigger": {
                "type": COLLECTION_ARTICLE_ADDED_TRIGGER,
                "event_type": COLLECTION_ARTICLE_ADDED_EVENT,
                "collection_id": str(uuid4()),
                "article_id": str(uuid4()),
                "source_event_id": "collection.article_added:source-event",
                "occurred_at": datetime.now(UTC).isoformat(),
                "actor_id": "operator",
            },
        }
    )

    assert output.article.title == "Saved article"
    assert output.collection.name == "Reading queue"
    assert output.trigger.event_type == COLLECTION_ARTICLE_ADDED_EVENT


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


def test_collection_article_output_contract_connects_to_generation_but_not_draft_input() -> None:
    collection_id = str(uuid4())
    prompt_id = uuid4()
    graph = WorkflowGraphV1.model_validate(
        {
            "schema_version": 1,
            "entry_node_id": "collection-trigger-1",
            "nodes": [
                {
                    "id": "collection-trigger-1",
                    "type": COLLECTION_ARTICLE_ADDED_TRIGGER,
                    "config": {"collection_id": collection_id},
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
                {"id": "drafts-1", "type": "save_drafts", "config": {}},
            ],
            "edges": [
                {
                    "source_node_id": "collection-trigger-1",
                    "source_port": "article",
                    "target_node_id": "generate-1",
                    "target_port": "story",
                },
                {
                    "source_node_id": "generate-1",
                    "source_port": "drafts",
                    "target_node_id": "drafts-1",
                    "target_port": "drafts",
                },
            ],
            "output_node_ids": ["drafts-1"],
            "metadata": {"layout": {}},
        }
    )

    validation = validate_graph(graph)
    plan = compile_graph(graph)
    catalog = node_catalog()
    trigger = next(item for item in catalog.nodes if item.type == COLLECTION_ARTICLE_ADDED_TRIGGER)

    assert validation.valid
    assert plan.trigger_kind == COLLECTION_ARTICLE_ADDED_TRIGGER
    assert trigger.outputs[0].artifact_types == [COLLECTION_ARTICLE_ARTIFACT]
    for node_type in ("filter_content", "research", "generate_content_pack"):
        node = next(item for item in catalog.nodes if item.type == node_type)
        assert COLLECTION_ARTICLE_ARTIFACT in node.inputs[0].artifact_types

    incompatible = WorkflowGraphV1.model_validate(
        {
            **graph.model_dump(mode="json"),
            "nodes": [graph.nodes[0].model_dump(mode="json"), graph.nodes[2].model_dump(mode="json")],
            "edges": [
                {
                    "source_node_id": "collection-trigger-1",
                    "source_port": "article",
                    "target_node_id": "drafts-1",
                    "target_port": "drafts",
                }
            ],
        }
    )
    assert any(item.code == "edge_port_invalid" for item in validate_graph(incompatible).findings)


@pytest.mark.asyncio
async def test_collection_article_downstream_binds_generation_job_to_saved_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    child_id = uuid4()
    story_id = uuid4()
    trigger_node = SimpleNamespace(
        node_id="collection-trigger-1",
        status="pending",
        started_at=None,
        finished_at=None,
        input_summary={},
        output_summary={},
    )
    generation_node = SimpleNamespace(
        id=uuid4(),
        node_id="generate-1",
        status="pending",
        workflow_job_id=None,
        started_at=None,
        finished_at=None,
        input_summary={},
        output_summary={},
    )
    child = SimpleNamespace(
        id=child_id,
        job_type="content_pack.generate",
        automation_run_id=None,
        automation_node_run_id=None,
    )
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=[trigger_node, generation_node]),
        get=AsyncMock(return_value=child),
    )
    context = SimpleNamespace(session=session)
    run = SimpleNamespace(
        id=run_id,
        status="queued",
        current_node_id="collection-trigger-1",
        finished_at=None,
    )
    plan = SimpleNamespace(
        stages=(
            SimpleNamespace(node_id="collection-trigger-1", node_type="collection_article_added", config={}),
            SimpleNamespace(
                node_id="generate-1",
                node_type="generate_content_pack",
                config={
                    "editorial_profile_id": str(uuid4()),
                    "provider_profile_id": str(uuid4()),
                    "prompt_version_ids": [],
                    "prompt_checksums": {},
                    "platforms": ["telegram"],
                },
            ),
        )
    )

    class FakeGroupingRepository:
        def __init__(self, _session):
            pass

        async def group_content_items(self, _content_item_ids):
            return SimpleNamespace(story=SimpleNamespace(id=story_id))

    class FakeEditorialService:
        def __init__(self, _session, *, profile_resolver):
            assert profile_resolver is None

        async def request_content_pack(self, _story_id, _request):
            return SimpleNamespace(job_id=child_id)

    monkeypatch.setattr("app.automations.definitions.collection_execution.StoryRepository", FakeGroupingRepository)
    monkeypatch.setattr("app.automations.definitions.collection_execution.EditorialService", FakeEditorialService)
    monkeypatch.setattr(
        "app.automations.definitions.collection_execution.require_exact_generation_prompts",
        AsyncMock(),
    )

    result = await _start_collection_downstream(
        context,
        job=SimpleNamespace(id=uuid4()),
        run=run,
        trigger_node=trigger_node,
        plan=plan,
        article=SimpleNamespace(id=uuid4(), title="Article", content_text="Body", primary_media=None),
        base_output={"article": {}, "collection": {"id": str(uuid4()), "name": "Reading queue"}, "trigger": {}},
        observed_at=datetime.now(UTC),
        profile_resolver=None,
    )

    assert result is not None
    assert result["continuation_job_id"] == str(child_id)
    assert result["continuation_node_id"] == "generate-1"
    assert child.automation_run_id == run_id
    assert child.automation_node_run_id == generation_node.id
    assert generation_node.status == "queued"
    assert trigger_node.status == "succeeded"
    assert run.status == "running"


@pytest.mark.asyncio
async def test_collection_generation_completion_finishes_saved_drafts_node() -> None:
    run_id = uuid4()
    generation_id = uuid4()
    generation_node = SimpleNamespace(
        id=generation_id,
        automation_run_id=run_id,
        node_id="generate-1",
        status="queued",
        started_at=None,
        finished_at=None,
        output_summary={},
        generation_run_id=None,
        platform_variant_revision_id=None,
        publication_id=None,
        automation_dispatch_id=None,
    )
    drafts_node = SimpleNamespace(
        id=uuid4(),
        automation_run_id=run_id,
        node_id="drafts-1",
        status="pending",
        started_at=None,
        finished_at=None,
    )
    run = SimpleNamespace(
        id=run_id,
        status="running",
        current_node_id="generate-1",
        finished_at=None,
        dry_run=False,
        resource_snapshot={"node_ids_by_type": {"save_drafts": ["drafts-1"]}},
    )
    job = SimpleNamespace(
        id=uuid4(),
        automation_run_id=run_id,
        automation_node_run_id=generation_id,
        job_type="content_pack.generate",
        started_at=None,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[run, generation_node, drafts_node, None]),
        add=Mock(),
    )

    await sync_automation_job_succeeded(
        session,
        job=job,
        result={"revision_id": str(uuid4())},
        observed_at=datetime.now(UTC),
    )

    assert generation_node.status == "succeeded"
    assert drafts_node.status == "succeeded"
    assert run.status == "succeeded"
    assert run.current_node_id is None
    assert run.finished_at is not None
