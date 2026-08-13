from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.automations.definitions.execution import AutomationExecutionService, _safe_projection_value
from app.automations.definitions.schemas import AutomationRunStart
from app.main import app
from app.operations.history import _category_for, _subject_url, history_statement


def test_run_contract_exposes_safe_inputs_and_bounded_filters() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/automations/{automation_id}/runs"]["get"]
    parameter_names = {item["name"] for item in operation["parameters"]}
    assert {
        "automation_id",
        "limit",
        "cursor",
        "status",
        "dry_run",
        "date_from",
        "date_to",
        "failed_only",
    }.issubset(parameter_names)
    body = schema["components"]["schemas"]["AutomationRunStart"]["properties"]
    assert {"version_number", "dry_run", "source_message_id", "story_id", "story_revision_id"}.issubset(body)
    limit = next(item for item in operation["parameters"] if item["name"] == "limit")["schema"]
    assert limit["maximum"] == 100


def test_run_start_accepts_one_allowlisted_story_input_only() -> None:
    story_id = uuid4()
    assert AutomationRunStart(story_id=story_id).story_id == story_id
    assert AutomationRunStart(story_revision_id=story_id).story_revision_id == story_id
    with pytest.raises(ValidationError, match="mutually exclusive"):
        AutomationRunStart(story_id=story_id, story_revision_id=uuid4())
    with pytest.raises(ValidationError):
        AutomationRunStart.model_validate({"story_id": str(story_id), "api_key": "credential-canary"})


def test_run_projection_redacts_secret_shaped_fields_but_keeps_prompt_identity() -> None:
    projected = _safe_projection_value(
        {
            "prompt_version_id": "prompt-1",
            "provider_model": "model-1",
            "nested": {
                "api_key": "credential-canary",
                "authorization": "Bearer credential-canary",
                "raw_response": "credential-canary",
                "summary": "safe result",
            },
        }
    )
    assert projected == {
        "prompt_version_id": "prompt-1",
        "provider_model": "model-1",
        "nested": {"summary": "safe result"},
    }


async def test_run_list_applies_server_filters_and_stable_pagination_order() -> None:
    session = EmptySession()
    page = await AutomationExecutionService(session).list(  # type: ignore[arg-type]
        uuid4(),
        limit=25,
        cursor=None,
        status="failed",
        dry_run=True,
        date_from=datetime(2026, 8, 1, tzinfo=UTC),
        date_to=datetime(2026, 8, 2, tzinfo=UTC),
        failed_only=True,
    )
    assert page.items == [] and page.next_cursor is None
    sql = str(session.statements[0])
    assert "automation_runs.status" in sql
    assert "automation_runs.dry_run" in sql
    assert "automation_runs.created_at >=" in sql
    assert "automation_runs.created_at <=" in sql
    assert "ORDER BY automation_runs.created_at DESC, automation_runs.id DESC" in sql
    assert "LIMIT" in sql


class EmptySession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def scalars(self, statement):
        self.statements.append(statement)
        return []


def test_operations_history_maps_workflow_version_run_and_node_taxonomy() -> None:
    run_id = uuid4()
    automation_id = uuid4()
    assert _category_for("automation.version_created", None) == "automation"
    assert _category_for("automation.run.failed", "content_pack.generate") == "automation"
    assert _subject_url(
        {"automation_id": str(automation_id), "automation_run_id": str(run_id)},
        None,
        "automation",
    ) == f"/automations/runs?runId={run_id}&automationId={automation_id}"
    statement = history_statement(
        cursor=None,
        subject_type="automation_run",
        subject_id=run_id,
        category="automation",
        status=None,
        limit=25,
    )
    sql = str(statement)
    assert "workflow_jobs.automation_run_id" in sql
    assert "automation" in sql
