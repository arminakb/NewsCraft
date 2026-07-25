from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

FIXED_NOW = datetime(2026, 7, 13, 8, 30, tzinfo=UTC)


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _ExportSession:
    def __init__(self, *, pack, variants, revisions, assets=()):
        from app.db.models import MediaAsset
        from app.generation.models import ContentPack

        self.pack = pack
        self.variants = list(variants)
        self.revisions = list(revisions)
        self.assets = {asset.id: asset for asset in assets}
        self.models = {ContentPack: {pack.id: pack}, MediaAsset: self.assets}

    async def get(self, model, identifier):
        return self.models.get(model, {}).get(identifier)

    async def scalars(self, statement):
        sql = str(statement)
        if "FROM platform_variants" in sql:
            return _ScalarRows(self.variants)
        if "FROM platform_variant_revisions" in sql:
            return _ScalarRows(self.revisions)
        raise AssertionError(f"unexpected export query: {sql}")


def _telegram_content(body: str = "Grounded release copy") -> dict:
    return {
        "body": body,
        "parse_mode": "HTML",
        "buttons": [],
        "source_item_id": None,
        "source_url": None,
        "media_policy": "omit",
        "media_asset_ids": [],
        "direction": "rtl",
        "dry_run": False,
    }


def _blog_content(body: str) -> dict:
    snapshot_id = uuid4()
    citation = {
        "evidence_key": "source:one",
        "evidence_snapshot_id": str(snapshot_id),
        "source_url": "https://example.com/report",
        "locator": "chars:0-12",
        "excerpt_sha256": "a" * 64,
    }
    return {
        "title": "Grounded report",
        "slug": "grounded-report",
        "excerpt": "A grounded report excerpt.",
        "body_markdown": body,
        "headings": ["Evidence"],
        "citations": [citation],
        "tags": ["news"],
        "seo_description": "A grounded description for a deterministic NewsCraft export package.",
        "hero_media": None,
        "canonical_sources": ["https://example.com/report"],
        "manual_checklist": ["Verify source links"],
    }


def _pack_fixture(*, blog_body: str | None = None):
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision

    pack = ContentPack(
        id=uuid4(),
        story_revision_id=uuid4(),
        brand_profile_id=uuid4(),
        status="draft",
    )
    telegram = PlatformVariant(id=uuid4(), content_pack_id=pack.id, platform="telegram")
    blog = PlatformVariant(id=uuid4(), content_pack_id=pack.id, platform="blog")
    telegram_content = _telegram_content()
    blog_content = _blog_content(
        blog_body or ("## Evidence\n\n[Source](https://example.com/report) " + "grounded " * 180)
    )
    revisions = [
        PlatformVariantRevision(
            id=uuid4(),
            platform_variant_id=telegram.id,
            parent_revision_id=None,
            generation_attempt_id=None,
            revision_number=1,
            content=telegram_content,
            content_hash=sha256_canonical({"content": telegram_content, "evidence_map": []}),
            evidence_map=[],
            validation_results=[],
            approval_state="approved",
            approved_at=FIXED_NOW,
            created_by="test",
        ),
        PlatformVariantRevision(
            id=uuid4(),
            platform_variant_id=blog.id,
            parent_revision_id=None,
            generation_attempt_id=None,
            revision_number=1,
            content=blog_content,
            content_hash=sha256_canonical({"content": blog_content, "evidence_map": []}),
            evidence_map=[],
            validation_results=[],
            approval_state="approved",
            approved_at=FIXED_NOW,
            created_by="test",
        ),
    ]
    return pack, [telegram, blog], revisions


def _revision_for(variant, content: dict, revision_number: int, *, approval_state: str = "approved"):
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.models import PlatformVariantRevision

    evidence_map = []
    return PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=revision_number,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
        evidence_map=evidence_map,
        validation_results=[],
        approval_state=approval_state,
        approved_at=FIXED_NOW if approval_state == "approved" else None,
        created_by="test",
    )


def _rehash(revision) -> None:
    from app.automations.telegram.handlers import sha256_canonical

    revision.content_hash = sha256_canonical({"content": revision.content, "evidence_map": revision.evidence_map})


