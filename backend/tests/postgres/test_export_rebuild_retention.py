from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.exports import _enqueue_export_job, export_idempotency_key
from app.exports.models import BuildExportPayload
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.types import JobOrigin
from app.retention.models import RetentionRun
from app.retention.service import RetentionService


@pytest.mark.asyncio
async def test_pending_old_cleanup_cannot_delete_new_export_generation(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
):
    observed_at = datetime(2026, 7, 13, 10, tzinfo=UTC)
    pack_id = uuid4()
    payload = BuildExportPayload(
        content_pack_id=pack_id,
        revision_ids=[uuid4()],
        revision_hashes=["a" * 64],
        platforms=["blog"],
        platform_variant_ids=[uuid4()],
        formats=["json"],
        include_media=False,
    )
    old = WorkflowJob(
        job_type="build_export",
        status="succeeded",
        payload=payload.model_dump(mode="json"),
        result={},
        idempotency_key=export_idempotency_key(payload),
        origin=JobOrigin.MANUAL,
        pause_sensitive=False,
        scheduled_for=observed_at - timedelta(days=20),
        attempt_count=1,
        max_attempts=3,
        progress=100,
        finished_at=observed_at - timedelta(days=19),
    )
    async with session_factory() as session:
        session.add(old)
        await session.flush()
        old.result = {
            "export_id": str(old.id),
            "content_pack_id": str(pack_id),
            "state": "expired",
            "expired_at": observed_at.isoformat(),
        }
        await session.commit()
        old_id = old.id

    export_root = tmp_path / "exports"
    media_root = tmp_path / "media"
    old_dir = export_root / str(old_id)
    old_dir.mkdir(parents=True)
    (old_dir / "old.json").write_text("old")
    media_root.mkdir()

    async def request_rebuild():
        async with session_factory() as session:
            result = await _enqueue_export_job(session, payload)
            job_id = result.job.id
            created = result.created
            await session.commit()
            return job_id, created

    first, replay = await asyncio.gather(request_rebuild(), request_rebuild())
    assert first[0] == replay[0]
    assert {first[1], replay[1]} == {True, False}
    new_id = first[0]
    assert new_id != old_id

    async with session_factory() as session:
        rebuilt = await session.get(WorkflowJob, new_id)
        rebuilt.status = "succeeded"
        rebuilt.result = {"state": "complete", "generation": 1}
        rebuilt.finished_at = observed_at + timedelta(minutes=2)
        run = RetentionRun(
            status="running",
            preview_token="f" * 64,
            policy_snapshot={},
            candidate_snapshot=[],
            cleanup_intent_snapshot=[
                {
                    "category": "export_artifact",
                    "record_id": str(old_id),
                    "operation": "delete_tree",
                    "relative_path": str(old_id),
                }
            ],
            count_snapshot={},
            error_snapshot=[],
            previewed_at=observed_at - timedelta(minutes=2),
            preview_expires_at=observed_at + timedelta(minutes=10),
            started_at=observed_at,
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    new_dir = export_root / str(new_id)
    new_dir.mkdir()
    new_file = new_dir / "new.json"
    new_file.write_text("new")

    async with session_factory() as session:
        finished = await RetentionService(session).finish_filesystem_phase(
            run_id,
            export_root=export_root,
            media_root=media_root,
        )
        assert finished.status == "succeeded"

    assert not old_dir.exists()
    assert new_file.read_text() == "new"
    async with session_factory() as session:
        rebuilt = await session.get(WorkflowJob, new_id)
        assert rebuilt.result == {"state": "complete", "generation": 1}
        old_row = await session.get(WorkflowJob, old_id)
        assert old_row.result["state"] == "expired"
        lineage_events = list(
            await session.scalars(
                select(WorkflowEvent).where(
                    WorkflowEvent.workflow_job_id == new_id,
                    WorkflowEvent.event_type == "export.rebuild_enqueued",
                )
            )
        )
        assert len(lineage_events) == 1
        assert lineage_events[0].event_data["previous_export_id"] == str(old_id)
