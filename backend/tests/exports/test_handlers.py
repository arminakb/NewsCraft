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