def _canonical_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@pytest.mark.asyncio
async def test_export_manifest_binds_every_file_to_exact_revision_and_hash(monkeypatch, tmp_path):
    from app.exports.models import ExportRequest
    from app.exports.service import ExportService

    pack, variants, revisions = _pack_fixture()
    service = ExportService(
        _ExportSession(pack=pack, variants=variants, revisions=revisions),
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )
    export_id = uuid4()
    writes: list[str] = []
    original_write_bytes = Path.write_bytes

    def tracked_write_bytes(path: Path, content: bytes) -> int:
        writes.append(path.name)
        return original_write_bytes(path, content)

    monkeypatch.setattr(Path, "write_bytes", tracked_write_bytes)

    artifact = await service.build(
        ExportRequest(
            content_pack_id=pack.id,
            formats=["json", "markdown", "html", "zip"],
            include_media=True,
        ),
        export_id=export_id,
        created_at=FIXED_NOW,
    )

    manifest = artifact.manifest
    assert manifest.content_pack_id == pack.id
    assert manifest.story_revision_id == pack.story_revision_id
    assert [item.platform for item in manifest.variants] == ["telegram", "blog"]
    assert {item.revision_id for item in manifest.variants} == {value.id for value in revisions}
    assert {item.content_hash for item in manifest.variants} == {value.content_hash for value in revisions}
    assert all(item.approval_state == "approved" for item in manifest.variants)
    assert manifest.variants[1].evidence_urls == ["https://example.com/report"]
    assert manifest.files
    assert [(item.platform, item.kind) for item in manifest.files] == [
        ("telegram", "json"),
        ("telegram", "markdown"),
        ("telegram", "html"),
        ("blog", "json"),
        ("blog", "markdown"),
        ("blog", "html"),
    ]
    assert all(item.sha256 for item in manifest.files)
    assert all(
        not Path(item.file_name).is_absolute() and ".." not in Path(item.file_name).parts for item in manifest.files
    )
    assert artifact.manifest_file == "manifest.json"
    assert artifact.archive_file == "bundle.zip"
    assert artifact.archive_sha256
    assert {item.file_name for item in manifest.files}.isdisjoint({"manifest.json", "bundle.zip"})
    assert str(tmp_path) not in json.dumps(artifact.model_dump(mode="json"), sort_keys=True)

    root = tmp_path / "exports" / str(export_id)
    for item in manifest.files:
        content = (root / item.file_name).read_bytes()
        assert sha256(content).hexdigest() == item.sha256
        if item.kind == "json":
            assert content == _canonical_json(json.loads(content))
    blog_markdown = next(
        (root / item.file_name).read_text(encoding="utf-8")
        for item in manifest.files
        if item.platform == "blog" and item.kind == "markdown"
    )
    for expected in (
        "Grounded report",
        "A grounded report excerpt.",
        "Verify source links",
        "https://example.com/report",
    ):
        assert expected in blog_markdown
    assert json.loads((root / "manifest.json").read_text(encoding="utf-8"))["schema_version"] == "newscraft-export-v1"
    assert writes[-1] == "manifest.json"
    assert sha256((root / "bundle.zip").read_bytes()).hexdigest() == artifact.archive_sha256
    with zipfile.ZipFile(root / "bundle.zip") as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert "manifest.json" in names
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
        assert all(info.compress_type == zipfile.ZIP_DEFLATED for info in archive.infolist())
        assert all(((info.external_attr >> 16) & 0o777) == 0o644 for info in archive.infolist())


@pytest.mark.asyncio
async def test_export_retry_reuses_only_a_complete_checksummed_artifact(tmp_path):
    from app.exports.models import ExportRequest
    from app.exports.service import ExportService

    pack, variants, revisions = _pack_fixture()
    export_id = uuid4()
    request = ExportRequest(content_pack_id=pack.id, formats=["json"])
    first = await ExportService(
        _ExportSession(pack=pack, variants=variants, revisions=revisions),
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    ).build(request, export_id=export_id, created_at=FIXED_NOW)

    target = tmp_path / "exports" / str(export_id)
    manifest_path = target / "manifest.json"
    incomplete_manifest = json.loads(manifest_path.read_bytes())
    removed = incomplete_manifest["files"].pop()
    (target / removed["file_name"]).unlink()
    manifest_path.write_bytes(_canonical_json(incomplete_manifest))

    second = await ExportService(
        _ExportSession(pack=pack, variants=variants, revisions=revisions),
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    ).build(request, export_id=export_id, created_at=FIXED_NOW)

    assert second == first
    assert (target / removed["file_name"]).is_file()
    assert not list((tmp_path / "exports").glob(f".{export_id}.*.tmp"))


