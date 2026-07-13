from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import zipfile
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4

import markdown
import nh3
from pydantic import ValidationError
from sqlalchemy import case, select

from app.db.models import MediaAsset
from app.exports.models import (
    BuildExportPayload,
    ExportArtifact,
    ExportFileIdentity,
    ExportManifest,
    ExportRequest,
    ExportVariantIdentity,
)
from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
from app.generation.multiplatform import MANUAL_PLATFORM_ADAPTERS, PLATFORM_ORDER
from app.generation.platform_renderers import render_platform_markdown
from app.generation.platform_schemas import Platform, PlatformPayload, TelegramVariantPayload
from app.generation.platform_validation import validate_platform_payload

FORMAT_ORDER = ("json", "markdown", "html", "zip")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MANIFEST_FILE = "manifest.json"
ARCHIVE_FILE = "bundle.zip"


class ExportContractError(ValueError):
    def __init__(self, message: str, *, code: str = "export_contract_invalid") -> None:
        super().__init__(message)
        self.code = code


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_hash(revision: PlatformVariantRevision) -> str:
    return _sha256_bytes(
        _canonical_json_bytes(
            {
                "content": revision.content,
                "evidence_map": revision.evidence_map,
            }
        )
    )


def _platform_index(platform: str) -> int:
    try:
        return PLATFORM_ORDER.index(platform)  # type: ignore[arg-type]
    except ValueError:
        raise ExportContractError(f"unsupported platform: {platform}") from None


def _evidence_urls(revision: PlatformVariantRevision) -> list[str]:
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            source_url = value.get("source_url")
            if isinstance(source_url, str) and source_url.strip():
                found.add(source_url.strip())
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(revision.evidence_map)
    visit(revision.content)
    return sorted(found)


def _payload_model(platform: Platform, content: dict[str, Any]) -> PlatformPayload:
    adapter = TelegramVariantPayload if platform == "telegram" else MANUAL_PLATFORM_ADAPTERS[platform]
    try:
        payload = adapter.model_validate(content)
    except ValidationError as exc:
        raise ExportContractError(
            f"{platform} revision content is not schema-valid",
            code="export_revision_schema_invalid",
        ) from exc
    issues = validate_platform_payload(platform, payload)
    if any(issue.severity == "error" for issue in issues):
        raise ExportContractError(
            f"{platform} revision has failed platform validation",
            code="export_revision_validation_failed",
        )
    return payload


def _identity(
    variant: PlatformVariant,
    revision: PlatformVariantRevision,
) -> ExportVariantIdentity:
    if revision.approval_state != "approved":
        raise ExportContractError(
            "all exported revisions must be approved",
            code="export_revision_not_approved",
        )
    if revision.content_hash != _content_hash(revision):
        raise ExportContractError(
            "revision content hash does not match its immutable content",
            code="export_revision_hash_mismatch",
        )
    platform: Platform = variant.platform  # type: ignore[assignment]
    _payload_model(platform, revision.content)
    return ExportVariantIdentity(
        platform=platform,
        platform_variant_id=variant.id,
        revision_id=revision.id,
        content_hash=revision.content_hash,
        approval_state="approved",
        evidence_urls=_evidence_urls(revision),
    )


def _safe_export_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts or "\\" in value:
        raise ExportContractError("unsafe export file name", code="export_file_name_unsafe")
    return path


def _assert_no_symlink_components(root: Path, path: Path) -> None:
    root_absolute = root.absolute()
    path_absolute = path.absolute()
    try:
        relative = path_absolute.relative_to(root_absolute)
    except ValueError:
        raise ExportContractError("path escapes configured storage root", code="export_path_escape") from None
    current = root_absolute
    if current.is_symlink():
        raise ExportContractError("storage root may not be a symlink", code="export_path_symlink")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ExportContractError("storage path may not contain symlinks", code="export_path_symlink")


def _safe_existing_file(root: Path, relative_name: str) -> Path:
    relative = _safe_export_relative(relative_name)
    candidate = root.joinpath(*relative.parts)
    _assert_no_symlink_components(root, candidate)
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise ExportContractError("export file is missing", code="export_file_missing") from None
    if not resolved.is_relative_to(resolved_root):
        raise ExportContractError("export file escaped storage root", code="export_path_escape")
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ExportContractError("export path is not a regular file", code="export_file_invalid")
    return resolved


