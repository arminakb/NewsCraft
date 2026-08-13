from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.automations.definitions.execution import AutomationExecutionService
from app.automations.definitions.models import Automation, AutomationNodeRun, AutomationRun, AutomationVersion


async def test_run_projection_filters_pages_and_redacts_summaries(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    automation_id = uuid4()
    version_id = uuid4()
    now = datetime.now(UTC)
    async with session_factory() as session:
        automation = Automation(id=automation_id, name="Projection proof", idempotency_key="projection-proof")
        session.add(automation)
        await session.flush()
        version = AutomationVersion(
            id=version_id,
            automation_id=automation_id,
            version=1,
            graph={
                "schema_version": 1,
                "entry_node_id": "manual-1",
                "nodes": [{"id": "manual-1", "type": "manual", "config": {}}],
                "edges": [],
                "output_node_ids": ["manual-1"],
                "metadata": {"layout": {}},
            },
            graph_hash="a" * 64,
            compiler_version="workflow-graph-v1",
            compiled_plan={},
            validation_summary={},
            creation_actor_type="human",
            creation_actor_id="local-owner",
            creation_reason="projection test",
            idempotency_key="projection-version",
        )
        session.add(version)
        await session.flush()
        automation.draft_version_id = version.id

        failed = AutomationRun(
            id=uuid4(),
            automation_id=automation_id,
            automation_version_id=version_id,
            trigger_kind="manual",
            trigger_metadata={"story_id": str(uuid4()), "authorization": "credential-canary"},
            dry_run=True,
            status="failed",
            current_node_id="generate-1",
            resource_snapshot={
                "automation_version": 1,
                "prompt_version_id": "prompt-1",
                "api_key": "credential-canary",
            },
            idempotency_key="projection-run-failed",
            request_hash="b" * 64,
            safe_error_code="automation_resource_unavailable",
            safe_error_message="Provider unavailable.",
            started_at=now - timedelta(minutes=2),
            finished_at=now - timedelta(minutes=1),
            created_at=now,
        )
        succeeded = AutomationRun(
            id=uuid4(),
            automation_id=automation_id,
            automation_version_id=version_id,
            trigger_kind="manual",
            trigger_metadata={},
            dry_run=False,
            status="succeeded",
            resource_snapshot={"automation_version": 1},
            idempotency_key="projection-run-live",
            request_hash="c" * 64,
            started_at=now - timedelta(days=2),
            finished_at=now - timedelta(days=2, minutes=-1),
            created_at=now - timedelta(days=2),
        )
        session.add_all([failed, succeeded])
        await session.flush()
        session.add(
            AutomationNodeRun(
                automation_run_id=failed.id,
                node_id="generate-1",
                status="failed",
                input_summary={"story_id": str(uuid4()), "secret": "credential-canary"},
                output_summary={"summary": "safe result", "raw_response": "credential-canary"},
                usage={"total_tokens": 42, "access_token": "credential-canary"},
                retry_metadata={"retryable": True, "request_headers": {"Authorization": "credential-canary"}},
                safe_error_code="automation_resource_unavailable",
                safe_error_message="Provider unavailable.",
                started_at=now - timedelta(minutes=2),
                finished_at=now - timedelta(minutes=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        page = await AutomationExecutionService(session).list(
            automation_id,
            limit=1,
            cursor=None,
            dry_run=True,
            failed_only=True,
            date_from=now - timedelta(hours=1),
            date_to=now + timedelta(hours=1),
        )
        assert len(page.items) == 1
        projected = page.items[0]
        assert projected.id == failed.id
        assert projected.trigger_metadata.get("authorization") is None
        assert projected.resource_snapshot == {"automation_version": 1, "prompt_version_id": "prompt-1"}
        assert projected.nodes[0].input_summary.get("secret") is None
        assert projected.nodes[0].output_summary == {"summary": "safe result"}
        assert projected.nodes[0].usage == {"total_tokens": 42}
        assert projected.nodes[0].retry_metadata == {"retryable": True}

        first = await AutomationExecutionService(session).list(automation_id, limit=1, cursor=None)
        assert first.next_cursor == str(failed.id)
        second = await AutomationExecutionService(session).list(
            automation_id,
            limit=1,
            cursor=failed.id,
        )
        assert [item.id for item in second.items] == [succeeded.id]
