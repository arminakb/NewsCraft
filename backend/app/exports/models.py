from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.generation.platform_schemas import Platform

type ExportFormat = Literal["json", "markdown", "html", "zip"]
type ExportFileKind = Literal["json", "markdown", "html", "media"]


def _safe_relative_file_name(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts or "\\" in value:
        raise ValueError("export file names must be safe relative POSIX paths")
    if any(not part for part in path.parts):
        raise ValueError("export file names must not contain empty path components")
    if any(re.fullmatch(r"[A-Za-z0-9._-]+", part) is None for part in path.parts):
        raise ValueError("export file names may contain only safe filename characters")
    return path.as_posix()


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_pack_id: UUID
    revision_ids: list[UUID] | None = Field(default=None, min_length=1)
    formats: list[ExportFormat] = Field(min_length=1)
    include_media: bool = False

    @field_validator("formats")
    @classmethod
    def require_unique_formats(cls, value: list[ExportFormat]) -> list[ExportFormat]:
        if len(set(value)) != len(value):
            raise ValueError("export formats must be unique")
        return value


class ExportVariantIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    platform: Platform
    platform_variant_id: UUID
    revision_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_state: Literal["approved"]
    evidence_urls: list[str]

    @field_validator("evidence_urls")
    @classmethod
    def require_deterministic_evidence_urls(cls, value: list[str]) -> list[str]:
        if value != sorted(set(value)):
            raise ValueError("manifest evidence URLs must be unique and sorted")
        return value


class ExportFileIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file_name: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(ge=0)
    kind: ExportFileKind
    platform: Platform
    revision_id: UUID
    media_asset_id: UUID | None = None

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        return _safe_relative_file_name(value)

    @model_validator(mode="after")
    def bind_media_identity(self):
        if (self.kind == "media") != (self.media_asset_id is not None):
            raise ValueError("only media export files may bind a media asset")
        return self


class ExportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["newscraft-export-v1"] = "newscraft-export-v1"
    content_pack_id: UUID
    story_revision_id: UUID
    created_at: datetime
    variants: list[ExportVariantIdentity]
    files: list[ExportFileIdentity]

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("export manifest created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_unique_bound_entries(self):
        revision_ids = [item.revision_id for item in self.variants]
        variant_ids = [item.platform_variant_id for item in self.variants]
        file_names = [item.file_name for item in self.files]
        if len(set(revision_ids)) != len(revision_ids) or len(set(variant_ids)) != len(variant_ids):
            raise ValueError("export manifest variant identities must be unique")
        if len(set(file_names)) != len(file_names):
            raise ValueError("export manifest file names must be unique")
        identities = {(item.platform, item.revision_id) for item in self.variants}
        if any((item.platform, item.revision_id) not in identities for item in self.files):
            raise ValueError("every export file must bind a manifest variant")
        return self


class ExportArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    export_id: UUID
    content_pack_id: UUID
    state: Literal["complete"]
    manifest_file: Literal["manifest.json"]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_file: Literal["bundle.zip"] | None
    archive_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    manifest: ExportManifest

    @field_validator("manifest_file")
    @classmethod
    def validate_manifest_file(cls, value: str) -> str:
        return _safe_relative_file_name(value)

    @field_validator("archive_file")
    @classmethod
    def validate_archive_file(cls, value: str | None) -> str | None:
        return _safe_relative_file_name(value) if value is not None else None

    @model_validator(mode="after")
    def bind_artifact(self):
        if self.manifest.content_pack_id != self.content_pack_id:
            raise ValueError("artifact content pack does not match its manifest")
        if (self.archive_file is None) != (self.archive_sha256 is None):
            raise ValueError("archive file and checksum must be present together")
        reserved = {self.manifest_file, *([self.archive_file] if self.archive_file is not None else [])}
        if any(item.file_name in reserved for item in self.manifest.files):
            raise ValueError("manifest payload files may not collide with artifact control files")
        return self


class BuildExportPayload(BaseModel):
    """Immutable exact revision identities persisted in WorkflowJob.payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content_pack_id: UUID
    revision_ids: list[UUID] = Field(min_length=1)
    revision_hashes: list[str] = Field(min_length=1)
    platforms: list[Platform] = Field(min_length=1)
    platform_variant_ids: list[UUID] = Field(min_length=1)
    formats: list[ExportFormat] = Field(min_length=1)
    include_media: bool = False

    @field_validator("revision_hashes")
    @classmethod
    def validate_hashes(cls, value: list[str]) -> list[str]:
        if any(len(item) != 64 or any(char not in "0123456789abcdef" for char in item) for item in value):
            raise ValueError("revision hashes must be lowercase SHA-256 values")
        return value

    @field_validator("formats")
    @classmethod
    def require_unique_formats(cls, value: list[ExportFormat]) -> list[ExportFormat]:
        if len(set(value)) != len(value):
            raise ValueError("export formats must be unique")
        return value

    @model_validator(mode="after")
    def validate_parallel_identities(self):
        sizes = {
            len(self.revision_ids),
            len(self.revision_hashes),
            len(self.platforms),
            len(self.platform_variant_ids),
        }
        if len(sizes) != 1:
            raise ValueError("export revision identity lists must have equal length")
        if len(set(self.revision_ids)) != len(self.revision_ids):
            raise ValueError("export revision IDs must be unique")
        if len(set(self.platform_variant_ids)) != len(self.platform_variant_ids):
            raise ValueError("export may include only one revision per platform variant")
        return self


class ExportArtifactOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: UUID
    status: str
    finished_at: datetime | None
    artifact: ExportArtifact | None
    downloads: list[str]
    error_code: str | None = None
    error_message: str | None = None


class ExportArtifactListOut(BaseModel):
    items: list[ExportArtifactOut]
    next_cursor: str | None