class ExportService:
    def __init__(self, session: Any, *, export_root: Path, media_root: Path) -> None:
        self.session = session
        self.export_root = Path(export_root)
        self.media_root = Path(media_root)

    async def prepare_payload(self, request: ExportRequest) -> BuildExportPayload:
        _, selected = await self._select_revisions(request)
        identities = [identity for _, _, identity in selected]
        return BuildExportPayload(
            content_pack_id=request.content_pack_id,
            revision_ids=[item.revision_id for item in identities],
            revision_hashes=[item.content_hash for item in identities],
            platforms=[item.platform for item in identities],
            platform_variant_ids=[item.platform_variant_id for item in identities],
            formats=[item for item in FORMAT_ORDER if item in request.formats],
            include_media=request.include_media,
        )

    async def build(
        self,
        request: ExportRequest,
        *,
        export_id: UUID,
        created_at: datetime,
    ) -> ExportArtifact:
        payload = await self.prepare_payload(request)
        return await self.build_from_payload(payload, export_id=export_id, created_at=created_at)

    async def build_from_payload(
        self,
        payload: BuildExportPayload,
        *,
        export_id: UUID,
        created_at: datetime,
    ) -> ExportArtifact:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ExportContractError("export created_at must be timezone-aware")
        request = ExportRequest(
            content_pack_id=payload.content_pack_id,
            revision_ids=payload.revision_ids,
            formats=payload.formats,
            include_media=payload.include_media,
        )
        pack, selected = await self._select_revisions(request)
        actual_identities = [identity for _, _, identity in selected]
        expected_identities = [
            ExportVariantIdentity(
                platform=platform,
                platform_variant_id=variant_id,
                revision_id=revision_id,
                content_hash=content_hash,
                approval_state="approved",
                evidence_urls=actual.evidence_urls,
            )
            for platform, variant_id, revision_id, content_hash, actual in zip(
                payload.platforms,
                payload.platform_variant_ids,
                payload.revision_ids,
                payload.revision_hashes,
                actual_identities,
                strict=True,
            )
        ]
        if actual_identities != expected_identities:
            raise ExportContractError(
                "queued export revision identity no longer matches durable data",
                code="export_revision_identity_mismatch",
            )

        root = self._prepare_export_root()
        target = root / str(export_id)
        if target.exists() or target.is_symlink():
            try:
                return self._load_complete_artifact(
                    target,
                    export_id=export_id,
                    pack=pack,
                    identities=actual_identities,
                    selected=selected,
                    payload=payload,
                    created_at=created_at,
                )
            except ExportContractError:
                if target.is_symlink() or not target.is_dir():
                    raise
                shutil.rmtree(target)

        staging = root / f".{export_id}.{uuid4().hex}.tmp"
        staging.mkdir(mode=0o700)
        try:
            files = await self._write_export_files(staging, selected, payload)
            manifest = ExportManifest(
                content_pack_id=pack.id,
                story_revision_id=pack.story_revision_id,
                created_at=created_at,
                variants=actual_identities,
                files=files,
            )
            manifest_bytes = _canonical_json_bytes(manifest.model_dump(mode="json"))
            archive_sha256 = None
            if "zip" in payload.formats:
                archive_path = staging / ARCHIVE_FILE
                self._write_deterministic_zip(
                    archive_path,
                    staging,
                    manifest.files,
                    manifest_bytes,
                )
                archive_sha256 = _sha256_path(archive_path)
            # The manifest is deliberately the final filesystem write in the staged package.
            (staging / MANIFEST_FILE).write_bytes(manifest_bytes)
            artifact = ExportArtifact(
                export_id=export_id,
                content_pack_id=pack.id,
                state="complete",
                manifest_file=MANIFEST_FILE,
                manifest_sha256=_sha256_bytes(manifest_bytes),
                archive_file=ARCHIVE_FILE if archive_sha256 is not None else None,
                archive_sha256=archive_sha256,
                manifest=manifest,
            )
            try:
                os.rename(staging, target)
            except OSError as exc:
                if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
                return self._load_complete_artifact(
                    target,
                    export_id=export_id,
                    pack=pack,
                    identities=actual_identities,
                    selected=selected,
                    payload=payload,
                    created_at=created_at,
                )
            return artifact
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    async def _select_revisions(
        self,
        request: ExportRequest,
    ) -> tuple[
        ContentPack,
        list[tuple[PlatformVariant, PlatformVariantRevision, ExportVariantIdentity]],
    ]:
        pack = await self.session.get(ContentPack, request.content_pack_id)
        if pack is None:
            raise ExportContractError("content pack not found", code="export_content_pack_missing")
        variants = list(
            await self.session.scalars(
                select(PlatformVariant)
                .where(PlatformVariant.content_pack_id == pack.id)
                .order_by(
                    case(
                        *(
                            (PlatformVariant.platform == platform, index)
                            for index, platform in enumerate(PLATFORM_ORDER)
                        ),
                        else_=len(PLATFORM_ORDER),
                    ),
                    PlatformVariant.id,
                )
            )
        )
        if not variants:
            raise ExportContractError("content pack has no platform variants")
        variants.sort(key=lambda item: (_platform_index(item.platform), str(item.id)))
        variant_by_id = {item.id: item for item in variants}
        revisions = list(
            await self.session.scalars(
                select(PlatformVariantRevision)
                .where(PlatformVariantRevision.platform_variant_id.in_(tuple(variant_by_id)))
                .order_by(
                    PlatformVariantRevision.platform_variant_id,
                    PlatformVariantRevision.revision_number.desc(),
                    PlatformVariantRevision.id,
                )
            )
        )

        if request.revision_ids is None:
            current: dict[UUID, PlatformVariantRevision] = {}
            for revision in revisions:
                existing = current.get(revision.platform_variant_id)
                if existing is None or revision.revision_number > existing.revision_number:
                    current[revision.platform_variant_id] = revision
            if set(current) != set(variant_by_id):
                raise ExportContractError("every platform variant must have a current revision")
            selected_revisions = list(current.values())
        else:
            if not request.revision_ids:
                raise ExportContractError("explicit revision IDs may not be empty")
            if len(set(request.revision_ids)) != len(request.revision_ids):
                raise ExportContractError("explicit revision IDs must be unique")
            revision_by_id = {item.id: item for item in revisions}
            try:
                selected_revisions = [revision_by_id[item] for item in request.revision_ids]
            except KeyError:
                raise ExportContractError(
                    "every explicit revision must belong to the requested content pack",
                    code="export_revision_foreign",
                ) from None
            selected_variant_ids = [item.platform_variant_id for item in selected_revisions]
            if len(set(selected_variant_ids)) != len(selected_variant_ids):
                raise ExportContractError("export may include only one revision per platform variant")
            if set(selected_variant_ids) != set(variant_by_id):
                raise ExportContractError(
                    "explicit revisions must include exactly one revision for every platform variant",
                    code="export_revision_set_incomplete",
                )

        selected_revisions.sort(
            key=lambda item: (
                _platform_index(variant_by_id[item.platform_variant_id].platform),
                str(item.id),
            )
        )
        selected = []
        for revision in selected_revisions:
            variant = variant_by_id.get(revision.platform_variant_id)
            if variant is None:
                raise ExportContractError("revision does not belong to the requested content pack")
            selected.append((variant, revision, _identity(variant, revision)))
        return pack, selected

    async def _write_export_files(
        self,
        staging: Path,
        selected: list[tuple[PlatformVariant, PlatformVariantRevision, ExportVariantIdentity]],
        payload: BuildExportPayload,
    ) -> list[ExportFileIdentity]:
        files: list[ExportFileIdentity] = []
        for variant, revision, identity in selected:
            platform: Platform = variant.platform  # type: ignore[assignment]
            parsed = _payload_model(platform, revision.content)
            base = PurePosixPath(platform, str(revision.id))
            for relative, content, kind in self._nonmedia_file_specs(
                variant,
                revision,
                identity,
                payload,
            ):
                files.append(
                    self._write_file(staging, relative, content, kind, platform, revision.id)
                )
            if payload.include_media:
                files.extend(await self._copy_revision_media(staging, base, platform, revision, parsed))
        return files

    def _nonmedia_file_specs(
        self,
        variant: PlatformVariant,
        revision: PlatformVariantRevision,
        identity: ExportVariantIdentity,
        payload: BuildExportPayload,
    ) -> list[tuple[PurePosixPath, bytes, str]]:
        platform: Platform = variant.platform  # type: ignore[assignment]
        base = PurePosixPath(platform, str(revision.id))
        output: list[tuple[PurePosixPath, bytes, str]] = []
        if "json" in payload.formats:
            output.append(
                (
                    base / "content.json",
                    _canonical_json_bytes(
                        {
                            "platform": platform,
                            "revision_id": str(revision.id),
                            "content_hash": revision.content_hash,
                            "approval_state": revision.approval_state,
                            "evidence_urls": identity.evidence_urls,
                            "content": revision.content,
                            "evidence_map": revision.evidence_map,
                        }
                    ),
                    "json",
                )
            )
        if "markdown" in payload.formats:
            output.append(
                (
                    base / "content.md",
                    self.render_markdown(platform, revision.content).encode("utf-8"),
                    "markdown",
                )
            )
        if "html" in payload.formats:
            output.append(
                (
                    base / "content.html",
                    self.render_html(platform, revision.content).encode("utf-8"),
                    "html",
                )
            )
        return output

    @staticmethod
    def _file_identity(
        relative: PurePosixPath,
        content: bytes,
        kind: str,
        platform: Platform,
        revision_id: UUID,
        *,
        media_asset_id: UUID | None = None,
    ) -> ExportFileIdentity:
        safe = _safe_export_relative(relative.as_posix())
        return ExportFileIdentity(
            file_name=safe.as_posix(),
            sha256=_sha256_bytes(content),
            byte_length=len(content),
            kind=kind,
            platform=platform,
            revision_id=revision_id,
            media_asset_id=media_asset_id,
        )

    def _write_file(
        self,
        staging: Path,
        relative: PurePosixPath,
        content: bytes,
        kind: str,
        platform: Platform,
        revision_id: UUID,
        *,
        media_asset_id: UUID | None = None,
    ) -> ExportFileIdentity:
        identity = self._file_identity(
            relative,
            content,
            kind,
            platform,
            revision_id,
            media_asset_id=media_asset_id,
        )
        safe = PurePosixPath(identity.file_name)
        path = staging.joinpath(*safe.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return identity

    def render_html(self, platform: Platform, content: dict[str, Any]) -> str:
        payload = _payload_model(platform, content)
        source = (
            payload.body_markdown  # type: ignore[union-attr]
            if platform == "blog"
            else self.render_markdown(platform, content)
        )
        rendered = markdown.markdown(source)
        return nh3.clean(rendered, url_schemes={"http", "https", "mailto"})

    def render_markdown(self, platform: Platform, content: dict[str, Any]) -> str:
        payload = _payload_model(platform, content)
        rendered = render_platform_markdown(platform, payload).rstrip()
        if platform == "blog":
            rendered = f"# {payload.title}\n\n{payload.body_markdown}"  # type: ignore[union-attr]
        structured = json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        structured_block = "\n".join(f"    {line}" for line in structured.splitlines())
        return f"{rendered}\n\n## Complete package data\n\n{structured_block}\n"

    async def _copy_revision_media(
        self,
        staging: Path,
        base: PurePosixPath,
        platform: Platform,
        revision: PlatformVariantRevision,
        payload: PlatformPayload,
    ) -> list[ExportFileIdentity]:
        media_ids = self._assigned_media_ids(platform, payload)
        output: list[ExportFileIdentity] = []
        for asset_id in media_ids:
            asset = await self.session.get(MediaAsset, asset_id)
            if asset is None:
                raise ExportContractError("assigned media asset is missing", code="export_media_missing")
            source = self._validated_media_path(asset)
            source_content = source.read_bytes()
            if _sha256_bytes(source_content) != asset.checksum_sha256:
                raise ExportContractError(
                    "assigned media changed while the export was being built",
                    code="export_media_checksum_mismatch",
                )
            suffix = source.suffix.lower()
            if not suffix or len(suffix) > 12 or not suffix[1:].isalnum():
                suffix = ".bin"
            file_name = base / f"media-{asset.id}{suffix}"
            output.append(
                self._write_file(
                    staging,
                    file_name,
                    source_content,
                    "media",
                    platform,
                    revision.id,
                    media_asset_id=asset.id,
                )
            )
        return output

    @staticmethod
    def _assigned_media_ids(platform: Platform, payload: PlatformPayload) -> list[UUID]:
        values: list[UUID | None]
        if platform == "telegram":
            values = list(payload.media_asset_ids)  # type: ignore[union-attr]
        elif platform == "instagram":
            values = [slide.media.media_asset_id for slide in payload.carousel]  # type: ignore[union-attr]
        elif platform == "x":
            values = [
                media.media_asset_id
                for post in payload.posts  # type: ignore[union-attr]
                for media in post.media
            ]
        else:
            hero = payload.hero_media  # type: ignore[union-attr]
            values = [hero.media_asset_id] if hero is not None else []
        return list(dict.fromkeys(value for value in values if value is not None))

    def _validated_media_path(self, asset: MediaAsset) -> Path:
        if asset.fetch_status != "downloaded" or not asset.storage_path:
            raise ExportContractError(
                "assigned media is not a validated local download",
                code="export_media_not_downloaded",
            )
        checksum = asset.checksum_sha256
        if (
            not isinstance(checksum, str)
            or len(checksum) != 64
            or any(char not in "0123456789abcdef" for char in checksum)
        ):
            raise ExportContractError("assigned media checksum is invalid", code="export_media_checksum_invalid")
        raw = Path(asset.storage_path)
        if ".." in raw.parts:
            raise ExportContractError("media storage path contains traversal", code="export_media_path_unsafe")
        root_absolute = self.media_root.absolute()
        candidate = raw if raw.is_absolute() else root_absolute / raw
        _assert_no_symlink_components(root_absolute, candidate)
        try:
            resolved_root = root_absolute.resolve(strict=True)
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            raise ExportContractError("assigned media storage file is missing", code="export_media_missing") from None
        if not resolved.is_relative_to(resolved_root):
            raise ExportContractError("assigned media escaped MEDIA_ROOT", code="export_media_path_escape")
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ExportContractError("assigned media is not a regular file", code="export_media_invalid")
        if asset.byte_length is not None and int(asset.byte_length) != metadata.st_size:
            raise ExportContractError("assigned media byte length mismatch", code="export_media_length_mismatch")
        if _sha256_path(resolved) != checksum:
            raise ExportContractError("assigned media checksum mismatch", code="export_media_checksum_mismatch")
        return resolved

    @staticmethod
    def _write_deterministic_zip(
        archive_path: Path,
        staging: Path,
        files: Iterable[ExportFileIdentity],
        manifest_bytes: bytes,
    ) -> None:
        entries = [(item.file_name, (staging / item.file_name).read_bytes()) for item in files]
        entries.append((MANIFEST_FILE, manifest_bytes))
        with zipfile.ZipFile(archive_path, "w") as archive:
            for name, content in sorted(entries, key=lambda item: item[0]):
                info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    def _prepare_export_root(self) -> Path:
        self.export_root.mkdir(parents=True, exist_ok=True)
        if self.export_root.is_symlink() or not self.export_root.is_dir():
            raise ExportContractError("EXPORT_ROOT must be a real directory")
        return self.export_root.resolve(strict=True)

    def _load_complete_artifact(
        self,
        target: Path,
        *,
        export_id: UUID,
        pack: ContentPack,
        identities: list[ExportVariantIdentity],
        selected: list[tuple[PlatformVariant, PlatformVariantRevision, ExportVariantIdentity]],
        payload: BuildExportPayload,
        created_at: datetime,
    ) -> ExportArtifact:
        if target.is_symlink() or not target.is_dir():
            raise ExportContractError("existing export target is unsafe")
        manifest_path = _safe_existing_file(target, MANIFEST_FILE)
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest = ExportManifest.model_validate_json(manifest_bytes)
        except ValidationError, ValueError:
            raise ExportContractError("existing export manifest is invalid") from None
        if manifest_bytes != _canonical_json_bytes(manifest.model_dump(mode="json")):
            raise ExportContractError("existing export manifest is not canonical")
        if (
            manifest.content_pack_id != pack.id
            or manifest.story_revision_id != pack.story_revision_id
            or manifest.created_at != created_at
            or manifest.variants != identities
        ):
            raise ExportContractError("existing export manifest identity is stale")
        self._validate_manifest_file_matrix(manifest, selected, payload)
        expected_files = {MANIFEST_FILE}
        for item in manifest.files:
            path = _safe_existing_file(target, item.file_name)
            if path.stat().st_size != item.byte_length or _sha256_path(path) != item.sha256:
                raise ExportContractError("existing export file checksum mismatch")
            expected_files.add(item.file_name)
        archive_file = None
        archive_sha256 = None
        if "zip" in payload.formats:
            archive = _safe_existing_file(target, ARCHIVE_FILE)
            self._validate_zip(archive, target, manifest.files, manifest_bytes)
            archive_file = ARCHIVE_FILE
            archive_sha256 = _sha256_path(archive)
            expected_files.add(ARCHIVE_FILE)
        actual_files = {
            path.relative_to(target).as_posix()
            for path in target.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        if actual_files != expected_files:
            raise ExportContractError("existing export directory has unexpected or missing files")
        return ExportArtifact(
            export_id=export_id,
            content_pack_id=pack.id,
            state="complete",
            manifest_file=MANIFEST_FILE,
            manifest_sha256=_sha256_bytes(manifest_bytes),
            archive_file=archive_file,
            archive_sha256=archive_sha256,
            manifest=manifest,
        )

    def _validate_manifest_file_matrix(
        self,
        manifest: ExportManifest,
        selected: list[tuple[PlatformVariant, PlatformVariantRevision, ExportVariantIdentity]],
        payload: BuildExportPayload,
    ) -> None:
        expected: list[tuple[str, str, UUID, UUID | None]] = []
        exact_nonmedia: dict[str, ExportFileIdentity] = {}
        for variant, revision, identity in selected:
            platform: Platform = variant.platform  # type: ignore[assignment]
            for relative, content, kind in self._nonmedia_file_specs(
                variant,
                revision,
                identity,
                payload,
            ):
                item = self._file_identity(relative, content, kind, platform, revision.id)
                exact_nonmedia[item.file_name] = item
                expected.append((kind, platform, revision.id, None))
            if payload.include_media:
                parsed = _payload_model(platform, revision.content)
                expected.extend(
                    ("media", platform, revision.id, asset_id)
                    for asset_id in self._assigned_media_ids(platform, parsed)
                )
        actual = [
            (item.kind, item.platform, item.revision_id, item.media_asset_id)
            for item in manifest.files
        ]
        if actual != expected:
            raise ExportContractError("existing export manifest file matrix is stale")
        for item in manifest.files:
            if item.kind != "media":
                if exact_nonmedia.get(item.file_name) != item:
                    raise ExportContractError("existing export payload is not semantically exact")
                continue
            expected_parent = PurePosixPath(item.platform, str(item.revision_id))
            path = PurePosixPath(item.file_name)
            if (
                path.parent != expected_parent
                or item.media_asset_id is None
                or not path.name.startswith(f"media-{item.media_asset_id}.")
            ):
                raise ExportContractError("existing export media file name is not canonical")

    @staticmethod
    def _validate_zip(
        archive_path: Path,
        target: Path,
        files: list[ExportFileIdentity],
        manifest_bytes: bytes,
    ) -> None:
        expected = {item.file_name: (target / item.file_name).read_bytes() for item in files}
        expected[MANIFEST_FILE] = manifest_bytes
        try:
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                if [item.filename for item in infos] != sorted(expected):
                    raise ExportContractError("existing export archive entries are invalid")
                for info in infos:
                    permissions = (info.external_attr >> 16) & 0o777
                    if (
                        info.date_time != ZIP_TIMESTAMP
                        or permissions != 0o644
                        or info.compress_type != zipfile.ZIP_DEFLATED
                        or archive.read(info.filename) != expected[info.filename]
                    ):
                        raise ExportContractError("existing export archive is not deterministic")
        except (KeyError, OSError, zipfile.BadZipFile):
            raise ExportContractError("existing export archive is invalid") from None
