from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError


def test_retention_job_payload_accepts_only_server_run_identity_and_token():
    from app.retention.handlers import RetentionJobPayload

    run_id = uuid4()
    payload = RetentionJobPayload.model_validate({"run_id": str(run_id), "preview_token": "a" * 64})

    assert payload.run_id == run_id
    assert payload.preview_token == "a" * 64
    with pytest.raises(ValidationError):
        RetentionJobPayload.model_validate(
            {
                "run_id": str(run_id),
                "preview_token": "a" * 64,
                "export_root": "/client/chosen/path",
            }
        )


@pytest.mark.asyncio
async def test_retention_handler_runs_database_phase_before_filesystem_with_owned_roots(
    monkeypatch,
    tmp_path,
):
    import app.retention.handlers as retention_handlers

    run_id = uuid4()
    token = "b" * 64
    calls: list[tuple] = []

    class Session:
        async def commit(self):
            calls.append(("commit",))

    session = Session()
    finished_run = SimpleNamespace(id=run_id, status="succeeded")

    class Service:
        def __init__(self, received_session):
            assert received_session is session

        async def execute_db_phase(
            self,
            received_run_id,
            received_token,
            *,
            export_root,
            media_root,
        ):
            calls.append(("database", received_run_id, received_token, export_root, media_root))
            return SimpleNamespace(run_id=received_run_id)

        async def finish_filesystem_phase(
            self,
            received_run_id,
            *,
            export_root,
            media_root,
        ):
            calls.append(("filesystem", received_run_id, export_root, media_root))
            return finished_run

    monkeypatch.setattr(
        retention_handlers,
        "_retention_service",
        lambda received_session: Service(received_session),
    )
    export_root = tmp_path / "exports"
    media_root = tmp_path / "media"
    handler = retention_handlers.build_retention_handler(
        export_root=export_root,
        media_root=media_root,
    )

    result = await handler(
        SimpleNamespace(payload={"run_id": str(run_id), "preview_token": token}),
        SimpleNamespace(session=session),
    )

    assert result == {"run_id": str(run_id), "status": "succeeded"}
    assert calls == [
        ("database", run_id, token, export_root, media_root),
        ("commit",),
        ("filesystem", run_id, export_root, media_root),
    ]


@pytest.mark.asyncio
async def test_retention_handler_rejects_client_paths_before_constructing_service(
    monkeypatch,
):
    import app.retention.handlers as retention_handlers
    from app.jobs.errors import PermanentJobError

    class Service:
        def __init__(self, _session):
            raise AssertionError("Invalid payload must not construct the retention service")

    monkeypatch.setattr(
        retention_handlers,
        "_retention_service",
        lambda received_session: Service(received_session),
    )
    handler = retention_handlers.build_retention_handler(
        export_root=Path("/owned/exports"),
        media_root=Path("/owned/media"),
    )

    with pytest.raises(PermanentJobError) as caught:
        await handler(
            SimpleNamespace(
                payload={
                    "run_id": str(uuid4()),
                    "preview_token": "c" * 64,
                    "media_root": "/client/chosen/path",
                }
            ),
            SimpleNamespace(session=object()),
        )

    assert caught.value.code == "retention_job_payload_invalid"


@pytest.mark.asyncio
async def test_retention_handler_maps_stale_preview_conflict_to_permanent_failure(
    monkeypatch,
):
    import app.retention.handlers as retention_handlers
    from app.jobs.errors import PermanentJobError
    from app.retention.service import RetentionConflict

    class Session:
        async def commit(self):
            raise AssertionError("A conflicting retention run must not commit")

    class Service:
        async def execute_db_phase(self, *_args, **_kwargs):
            raise RetentionConflict("preview token does not match persisted state")

        async def finish_filesystem_phase(self, *_args, **_kwargs):
            raise AssertionError("A conflicting retention run must not touch files")

    monkeypatch.setattr(
        retention_handlers,
        "_retention_service",
        lambda _session: Service(),
    )
    handler = retention_handlers.build_retention_handler(
        export_root=Path("/owned/exports"),
        media_root=Path("/owned/media"),
    )

    with pytest.raises(PermanentJobError) as caught:
        await handler(
            SimpleNamespace(payload={"run_id": str(uuid4()), "preview_token": "d" * 64}),
            SimpleNamespace(session=Session()),
        )

    assert caught.value.code == "retention_conflict"
    assert caught.value.message == "preview token does not match persisted state"


@pytest.mark.asyncio
async def test_retention_handler_retries_persisted_partial_filesystem_cleanup(
    monkeypatch,
    tmp_path,
):
    import app.retention.handlers as retention_handlers
    from app.jobs.errors import RetryableJobError

    run_id = uuid4()
    token = "e" * 64

    class Session:
        async def commit(self):
            return None

    class Service:
        async def execute_db_phase(self, *_args, **_kwargs):
            return SimpleNamespace(run_id=run_id)

        async def finish_filesystem_phase(self, *_args, **_kwargs):
            return SimpleNamespace(id=run_id, status="partial")

    monkeypatch.setattr(
        retention_handlers,
        "_retention_service",
        lambda _session: Service(),
    )
    handler = retention_handlers.build_retention_handler(
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )

    with pytest.raises(RetryableJobError) as caught:
        await handler(
            SimpleNamespace(payload={"run_id": str(run_id), "preview_token": token}),
            SimpleNamespace(session=Session()),
        )

    assert caught.value.code == "retention_cleanup_partial"
    assert caught.value.message == "Retention filesystem cleanup remains partial"
