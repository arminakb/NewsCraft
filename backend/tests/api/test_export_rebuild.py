from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.exports import create_export, export_idempotency_key, get_export
from app.exports.models import BuildExportPayload, ExportRequest


def _payload(pack_id):
    return BuildExportPayload(
        content_pack_id=pack_id,
        revision_ids=[uuid4()],
        revision_hashes=["a" * 64],
        platforms=["blog"],
        platform_variant_ids=[uuid4()],
        formats=["json"],
        include_media=False,
    )


def _expired_job(payload, *, job_id=None, expired_at=None):
    job_id = job_id or uuid4()
    expired_at = expired_at or datetime(2026, 7, 13, 8, tzinfo=UTC)
    finished_at = expired_at - timedelta(days=1)
    return SimpleNamespace(
        id=job_id,
        job_type="build_export",
        status="succeeded",
        payload=payload.model_dump(mode="json"),
        result={
            "export_id": str(job_id),
            "content_pack_id": str(payload.content_pack_id),
            "state": "expired",
            "expired_at": expired_at.isoformat(),
        },
        idempotency_key=None,
        scheduled_for=finished_at,
        attempt_count=1,
        finished_at=finished_at,
        created_at=finished_at,
        error_code=None,
        error_message=None,
    )


@pytest.mark.asyncio
async def test_expired_export_requests_create_immutable_deduplicated_rebuild_generations(
    monkeypatch,
    tmp_path,
):
    pack_id = uuid4()
    payload = _payload(pack_id)
    base_key = export_idempotency_key(payload)
    old = _expired_job(payload)
    old.idempotency_key = base_key
    jobs_by_key = {base_key: old}
    events = []

    class Service:
        def __init__(self, session, *, export_root, media_root):
            pass

        async def prepare_payload(self, request):
            return payload

    class Repository:
        def __init__(self, session):
            pass

        async def enqueue_job(self, **kwargs):
            key = kwargs["idempotency_key"]
            existing = jobs_by_key.get(key)
            if existing is not None:
                return SimpleNamespace(job=existing, created=False)
            job = SimpleNamespace(
                id=uuid4(),
                job_type=kwargs["job_type"],
                status="queued",
                payload=kwargs["payload"],
                result={},
                idempotency_key=key,
                scheduled_for=datetime.now(UTC),
                attempt_count=0,
                finished_at=None,
                created_at=datetime.now(UTC),
                error_code=None,
                error_message=None,
            )
            jobs_by_key[key] = job
            return SimpleNamespace(job=job, created=True)

    class Session:
        async def scalar(self, statement):
            return old

        async def get(self, model, identifier):
            return next((job for job in jobs_by_key.values() if job.id == identifier), None)

        def add(self, value):
            events.append(value)

        async def flush(self):
            return None

        async def commit(self):
            return None

    monkeypatch.setattr("app.api.exports.ExportService", Service)
    monkeypatch.setattr("app.api.exports.JobRepository", Repository)
    body = ExportRequest(content_pack_id=pack_id, formats=["json"])
    session = Session()

    first = await create_export(
        pack_id,
        body,
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
        session=session,
    )

    assert first.job_id != old.id
    assert first.status == "queued"
    assert first.deduplicated is False
    assert old.status == "succeeded"
    assert old.result["state"] == "expired"
    first_job = await session.get(None, first.job_id)
    assert first_job.idempotency_key.startswith(f"{base_key}:rebuild:")
    assert len(first_job.idempotency_key) == len(base_key) + len(":rebuild:") + 64
    old_projection = await get_export(old.id, session=session)
    assert old_projection.downloads == []
    assert old_projection.error_code == "export_expired"

    first_expired_at = datetime(2026, 7, 14, 8, tzinfo=UTC)
    first_job.status = "succeeded"
    first_job.finished_at = first_expired_at
    first_job.result = {
        "export_id": str(first_job.id),
        "content_pack_id": str(pack_id),
        "state": "expired",
        "expired_at": first_expired_at.isoformat(),
    }
    second = await create_export(
        pack_id,
        body,
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
        session=session,
    )

    assert second.job_id not in {old.id, first.job_id}
    assert second.status == "queued"
    assert second.deduplicated is False
    second_job = await session.get(None, second.job_id)
    replay = await create_export(
        pack_id,
        body,
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
        session=session,
    )
    assert replay.job_id == second.job_id
    assert replay.deduplicated is True
    assert second_job.result == {}
    assert [event.event_type for event in events] == [
        "export.rebuild_enqueued",
        "export.rebuild_enqueued",
    ]
    assert events[0].event_data["previous_export_id"] == str(old.id)
    assert events[1].event_data["previous_export_id"] == str(first.job_id)


@pytest.mark.asyncio
async def test_completed_nonexpired_export_keeps_generic_idempotent_replay(monkeypatch, tmp_path):
    pack_id = uuid4()
    payload = _payload(pack_id)
    job = SimpleNamespace(
        id=uuid4(),
        job_type="build_export",
        status="succeeded",
        payload=payload.model_dump(mode="json"),
        result={"state": "complete"},
        scheduled_for=datetime.now(UTC),
    )

    class Service:
        def __init__(self, session, *, export_root, media_root):
            pass

        async def prepare_payload(self, request):
            return payload

    class Repository:
        def __init__(self, session):
            pass

        async def enqueue_job(self, **kwargs):
            return SimpleNamespace(job=job, created=False)

    class Session:
        async def commit(self):
            return None

    monkeypatch.setattr("app.api.exports.ExportService", Service)
    monkeypatch.setattr("app.api.exports.JobRepository", Repository)

    accepted = await create_export(
        pack_id,
        ExportRequest(content_pack_id=pack_id, formats=["json"]),
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
        session=Session(),
    )

    assert accepted.status == "succeeded"
    assert accepted.deduplicated is True
