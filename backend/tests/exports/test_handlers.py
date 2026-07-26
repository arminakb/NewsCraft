from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_build_export_handler_revalidates_immutable_revision_identity(monkeypatch, tmp_path):
    from app.exports.handlers import build_export_handler
    from app.exports.models import ExportArtifact, ExportManifest, ExportVariantIdentity

    revision_id = uuid4()
    pack_id = uuid4()
    export_id = uuid4()
    expected = ExportVariantIdentity(
        platform="blog",
        platform_variant_id=uuid4(),
        revision_id=revision_id,
        content_hash="a" * 64,
        approval_state="approved",
        evidence_urls=["https://example.com/report"],
    )
    artifact = ExportArtifact(
        export_id=export_id,
        content_pack_id=pack_id,
        state="complete",
        manifest_file="manifest.json",
        manifest_sha256="b" * 64,
        archive_file=None,
        archive_sha256=None,
        manifest=ExportManifest(
            content_pack_id=pack_id,
            story_revision_id=uuid4(),
            created_at=datetime(2026, 7, 13, tzinfo=UTC),
            variants=[expected],
            files=[],
        ),
    )
    observed = {}

    class Service:
        def __init__(self, session, *, export_root, media_root):
            observed["roots"] = (export_root, media_root)

        async def build_from_payload(self, payload, *, export_id, created_at):
            observed["payload"] = payload
            observed["export_id"] = export_id
            observed["created_at"] = created_at
            return artifact

    monkeypatch.setattr("app.exports.handlers.ExportService", Service)
    handler = build_export_handler(export_root=tmp_path / "exports", media_root=tmp_path / "media")
    job = SimpleNamespace(
        id=export_id,
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
        payload={
            "content_pack_id": str(pack_id),
            "revision_ids": [str(revision_id)],
            "revision_hashes": ["a" * 64],
            "platforms": ["blog"],
            "platform_variant_ids": [str(expected.platform_variant_id)],
            "formats": ["json"],
            "include_media": False,
        },
    )

    result = await handler(job, SimpleNamespace(session=object()))

    assert observed["export_id"] == export_id
    assert observed["created_at"] == job.created_at
    assert observed["payload"].revision_hashes == ["a" * 64]
    assert result == artifact.model_dump(mode="json")
    assert str(tmp_path) not in str(result)


@pytest.mark.asyncio
async def test_build_export_handler_hits_fault_after_complete_manifest_before_job_commit(
    monkeypatch,
    tmp_path,
):
    from app.exports.handlers import build_export_handler
    from app.exports.models import ExportArtifact, ExportManifest
    from qualification.faults import InjectedFault, ScriptedFaultInjector

    export_id = uuid4()
    pack_id = uuid4()
    artifact = ExportArtifact(
        export_id=export_id,
        content_pack_id=pack_id,
        state="complete",
        manifest_file="manifest.json",
        manifest_sha256="b" * 64,
        archive_file=None,
        archive_sha256=None,
        manifest=ExportManifest(
            content_pack_id=pack_id,
            story_revision_id=uuid4(),
            created_at=datetime(2026, 7, 13, tzinfo=UTC),
            variants=[],
            files=[],
        ),
    )

    class Service:
        def __init__(self, session, *, export_root, media_root):
            pass

        async def build_from_payload(self, payload, *, export_id, created_at):
            return artifact

    monkeypatch.setattr("app.exports.handlers.ExportService", Service)
    injector = ScriptedFaultInjector({"export.after_manifest_before_commit": 1})
    handler = build_export_handler(
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
        fault_injector=injector,
    )
    job = SimpleNamespace(
        id=export_id,
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
        payload={
            "content_pack_id": str(pack_id),
            "revision_ids": [str(uuid4())],
            "revision_hashes": ["a" * 64],
            "platforms": ["blog"],
            "platform_variant_ids": [str(uuid4())],
            "formats": ["json"],
            "include_media": False,
        },
    )

    with pytest.raises(InjectedFault):
        await handler(job, SimpleNamespace(session=object()))

    assert injector.hits[0].point == "export.after_manifest_before_commit"
    assert dict(injector.hits[0].context) == {
        "export_id": str(export_id),
        "content_pack_id": str(pack_id),
    }


