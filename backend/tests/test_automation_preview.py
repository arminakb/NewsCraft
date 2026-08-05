from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.automations.definitions.models import Automation, AutomationVersion
from app.automations.definitions.service import AutomationDefinitionService, _automation_preview


def test_preview_uses_compiled_order_real_outputs_and_excludes_config() -> None:
    version = AutomationVersion(
        id=uuid4(),
        automation_id=uuid4(),
        version=4,
        schema_version=1,
        graph={
            "nodes": [
                {"id": "publish", "type": "telegram_publish", "config": {"destination_id": str(uuid4())}},
                {"id": "trigger", "type": "manual", "config": {"story_revision_id": str(uuid4())}},
                {"id": "review", "type": "human_review", "config": {"instructions": "credential-canary"}},
            ],
            "output_node_ids": ["publish"],
        },
        graph_hash="a" * 64,
        compiler_version="workflow-v1.0",
        compiled_plan={
            "stages": [
                {
                    "ordinal": 2,
                    "node_id": "publish",
                    "node_type": "telegram_publish",
                    "config": {"secret_ref": "credential-canary"},
                },
                {"ordinal": 0, "node_id": "trigger", "node_type": "manual", "config": {}},
                {"ordinal": 1, "node_id": "review", "node_type": "human_review", "config": {}},
            ]
        },
        validation_summary={
            "valid": False,
            "findings": [{"severity": "error", "node_id": "review", "message": "Review needs attention"}],
        },
        creation_actor_type="human",
        creation_actor_id="owner",
        creation_reason="test",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    preview = _automation_preview(
        version,
        version_state="active",
        run_count=7,
        completed_count=5,
        succeeded_count=4,
        last_run_at=datetime(2026, 8, 1, tzinfo=UTC),
        last_outcome="failed",
    )

    assert preview is not None
    assert [stage.node_id for stage in preview.stages] == ["trigger", "review", "publish"]
    assert preview.output_platforms == ["telegram"]
    assert preview.stages[1].needs_attention is True
    assert preview.success_rate == 80
    serialized = preview.model_dump_json()
    assert "credential-canary" not in serialized
    assert "secret_ref" not in serialized
    assert "destination_id" not in serialized


def test_preview_marks_draft_multi_platform_and_unknown_outputs_from_nodes() -> None:
    cases = [
        ("save_drafts", {}, ["draft"]),
        ("manual_package", {"platforms": ["x", "blog"]}, ["x", "blog"]),
        ("custom_output", {}, ["unknown"]),
    ]
    for node_type, config, expected in cases:
        version = AutomationVersion(
            id=uuid4(),
            automation_id=uuid4(),
            version=1,
            schema_version=1,
            graph={"nodes": [{"id": "output", "type": node_type, "config": config}], "output_node_ids": ["output"]},
            graph_hash="a" * 64,
            compiler_version="workflow-v1.0",
            compiled_plan={"stages": [{"ordinal": 0, "node_id": "output", "node_type": node_type, "config": {}}]},
            validation_summary={"valid": True, "findings": []},
            creation_actor_type="human",
            creation_actor_id="owner",
            creation_reason="test",
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        preview = _automation_preview(
            version,
            version_state="draft",
            run_count=0,
            completed_count=0,
            succeeded_count=0,
            last_run_at=None,
            last_outcome=None,
        )
        assert preview is not None
        assert preview.output_platforms == expected


def test_preview_marks_empty_workflow_without_inventing_stages() -> None:
    version = AutomationVersion(
        id=uuid4(),
        automation_id=uuid4(),
        version=1,
        schema_version=1,
        graph={
            "schema_version": 1,
            "entry_node_id": "",
            "nodes": [],
            "edges": [],
            "output_node_ids": [],
            "metadata": {"layout": {}},
        },
        graph_hash="a" * 64,
        compiler_version=None,
        compiled_plan={},
        validation_summary={"valid": False, "findings": []},
        creation_actor_type="human",
        creation_actor_id="owner",
        creation_reason="test",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    preview = _automation_preview(
        version,
        version_state="draft",
        run_count=0,
        completed_count=0,
        succeeded_count=0,
        last_run_at=None,
        last_outcome=None,
    )

    assert preview is not None
    assert preview.stages == []
    assert preview.output_platforms == ["unknown"]
    assert preview.valid is False

async def test_list_with_rows_attaches_preview_without_duplicate_schema_field() -> None:
    automation_id = uuid4()
    version_id = uuid4()
    now = datetime(2026, 8, 1, tzinfo=UTC)
    automation = Automation(
        id=automation_id,
        name="Morning newsroom",
        description=None,
        lifecycle="inactive",
        owner_type="operator_managed",
        owner_id="local-owner",
        revision=1,
        active_version_id=None,
        draft_version_id=version_id,
        archived_at=None,
        created_at=now,
        updated_at=now,
    )
    version = AutomationVersion(
        id=version_id,
        automation_id=automation_id,
        version=1,
        schema_version=1,
        graph={
            "nodes": [{"id": "draft", "type": "save_drafts", "config": {}}],
            "output_node_ids": ["draft"],
        },
        graph_hash="a" * 64,
        compiler_version="workflow-v1.0",
        compiled_plan={"stages": [{"ordinal": 0, "node_id": "draft", "node_type": "save_drafts"}]},
        validation_summary={"valid": True, "findings": []},
        creation_actor_type="human",
        creation_actor_id="owner",
        creation_reason="test",
        created_at=now,
    )
    session = _ListSession(automation, version)

    page = await AutomationDefinitionService(session).list_automations(
        limit=50,
        cursor=None,
        include_archived=False,
    )

    assert len(page.items) == 1
    assert page.items[0].preview is not None
    assert page.items[0].preview.output_platforms == ["draft"]


class _Rows:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return self._rows


class _ListSession:
    def __init__(self, automation: Automation, version: AutomationVersion) -> None:
        self._automation = automation
        self._version = version
        self._scalar_calls = 0

    async def scalars(self, _statement: object) -> list[Automation] | list[AutomationVersion]:
        self._scalar_calls += 1
        return [self._automation] if self._scalar_calls == 1 else [self._version]

    async def execute(self, _statement: object) -> _Rows:
        return _Rows([])
