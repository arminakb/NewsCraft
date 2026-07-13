from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.main import app


def _artifact(*, export_id=None, pack_id=None, finished_at=None):
    import hashlib
    import json

    from app.exports.models import ExportArtifact, ExportManifest, ExportVariantIdentity

    export_id = export_id or uuid4()
    pack_id = pack_id or uuid4()
    revision_id, variant_id = uuid4(), uuid4()
    manifest = ExportManifest(
        content_pack_id=pack_id,
        story_revision_id=uuid4(),
        created_at=finished_at or datetime(2026, 7, 13, tzinfo=UTC),
        variants=[
            ExportVariantIdentity(
                platform="blog",
                platform_variant_id=variant_id,
                revision_id=revision_id,
                content_hash="c" * 64,
                approval_state="approved",
                evidence_urls=[],
            )
        ],
        files=[],
    )
    checksum = hashlib.sha256(
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ExportArtifact(
        export_id=export_id,
        content_pack_id=pack_id,
        state="complete",
        manifest_file="manifest.json",
        manifest_sha256=checksum,
        archive_file="bundle.zip",
        archive_sha256="b" * 64,
        manifest=manifest,
    )


def _payload_for_artifact(artifact):
    from app.exports.models import BuildExportPayload

    variants = artifact.manifest.variants
    formats = []
    for kind in ("json", "markdown", "html"):
        if any(item.kind == kind for item in artifact.manifest.files):
            formats.append(kind)
    if artifact.archive_file is not None:
        formats.append("zip")
    return BuildExportPayload(
        content_pack_id=artifact.content_pack_id,
        revision_ids=[item.revision_id for item in variants],
        revision_hashes=[item.content_hash for item in variants],
        platforms=[item.platform for item in variants],
        platform_variant_ids=[item.platform_variant_id for item in variants],
        formats=formats,
        include_media=any(item.kind == "media" for item in artifact.manifest.files),
    )


def test_export_routes_are_registered_with_safe_public_contracts():
    operations = {(path, method.upper()) for path, row in app.openapi()["paths"].items() for method in row}
    assert {
        ("/content-packs/{pack_id}/exports", "POST"),
        ("/exports", "GET"),
        ("/exports/{export_id}", "GET"),
        ("/exports/{export_id}/download/{file_name}", "GET"),
    } <= operations


@pytest.mark.asyncio
async def test_post_freezes_exact_revision_payload_and_semantic_idempotency(monkeypatch, tmp_path):
    from app.api.exports import create_export, export_idempotency_key
    from app.exports.models import BuildExportPayload, ExportRequest

    pack_id, revision_id, variant_id, job_id = uuid4(), uuid4(), uuid4(), uuid4()
    payload = BuildExportPayload(
        content_pack_id=pack_id,
        revision_ids=[revision_id],
        revision_hashes=["a" * 64],
        platforms=["blog"],
        platform_variant_ids=[variant_id],
        formats=["json", "zip"],
        include_media=True,
    )
    observed = {}

    class Service:
        def __init__(self, session, *, export_root, media_root):
            observed["roots"] = (export_root, media_root)

        async def prepare_payload(self, request):
            observed["request"] = request
            return payload

    class Repository:
        def __init__(self, session):
            pass

        async def enqueue_job(self, **kwargs):
            observed["enqueue"] = kwargs
            return SimpleNamespace(
                job=SimpleNamespace(id=job_id, status="queued"),
                created=True,
            )

    class Session:
        async def commit(self):
            observed["committed"] = True

    monkeypatch.setattr("app.api.exports.ExportService", Service)
    monkeypatch.setattr("app.api.exports.JobRepository", Repository)
    body = ExportRequest(
        content_pack_id=pack_id,
        revision_ids=[revision_id],
        formats=["zip", "json"],
        include_media=True,
    )

    output = await create_export(
        pack_id,
        body,
        session=Session(),
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )

    assert output.job_id == job_id
    assert observed["request"] == body
    assert observed["enqueue"]["job_type"] == "build_export"
    assert observed["enqueue"]["payload"] == payload.model_dump(mode="json")
    assert observed["enqueue"]["idempotency_key"] == export_idempotency_key(payload)
    import hashlib
    import json

    request_hash = hashlib.sha256(
        json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert observed["enqueue"]["idempotency_key"] == (f"build_export:{pack_id}:{'a' * 64}:{request_hash}")
    assert str(tmp_path) not in str(observed["enqueue"]["payload"])
    assert observed["committed"] is True


@pytest.mark.asyncio
async def test_post_rejects_body_pack_that_differs_from_path(tmp_path):
    from app.api.exports import create_export
    from app.exports.models import ExportRequest

    with pytest.raises(HTTPException) as caught:
        await create_export(
            uuid4(),
            ExportRequest(content_pack_id=uuid4(), formats=["json"]),
            session=object(),
            export_root=tmp_path,
            media_root=tmp_path,
        )
    assert caught.value.status_code == 409


def test_export_cursor_round_trips_finished_at_and_job_id_and_rejects_tampering():
    from app.api.exports import decode_export_cursor, encode_export_cursor

    finished_at = datetime(2026, 7, 13, 7, 2, 3, 456789, tzinfo=UTC)
    job_id = uuid4()
    cursor = encode_export_cursor(finished_at, job_id)

    assert decode_export_cursor(cursor) == (finished_at, job_id)
    with pytest.raises(ValueError):
        decode_export_cursor(cursor + "not-valid")


def test_export_projection_never_exposes_absolute_storage_paths():
    from app.api.exports import export_artifact_out
    from app.exports.models import ExportArtifact, ExportManifest

    export_id = uuid4()
    pack_id = uuid4()
    artifact = ExportArtifact(
        export_id=export_id,
        content_pack_id=pack_id,
        state="complete",
        manifest_file="manifest.json",
        manifest_sha256="a" * 64,
        archive_file="bundle.zip",
        archive_sha256="b" * 64,
        manifest=ExportManifest(
            content_pack_id=pack_id,
            story_revision_id=uuid4(),
            created_at=datetime(2026, 7, 13, tzinfo=UTC),
            variants=[],
            files=[],
        ),
    )
    job = SimpleNamespace(
        id=export_id,
        status="succeeded",
        finished_at=datetime(2026, 7, 13, tzinfo=UTC),
        error_code=None,
        error_message=None,
    )

    output = export_artifact_out(job, artifact)

    assert output.export_id == export_id
    assert output.downloads == [
        f"/exports/{export_id}/download/manifest.json",
        f"/exports/{export_id}/download/bundle.zip",
    ]
    assert "/data/exports" not in output.model_dump_json()


@pytest.mark.asyncio
async def test_export_list_uses_stable_tie_cursor_and_keeps_failed_rows_safe():
    from app.api.exports import decode_export_cursor, list_exports
    from app.exports.models import ExportArtifact

    finished_at = datetime(2026, 7, 13, 8, tzinfo=UTC)
    ids = sorted([uuid4(), uuid4(), uuid4()], reverse=True)
    succeeded = SimpleNamespace(
        id=ids[0],
        job_type="build_export",
        status="succeeded",
        finished_at=finished_at,
        result=_artifact(export_id=ids[0], finished_at=finished_at).model_dump(mode="json"),
        error_code=None,
        error_message=None,
    )
    succeeded.created_at = finished_at
    succeeded.payload = _payload_for_artifact(ExportArtifact.model_validate(succeeded.result)).model_dump(mode="json")
    failed = SimpleNamespace(
        id=ids[1],
        job_type="build_export",
        status="failed",
        finished_at=finished_at,
        result={"storage_path": "/data/exports/secret"},
        error_code="export_api_key=export-code-canary",
        error_message="token=do-not-leak",
    )
    overflow = SimpleNamespace(
        id=ids[2],
        job_type="build_export",
        status="failed",
        finished_at=finished_at,
        result={},
        error_code="later",
        error_message=None,
    )

    class Rows:
        def __iter__(self):
            return iter([succeeded, failed, overflow])

    class Session:
        async def scalars(self, statement):
            self.statement = statement
            return Rows()

    session = Session()
    output = await list_exports(cursor=None, limit=2, session=session)

    assert [item.export_id for item in output.items] == ids[:2]
    assert output.items[1].artifact is None
    assert "/data/exports" not in output.model_dump_json()
    assert "export-code-canary" not in output.items[1].error_code
    assert output.items[1].error_code == "export_api_key=[REDACTED]"
    assert "do-not-leak" not in output.items[1].error_message
    assert decode_export_cursor(output.next_cursor) == (finished_at, ids[1])
    assert "workflow_jobs.finished_at DESC" in str(session.statement)
    assert "workflow_jobs.id DESC" in str(session.statement)


@pytest.mark.asyncio
async def test_export_detail_authorizes_only_build_export_jobs():
    from app.api.exports import get_export

    export_id = uuid4()

    class Session:
        def __init__(self, job):
            self.job = job

        async def get(self, _model, _identifier):
            return self.job

    wrong = SimpleNamespace(id=export_id, job_type="other", status="succeeded")
    with pytest.raises(HTTPException) as caught:
        await get_export(export_id, session=Session(wrong))
    assert caught.value.status_code == 404

    artifact = _artifact(export_id=export_id)
    job = SimpleNamespace(
        id=export_id,
        job_type="build_export",
        status="succeeded",
        finished_at=artifact.manifest.created_at,
        result=artifact.model_dump(mode="json"),
        payload=_payload_for_artifact(artifact).model_dump(mode="json"),
        created_at=artifact.manifest.created_at,
        error_code=None,
        error_message=None,
    )
    assert (await get_export(export_id, session=Session(job))).artifact == artifact


@pytest.mark.asyncio
async def test_expired_export_detail_is_truthful_and_never_advertises_downloads():
    from app.api.exports import get_export
    from app.exports.models import BuildExportPayload

    export_id = uuid4()
    pack_id = uuid4()
    expired_at = datetime(2026, 7, 13, 9, tzinfo=UTC)
    job = SimpleNamespace(
        id=export_id,
        job_type="build_export",
        status="succeeded",
        finished_at=datetime(2026, 7, 1, tzinfo=UTC),
        result={
            "export_id": str(export_id),
            "content_pack_id": str(pack_id),
            "state": "expired",
            "expired_at": expired_at.isoformat(),
        },
        payload=BuildExportPayload(
            content_pack_id=pack_id,
            revision_ids=[uuid4()],
            revision_hashes=["a" * 64],
            platforms=["blog"],
            platform_variant_ids=[uuid4()],
            formats=["json"],
        ).model_dump(mode="json"),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        error_code=None,
        error_message=None,
    )

    class Session:
        async def get(self, _model, identifier):
            assert identifier == export_id
            return job

    output = await get_export(export_id, session=Session())

    assert output.status == "succeeded"
    assert output.downloads == []
    assert output.error_code == "export_expired"
    assert output.error_message == "Export artifact expired under retention policy"
    assert output.artifact is not None
    assert output.artifact.model_dump(mode="json") == {
        "export_id": str(export_id),
        "content_pack_id": str(pack_id),
        "state": "expired",
        "expired_at": expired_at.isoformat().replace("+00:00", "Z"),
    }


@pytest.mark.asyncio
async def test_expired_export_download_returns_gone_before_touching_storage(tmp_path):
    from app.api.exports import download_export
    from app.exports.models import BuildExportPayload

    export_id = uuid4()
    pack_id = uuid4()
    job = SimpleNamespace(
        id=export_id,
        job_type="build_export",
        status="succeeded",
        result={
            "export_id": str(export_id),
            "content_pack_id": str(pack_id),
            "state": "expired",
            "expired_at": datetime(2026, 7, 13, 9, tzinfo=UTC).isoformat(),
        },
        payload=BuildExportPayload(
            content_pack_id=pack_id,
            revision_ids=[uuid4()],
            revision_hashes=["a" * 64],
            platforms=["blog"],
            platform_variant_ids=[uuid4()],
            formats=["json"],
        ).model_dump(mode="json"),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )

    class Session:
        async def get(self, _model, identifier):
            assert identifier == export_id
            return job

    with pytest.raises(HTTPException) as caught:
        await download_export(
            export_id,
            "manifest.json",
            export_root=tmp_path / "missing-export-root",
            session=Session(),
        )

    assert caught.value.status_code == 410
    assert caught.value.detail == "Export artifact has expired"


@pytest.mark.asyncio
async def test_expired_export_tombstone_must_match_retained_job_payload_identity():
    from app.api.exports import get_export
    from app.exports.models import BuildExportPayload

    export_id = uuid4()
    job = SimpleNamespace(
        id=export_id,
        job_type="build_export",
        status="succeeded",
        finished_at=datetime(2026, 7, 1, tzinfo=UTC),
        result={
            "export_id": str(export_id),
            "content_pack_id": str(uuid4()),
            "state": "expired",
            "expired_at": datetime(2026, 7, 13, 9, tzinfo=UTC).isoformat(),
        },
        payload=BuildExportPayload(
            content_pack_id=uuid4(),
            revision_ids=[uuid4()],
            revision_hashes=["a" * 64],
            platforms=["blog"],
            platform_variant_ids=[uuid4()],
            formats=["json"],
        ).model_dump(mode="json"),
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
        error_code=None,
        error_message=None,
    )

    class Session:
        async def get(self, _model, _identifier):
            return job

    with pytest.raises(HTTPException) as caught:
        await get_export(export_id, session=Session())

    assert caught.value.status_code == 409
    assert caught.value.detail == "Expired export identity does not match its job"


def test_download_rejects_unlisted_nested_absolute_symlink_and_bad_checksum(tmp_path):
    from app.api.exports import resolve_export_download
    from app.exports.models import ExportArtifact, ExportFileIdentity, ExportManifest, ExportVariantIdentity

    export_id, revision_id = uuid4(), uuid4()
    export_dir = tmp_path / str(export_id)
    export_dir.mkdir()
    payload = b"safe"
    safe = export_dir / "copy.json"
    safe.write_bytes(payload)
    pack_id = uuid4()
    artifact = ExportArtifact(
        export_id=export_id,
        content_pack_id=pack_id,
        state="complete",
        manifest_file="manifest.json",
        manifest_sha256="a" * 64,
        archive_file=None,
        archive_sha256=None,
        manifest=ExportManifest(
            content_pack_id=pack_id,
            story_revision_id=uuid4(),
            created_at=datetime(2026, 7, 13, tzinfo=UTC),
            variants=[
                ExportVariantIdentity(
                    platform="blog",
                    platform_variant_id=uuid4(),
                    revision_id=revision_id,
                    content_hash="c" * 64,
                    approval_state="approved",
                    evidence_urls=[],
                )
            ],
            files=[
                ExportFileIdentity(
                    file_name="copy.json",
                    sha256=__import__("hashlib").sha256(payload).hexdigest(),
                    byte_length=len(payload),
                    kind="json",
                    platform="blog",
                    revision_id=revision_id,
                )
            ],
        ),
    )

    assert resolve_export_download(tmp_path, artifact, "copy.json") == safe
    for unsafe in ("../copy.json", "/etc/passwd", "nested/copy.json", "missing.json"):
        with pytest.raises(HTTPException):
            resolve_export_download(tmp_path, artifact, unsafe)
    safe.write_bytes(b"tampered")
    with pytest.raises(HTTPException):
        resolve_export_download(tmp_path, artifact, "copy.json")

    safe.write_bytes(payload)
    target = export_dir / "target.json"
    target.write_bytes(payload)
    safe.unlink()
    safe.symlink_to(target)
    with pytest.raises(HTTPException):
        resolve_export_download(tmp_path, artifact, "copy.json")


def test_download_accepts_exact_manifest_allowlisted_nested_name(tmp_path):
    from hashlib import sha256

    from app.api.exports import resolve_export_download
    from app.exports.models import ExportArtifact, ExportFileIdentity, ExportManifest, ExportVariantIdentity

    export_id, pack_id, revision_id = uuid4(), uuid4(), uuid4()
    file_name = f"blog/{revision_id}/content.json"
    target = tmp_path / str(export_id) / file_name
    target.parent.mkdir(parents=True)
    content = b"nested-safe"
    target.write_bytes(content)
    artifact = ExportArtifact(
        export_id=export_id,
        content_pack_id=pack_id,
        state="complete",
        manifest_file="manifest.json",
        manifest_sha256="a" * 64,
        archive_file=None,
        archive_sha256=None,
        manifest=ExportManifest(
            content_pack_id=pack_id,
            story_revision_id=uuid4(),
            created_at=datetime(2026, 7, 13, tzinfo=UTC),
            variants=[
                ExportVariantIdentity(
                    platform="blog",
                    platform_variant_id=uuid4(),
                    revision_id=revision_id,
                    content_hash="c" * 64,
                    approval_state="approved",
                    evidence_urls=[],
                )
            ],
            files=[
                ExportFileIdentity(
                    file_name=file_name,
                    sha256=sha256(content).hexdigest(),
                    byte_length=len(content),
                    kind="json",
                    platform="blog",
                    revision_id=revision_id,
                )
            ],
        ),
    )

    assert resolve_export_download(tmp_path, artifact, file_name) == target


@pytest.mark.asyncio
async def test_download_route_requires_succeeded_durable_job_and_sets_attachment(tmp_path):
    import json
    from hashlib import sha256

    from app.api.exports import download_export
    from app.exports.models import ExportArtifact, ExportFileIdentity, ExportManifest, ExportVariantIdentity

    export_id, pack_id, revision_id = uuid4(), uuid4(), uuid4()
    file_name = f"blog/{revision_id}/content.json"
    content = b"download"
    path = tmp_path / str(export_id) / file_name
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    artifact = ExportArtifact(
        export_id=export_id,
        content_pack_id=pack_id,
        state="complete",
        manifest_file="manifest.json",
        manifest_sha256="a" * 64,
        archive_file=None,
        archive_sha256=None,
        manifest=ExportManifest(
            content_pack_id=pack_id,
            story_revision_id=uuid4(),
            created_at=datetime(2026, 7, 13, tzinfo=UTC),
            variants=[
                ExportVariantIdentity(
                    platform="blog",
                    platform_variant_id=uuid4(),
                    revision_id=revision_id,
                    content_hash="c" * 64,
                    approval_state="approved",
                    evidence_urls=[],
                )
            ],
            files=[
                ExportFileIdentity(
                    file_name=file_name,
                    sha256=sha256(content).hexdigest(),
                    byte_length=len(content),
                    kind="json",
                    platform="blog",
                    revision_id=revision_id,
                )
            ],
        ),
    )
    artifact = artifact.model_copy(
        update={
            "manifest_sha256": sha256(
                json.dumps(
                    artifact.manifest.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        }
    )
    job = SimpleNamespace(
        id=export_id,
        job_type="build_export",
        status="succeeded",
        result=artifact.model_dump(mode="json"),
        payload=_payload_for_artifact(artifact).model_dump(mode="json"),
        created_at=artifact.manifest.created_at,
    )

    class Session:
        async def get(self, _model, _identifier):
            return job

    response = await download_export(export_id, file_name, session=Session(), export_root=tmp_path)

    assert Path(response.path) == path
    assert response.media_type == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")


def test_export_file_model_rejects_traversal_or_absolute_names():
    from pydantic import ValidationError

    from app.exports.models import ExportFileIdentity

    for file_name in ("../copy.json", "/tmp/copy.json", "blog\\copy.json"):
        with pytest.raises(ValidationError):
            ExportFileIdentity(
                file_name=file_name,
                sha256="a" * 64,
                byte_length=1,
                kind="json",
                platform="blog",
                revision_id=uuid4(),
            )