@pytest.mark.asyncio
async def test_export_crash_after_real_manifest_retries_without_duplicate_artifact(tmp_path):
    from app.exports.handlers import build_export_handler
    from app.exports.models import ExportRequest
    from app.exports.service import ExportService
    from qualification.faults import InjectedFault, ScriptedFaultInjector
    from tests.exports.test_service import FIXED_NOW, _ExportSession, _pack_fixture

    pack, variants, revisions = _pack_fixture()
    session = _ExportSession(pack=pack, variants=variants, revisions=revisions)
    export_root = tmp_path / "exports"
    media_root = tmp_path / "media"
    payload = await ExportService(
        session,
        export_root=export_root,
        media_root=media_root,
    ).prepare_payload(
        ExportRequest(
            content_pack_id=pack.id,
            formats=["json", "zip"],
        )
    )
    export_id = uuid4()
    job = SimpleNamespace(
        id=export_id,
        created_at=FIXED_NOW,
        payload=payload.model_dump(mode="json"),
    )
    injector = ScriptedFaultInjector({"export.after_manifest_before_commit": 1})

    with pytest.raises(InjectedFault):
        await build_export_handler(
            export_root=export_root,
            media_root=media_root,
            fault_injector=injector,
        )(job, SimpleNamespace(session=session))

    target = export_root / str(export_id)
    assert target.is_dir()
    assert (target / "manifest.json").is_file()
    package_before = {
        path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()
    }

    healthy = build_export_handler(export_root=export_root, media_root=media_root)
    first_replay = await healthy(job, SimpleNamespace(session=session))
    second_replay = await healthy(job, SimpleNamespace(session=session))

    package_after = {
        path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()
    }
    assert first_replay == second_replay
    assert package_after == package_before
    assert first_replay["manifest_sha256"]
    assert len([path for path in export_root.iterdir() if path.is_dir()]) == 1
    assert not list(export_root.glob(f".{export_id}.*.tmp"))


@pytest.mark.asyncio
async def test_build_export_handler_rejects_malformed_payload_before_storage(tmp_path):
    from app.exports.handlers import build_export_handler
    from app.jobs.errors import PermanentJobError

    handler = build_export_handler(export_root=tmp_path / "exports", media_root=tmp_path / "media")
    job = SimpleNamespace(
        id=uuid4(),
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
        payload={"content_pack_id": str(uuid4())},
    )

    with pytest.raises(PermanentJobError) as caught:
        await handler(job, SimpleNamespace(session=object()))
    assert caught.value.code == "export_job_payload_invalid"


@pytest.mark.asyncio
async def test_build_export_handler_maps_revalidation_failure_to_stable_permanent_error(
    monkeypatch,
    tmp_path,
):
    from app.exports.handlers import build_export_handler
    from app.exports.service import ExportContractError
    from app.jobs.errors import PermanentJobError

    class Service:
        def __init__(self, session, *, export_root, media_root):
            assert export_root == tmp_path / "exports"
            assert media_root == tmp_path / "media"

        async def build_from_payload(self, payload, *, export_id, created_at):
            raise ExportContractError(
                "queued revision hash no longer matches",
                code="export_revision_identity_mismatch",
            )

    monkeypatch.setattr("app.exports.handlers.ExportService", Service)
    handler = build_export_handler(export_root=tmp_path / "exports", media_root=tmp_path / "media")
    job = SimpleNamespace(
        id=uuid4(),
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
        payload={
            "content_pack_id": str(uuid4()),
            "revision_ids": [str(uuid4())],
            "revision_hashes": ["a" * 64],
            "platforms": ["blog"],
            "platform_variant_ids": [str(uuid4())],
            "formats": ["json"],
            "include_media": False,
        },
    )

    with pytest.raises(PermanentJobError) as caught:
        await handler(job, SimpleNamespace(session=object()))
    assert caught.value.code == "export_revision_identity_mismatch"
    assert str(tmp_path) not in str(caught.value)