@pytest.mark.asyncio
async def test_independent_exports_have_identical_bytes_and_never_embed_job_or_root(tmp_path):
    from app.exports.models import ExportRequest
    from app.exports.service import ExportService

    pack, variants, revisions = _pack_fixture()
    request = ExportRequest(
        content_pack_id=pack.id,
        formats=["zip", "html", "json", "markdown"],
    )
    export_ids = [uuid4(), uuid4()]
    artifacts = []
    for export_id in export_ids:
        artifacts.append(
            await ExportService(
                _ExportSession(pack=pack, variants=variants, revisions=revisions),
                export_root=tmp_path / "exports",
                media_root=tmp_path / "media",
            ).build(request, export_id=export_id, created_at=FIXED_NOW)
        )

    def package_bytes(export_id):
        root = tmp_path / "exports" / str(export_id)
        return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    first_package = package_bytes(export_ids[0])
    assert first_package == package_bytes(export_ids[1])
    assert artifacts[0].manifest == artifacts[1].manifest
    assert artifacts[0].archive_sha256 == artifacts[1].archive_sha256
    serialized = json.dumps(artifacts[0].model_dump(mode="json"), sort_keys=True)
    assert str(tmp_path) not in serialized
    package_content = b"".join(first_package.values())
    assert all(str(export_id).encode() not in package_content for export_id in export_ids)


@pytest.mark.asyncio
async def test_selection_freezes_highest_revision_and_worker_never_substitutes_newer(tmp_path):
    from app.exports.models import ExportRequest
    from app.exports.service import ExportContractError, ExportService

    pack, variants, revisions = _pack_fixture()
    old_telegram = revisions[0]
    new_telegram = _revision_for(variants[0], _telegram_content("New current copy"), 2)
    all_revisions = [revisions[1], old_telegram, new_telegram]

    service = ExportService(
        _ExportSession(pack=pack, variants=variants, revisions=all_revisions),
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )
    current_payload = await service.prepare_payload(ExportRequest(content_pack_id=pack.id, formats=["json"]))
    assert current_payload.revision_ids == [new_telegram.id, revisions[1].id]

    exact_payload = await service.prepare_payload(
        ExportRequest(
            content_pack_id=pack.id,
            revision_ids=[revisions[1].id, old_telegram.id],
            formats=["json"],
        )
    )
    assert exact_payload.revision_ids == [old_telegram.id, revisions[1].id]
    artifact = await service.build_from_payload(
        exact_payload,
        export_id=uuid4(),
        created_at=FIXED_NOW,
    )
    assert [item.revision_id for item in artifact.manifest.variants] == [
        old_telegram.id,
        revisions[1].id,
    ]

    with pytest.raises(ExportContractError, match="every.*variant|one revision"):
        await service.prepare_payload(
            ExportRequest(
                content_pack_id=pack.id,
                revision_ids=[old_telegram.id],
                formats=["json"],
            )
        )

    drifted = exact_payload.model_copy(update={"revision_hashes": ["f" * 64, *exact_payload.revision_hashes[1:]]})
    with pytest.raises(ExportContractError, match="identity"):
        await service.build_from_payload(
            drifted,
            export_id=uuid4(),
            created_at=FIXED_NOW,
        )


@pytest.mark.asyncio
async def test_selection_rejects_foreign_schema_invalid_and_hash_drifted_revisions(tmp_path):
    from app.exports.models import ExportRequest
    from app.exports.service import ExportContractError, ExportService

    pack, variants, revisions = _pack_fixture()

    with pytest.raises(ExportContractError, match="belong"):
        await ExportService(
            _ExportSession(pack=pack, variants=variants, revisions=revisions),
            export_root=tmp_path / "foreign-exports",
            media_root=tmp_path / "media",
        ).prepare_payload(
            ExportRequest(
                content_pack_id=pack.id,
                revision_ids=[revisions[0].id, uuid4()],
                formats=["json"],
            )
        )

    invalid_pack, invalid_variants, invalid_revisions = _pack_fixture()
    invalid_revisions[1].content["title"] = ""
    _rehash(invalid_revisions[1])
    with pytest.raises(ExportContractError, match="schema-valid"):
        await ExportService(
            _ExportSession(
                pack=invalid_pack,
                variants=invalid_variants,
                revisions=invalid_revisions,
            ),
            export_root=tmp_path / "schema-exports",
            media_root=tmp_path / "media",
        ).prepare_payload(ExportRequest(content_pack_id=invalid_pack.id, formats=["json"]))

    drift_pack, drift_variants, drift_revisions = _pack_fixture()
    drift_revisions[0].content["body"] = "Tampered without a new immutable hash"
    with pytest.raises(ExportContractError, match="hash"):
        await ExportService(
            _ExportSession(
                pack=drift_pack,
                variants=drift_variants,
                revisions=drift_revisions,
            ),
            export_root=tmp_path / "drift-exports",
            media_root=tmp_path / "media",
        ).prepare_payload(ExportRequest(content_pack_id=drift_pack.id, formats=["json"]))


def test_blog_html_is_sanitized_and_keeps_resolved_citation_links(tmp_path):
    from app.exports.service import ExportService, render_export_html

    malicious = (
        "## Evidence\n\n<script>alert(1)</script> [Source](https://example.com/report) "
        "[Unsafe](javascript:alert(2)) " + "grounded " * 180
    )
    pack, variants, revisions = _pack_fixture(blog_body=malicious)
    service = ExportService(
        _ExportSession(pack=pack, variants=variants, revisions=revisions),
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )

    html = service.render_html("blog", revisions[1].content)

    assert html == render_export_html("blog", revisions[1].content)
    assert "<h2>Evidence</h2>" in html
    assert "<script" not in html
    assert 'href="javascript:' not in html
    assert 'href="https://example.com/report"' in html
    assert "grounded" in html
    assert "Grounded report" not in html
    assert "A grounded report excerpt." not in html
    assert "Verify source links" not in html
    assert "Complete package data" not in html


@pytest.mark.asyncio
async def test_export_rejects_duplicate_unapproved_or_foreign_explicit_revisions(tmp_path):
    from app.exports.models import ExportRequest
    from app.exports.service import ExportContractError, ExportService

    pack, variants, revisions = _pack_fixture()
    revisions[1].approval_state = "pending_review"
    service = ExportService(
        _ExportSession(pack=pack, variants=variants, revisions=revisions),
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )
    with pytest.raises(ExportContractError, match="unique"):
        await service.build(
            ExportRequest(
                content_pack_id=pack.id,
                revision_ids=[revisions[0].id, revisions[0].id],
                formats=["json"],
            ),
            export_id=uuid4(),
            created_at=FIXED_NOW,
        )

    service = ExportService(
        _ExportSession(pack=pack, variants=variants, revisions=revisions),
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
    )
    with pytest.raises(ExportContractError, match="approved"):
        await service.build(
            ExportRequest(content_pack_id=pack.id, formats=["json"]),
            export_id=uuid4(),
            created_at=FIXED_NOW,
        )


@pytest.mark.asyncio
async def test_media_export_skips_manual_assignment_and_rejects_tampered_storage(tmp_path):
    from app.db.models import MediaAsset
    from app.exports.models import ExportRequest
    from app.exports.service import ExportContractError, ExportService

    media_root = tmp_path / "media"
    media_root.mkdir()
    media_bytes = b"validated-media"
    media_path = media_root / "asset.jpg"
    media_path.write_bytes(media_bytes)
    asset_id = uuid4()
    asset = MediaAsset(
        id=asset_id,
        original_url="https://example.com/asset.jpg",
        normalized_url="https://example.com/asset.jpg",
        url_hash="a" * 64,
        kind="image",
        mime_type="image/jpeg",
        source_field="test",
        checksum_sha256=sha256(media_bytes).hexdigest(),
        storage_path=str(media_path),
        fetch_status="downloaded",
    )
    pack, variants, revisions = _pack_fixture()
    revisions[1].content["hero_media"] = {
        "media_asset_id": str(asset_id),
        "role": "hero",
        "order": 1,
        "alt_text": "Grounded image",
        "manual_brief": None,
        "image_prompt": None,
    }
    _rehash(revisions[1])
    request = ExportRequest(content_pack_id=pack.id, formats=["json"], include_media=True)

    artifact = await ExportService(
        _ExportSession(pack=pack, variants=variants, revisions=revisions, assets=[asset]),
        export_root=tmp_path / "exports",
        media_root=media_root,
    ).build(request, export_id=uuid4(), created_at=FIXED_NOW)
    media_entry = next(item for item in artifact.manifest.files if item.kind == "media")
    copied = tmp_path / "exports" / str(artifact.export_id) / media_entry.file_name
    assert copied.read_bytes() == media_bytes
    assert media_entry.sha256 == asset.checksum_sha256

    media_path.write_bytes(b"tampered")
    with pytest.raises(ExportContractError, match="checksum"):
        await ExportService(
            _ExportSession(pack=pack, variants=variants, revisions=revisions, assets=[asset]),
            export_root=tmp_path / "other-exports",
            media_root=media_root,
        ).build(request, export_id=uuid4(), created_at=FIXED_NOW)

    manual_pack, manual_variants, manual_revisions = _pack_fixture()
    manual_revisions[1].content["hero_media"] = {
        "media_asset_id": None,
        "role": "hero",
        "order": 1,
        "alt_text": "Create a grounded image manually",
        "manual_brief": "Use a source-backed editorial illustration",
        "image_prompt": None,
    }
    _rehash(manual_revisions[1])
    manual_artifact = await ExportService(
        _ExportSession(
            pack=manual_pack,
            variants=manual_variants,
            revisions=manual_revisions,
        ),
        export_root=tmp_path / "manual-exports",
        media_root=media_root,
    ).build(
        ExportRequest(content_pack_id=manual_pack.id, formats=["json"], include_media=True),
        export_id=uuid4(),
        created_at=FIXED_NOW,
    )
    assert all(item.kind != "media" for item in manual_artifact.manifest.files)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("missing", "missing"),
        ("not_downloaded", "download"),
        ("invalid_checksum", "checksum"),
        ("length", "length"),
        ("directory", "regular file"),
        ("escape", "escape"),
        ("symlink", "symlink"),
    ],
)
@pytest.mark.asyncio
async def test_media_export_rejects_untrusted_storage_shapes(case, message, tmp_path):
    from app.db.models import MediaAsset
    from app.exports.models import ExportRequest
    from app.exports.service import ExportContractError, ExportService

    media_root = tmp_path / "media"
    media_root.mkdir()
    media_bytes = b"validated-media"
    media_path = media_root / "asset.jpg"
    media_path.write_bytes(media_bytes)
    fetch_status = "downloaded"
    checksum = sha256(media_bytes).hexdigest()
    byte_length = len(media_bytes)

    if case == "missing":
        media_path.unlink()
    elif case == "not_downloaded":
        fetch_status = "pending"
    elif case == "invalid_checksum":
        checksum = "not-a-sha256"
    elif case == "length":
        byte_length += 1
    elif case == "directory":
        media_path.unlink()
        media_path.mkdir()
    elif case == "escape":
        media_path = tmp_path / "outside.jpg"
        media_path.write_bytes(media_bytes)
    elif case == "symlink":
        target_dir = tmp_path / "real-media"
        target_dir.mkdir()
        (target_dir / "asset.jpg").write_bytes(media_bytes)
        linked_dir = media_root / "linked"
        linked_dir.symlink_to(target_dir, target_is_directory=True)
        media_path = linked_dir / "asset.jpg"

    asset_id = uuid4()
    asset = MediaAsset(
        id=asset_id,
        original_url="https://example.com/asset.jpg",
        normalized_url="https://example.com/asset.jpg",
        url_hash="a" * 64,
        kind="image",
        mime_type="image/jpeg",
        byte_length=byte_length,
        source_field="test",
        checksum_sha256=checksum,
        storage_path=str(media_path),
        fetch_status=fetch_status,
    )
    pack, variants, revisions = _pack_fixture()
    revisions[1].content["hero_media"] = {
        "media_asset_id": str(asset_id),
        "role": "hero",
        "order": 1,
        "alt_text": "Grounded image",
        "manual_brief": None,
        "image_prompt": None,
    }
    _rehash(revisions[1])

    with pytest.raises(ExportContractError, match=message):
        await ExportService(
            _ExportSession(pack=pack, variants=variants, revisions=revisions, assets=[asset]),
            export_root=tmp_path / "exports",
            media_root=media_root,
        ).build(
            ExportRequest(content_pack_id=pack.id, formats=["json"], include_media=True),
            export_id=uuid4(),
            created_at=FIXED_NOW,
        )


def test_export_request_forbids_unknown_fields_and_empty_formats():
    from pydantic import ValidationError

    from app.exports.models import ExportRequest

    with pytest.raises(ValidationError):
        ExportRequest(content_pack_id=uuid4(), formats=[], arbitrary_root="/tmp")
    with pytest.raises(ValidationError):
        ExportRequest(content_pack_id=uuid4(), formats=["pdf"])
    with pytest.raises(ValidationError):
        ExportRequest(content_pack_id=uuid4(), revision_ids=[], formats=["json"])
    with pytest.raises(ValidationError):
        ExportRequest(content_pack_id=uuid4(), formats=["json", "json"])
    assert ExportRequest(content_pack_id=uuid4(), formats=["json"]).revision_ids is None


def test_export_value_objects_are_pydantic_only_not_orm_models():
    from pydantic import BaseModel

    from app.exports.models import ExportArtifact, ExportManifest, ExportRequest

    assert all(issubclass(model, BaseModel) for model in (ExportRequest, ExportManifest, ExportArtifact))
    assert all(not hasattr(model, "__tablename__") for model in (ExportRequest, ExportManifest, ExportArtifact))
