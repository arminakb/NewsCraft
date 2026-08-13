from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import stat
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redaction import redact_secrets
from app.db.session import get_session
from app.exports.models import (
    BuildExportPayload,
    ExpiredExportArtifact,
    ExportArtifact,
    ExportArtifactListOut,
    ExportArtifactOut,
    ExportRequest,
)
from app.exports.service import ExportContractError, ExportService
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin, JobStatus

logger = logging.getLogger(__name__)

router = APIRouter()
SessionDependency = Depends(get_session)
MAX_EXPORT_REBUILD_GENERATIONS = 32


#: Every way a stored export artifact can fail its integrity checks, each with
#: a stable code. Keeping them enumerated here is what makes a manifest
#: checksum mismatch — the tamper signal — reportable as itself instead of
#: collapsing into one opaque "artifact invalid" answer.
EXPORT_ARTIFACT_FAILURES = {
    "export_artifact_expired_result_invalid": "Expired export result is invalid",
    "export_artifact_expired_identity_mismatch": "Expired export identity does not match its job",
    "export_artifact_result_incomplete": "Export artifact result is incomplete",
    "export_artifact_identity_mismatch": "Export artifact identity does not match its job",
    "export_artifact_manifest_checksum_mismatch": "Export manifest checksum does not match its result",
    "export_artifact_file_matrix_mismatch": "Export artifact file matrix does not match its job",
    "export_artifact_archive_mismatch": "Export archive does not match its job",
    "export_artifact_unrequested_media": "Export contains media that was not requested",
    "export_artifact_file_unbound": "Export file is not bound to its job",
    "export_artifact_media_identity_invalid": "Export media file identity is invalid",
    "export_artifact_file_order_nondeterministic": "Export file ordering is not deterministic",
}


class ExportArtifactInvalid(Exception):
    """A completed export whose stored artifact fails an integrity check.

    Routes answering for a single export map this onto the 409 they have always
    returned, detail text unchanged; the list route reports the code per item
    instead of flattening every failure into one string.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = EXPORT_ARTIFACT_FAILURES[code]
        super().__init__(self.message)


def _artifact_conflict(exc: ExportArtifactInvalid) -> HTTPException:
    return HTTPException(status_code=409, detail=exc.message)


def _export_root() -> Path:
    return Path(settings.export_root)


def _media_root() -> Path:
    return Path(settings.media_root)


ExportRootDependency = Annotated[Path, Depends(_export_root)]
MediaRootDependency = Annotated[Path, Depends(_media_root)]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def export_idempotency_key(payload: BuildExportPayload) -> str:
    revision_hashes = ",".join(sorted(payload.revision_hashes))
    request_hash = hashlib.sha256(_canonical_json(payload.model_dump(mode="json"))).hexdigest()
    return f"build_export:{payload.content_pack_id}:{revision_hashes}:{request_hash}"


def encode_export_cursor(finished_at: datetime, job_id: UUID) -> str:
    if finished_at.tzinfo is None or finished_at.utcoffset() is None:
        raise ValueError("export cursor timestamp must be timezone-aware")
    encoded = base64.urlsafe_b64encode(_canonical_json({"finished_at": finished_at.isoformat(), "job_id": str(job_id)}))
    return encoded.rstrip(b"=").decode("ascii")


def decode_export_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"finished_at", "job_id"}:
            raise ValueError
        finished_at = datetime.fromisoformat(value["finished_at"])
        job_id = UUID(value["job_id"])
        if finished_at.tzinfo is None or finished_at.utcoffset() is None:
            raise ValueError
    except binascii.Error, json.JSONDecodeError, KeyError, TypeError, ValueError:
        raise ValueError("invalid export cursor") from None
    return finished_at, job_id


def _safe_error_text(value: Any) -> str | None:
    if value is None:
        return None
    redacted = redact_secrets(str(value))
    return str(redacted)


def export_artifact_out(
    job: Any,
    artifact: ExportArtifact | ExpiredExportArtifact | None,
) -> ExportArtifactOut:
    downloads: list[str] = []
    if isinstance(artifact, ExportArtifact):
        names: list[str] = [artifact.manifest_file]
        if artifact.archive_file is not None:
            names.append(artifact.archive_file)
        names.extend(item.file_name for item in artifact.manifest.files)
        downloads = [f"/exports/{job.id}/download/{quote(name, safe='/')}" for name in dict.fromkeys(names)]
    expired = isinstance(artifact, ExpiredExportArtifact)
    return ExportArtifactOut(
        export_id=job.id,
        status=str(job.status),
        finished_at=getattr(job, "finished_at", None),
        artifact=artifact,
        downloads=downloads,
        error_code=("export_expired" if expired else _safe_error_text(getattr(job, "error_code", None))),
        error_message=(
            "Export artifact expired under retention policy"
            if expired
            else _safe_error_text(getattr(job, "error_message", None))
        ),
    )


def _typed_artifact(job: Any) -> ExportArtifact | ExpiredExportArtifact | None:
    if str(job.status) != JobStatus.SUCCEEDED:
        return None
    if isinstance(job.result, dict) and job.result.get("state") == "expired":
        try:
            expired = ExpiredExportArtifact.model_validate(job.result)
            payload = BuildExportPayload.model_validate(job.payload)
        except ValidationError:
            raise ExportArtifactInvalid("export_artifact_expired_result_invalid") from None
        if expired.export_id != job.id or expired.content_pack_id != payload.content_pack_id:
            raise ExportArtifactInvalid("export_artifact_expired_identity_mismatch")
        return expired
    try:
        artifact = ExportArtifact.model_validate(job.result)
        payload = BuildExportPayload.model_validate(job.payload)
    except AttributeError, ValidationError:
        raise ExportArtifactInvalid("export_artifact_result_incomplete") from None
    artifact_identities = [
        (
            item.platform,
            item.platform_variant_id,
            item.revision_id,
            item.content_hash,
        )
        for item in artifact.manifest.variants
    ]
    payload_identities = list(
        zip(
            payload.platforms,
            payload.platform_variant_ids,
            payload.revision_ids,
            payload.revision_hashes,
            strict=True,
        )
    )
    if (
        artifact.export_id != job.id
        or artifact.content_pack_id != payload.content_pack_id
        or artifact.manifest.content_pack_id != payload.content_pack_id
        or artifact.manifest.created_at != getattr(job, "created_at", None)
        or artifact_identities != payload_identities
    ):
        raise ExportArtifactInvalid("export_artifact_identity_mismatch")
    expected_manifest_sha256 = hashlib.sha256(_canonical_json(artifact.manifest.model_dump(mode="json"))).hexdigest()
    if artifact.manifest_sha256 != expected_manifest_sha256:
        raise ExportArtifactInvalid("export_artifact_manifest_checksum_mismatch")
    _validate_public_file_matrix(artifact, payload)
    return artifact


def _export_rebuild_idempotency_key(
    base_key: str,
    job: WorkflowJob,
    expired: ExpiredExportArtifact,
) -> str:
    identity_hash = hashlib.sha256(
        _canonical_json(
            {
                "previous_export_id": str(job.id),
                "expired_at": expired.expired_at.isoformat(),
            }
        )
    ).hexdigest()
    return f"{base_key}:rebuild:{identity_hash}"


async def _enqueue_export_job(
    session: AsyncSession,
    payload: BuildExportPayload,
):
    repository = JobRepository(session)
    payload_data = payload.model_dump(mode="json")
    base_key = export_idempotency_key(payload)
    idempotency_key = base_key
    previous: tuple[WorkflowJob, ExpiredExportArtifact] | None = None

    for generation in range(MAX_EXPORT_REBUILD_GENERATIONS + 1):
        result = await repository.enqueue_job(
            job_type="build_export",
            payload=payload_data,
            idempotency_key=idempotency_key,
            origin=JobOrigin.MANUAL,
            pause_sensitive=False,
        )
        if result.created:
            if previous is not None:
                expired_job, expired = previous
                session.add(
                    WorkflowEvent(
                        workflow_job_id=result.job.id,
                        event_type="export.rebuild_enqueued",
                        actor=JobOrigin.MANUAL,
                        event_data={
                            "previous_export_id": str(expired_job.id),
                            "expired_at": expired.expired_at.isoformat(),
                            "rebuild_generation": generation,
                        },
                    )
                )
                await session.flush()
            return result

        job = result.job
        if job.job_type != "build_export":
            raise HTTPException(status_code=409, detail="Export idempotency identity is invalid")
        try:
            persisted_payload = BuildExportPayload.model_validate(job.payload)
        except ValidationError:
            raise HTTPException(status_code=409, detail="Export idempotency payload is invalid") from None
        if persisted_payload != payload:
            raise HTTPException(status_code=409, detail="Export idempotency payload does not match request")
        if str(job.status) != JobStatus.SUCCEEDED or not (
            isinstance(job.result, dict) and job.result.get("state") == "expired"
        ):
            return result

        try:
            expired_artifact = _typed_artifact(job)
        except ExportArtifactInvalid as exc:
            raise _artifact_conflict(exc) from None
        if not isinstance(expired_artifact, ExpiredExportArtifact):  # pragma: no cover - guarded above
            return result
        if generation >= MAX_EXPORT_REBUILD_GENERATIONS:
            raise HTTPException(status_code=409, detail="Export rebuild history exceeds the supported depth")
        previous = (job, expired_artifact)
        idempotency_key = _export_rebuild_idempotency_key(base_key, job, expired_artifact)

    raise HTTPException(status_code=409, detail="Export rebuild history is invalid")  # pragma: no cover


def _validate_public_file_matrix(artifact: ExportArtifact, payload: BuildExportPayload) -> None:
    expected_nonmedia: list[tuple[str, str, UUID, str]] = []
    extension_by_format = {"json": "json", "markdown": "md", "html": "html"}
    for platform, revision_id in zip(payload.platforms, payload.revision_ids, strict=True):
        for format_name in ("json", "markdown", "html"):
            if format_name in payload.formats:
                expected_nonmedia.append(
                    (
                        f"{platform}/{revision_id}/content.{extension_by_format[format_name]}",
                        format_name,
                        revision_id,
                        platform,
                    )
                )
    actual_nonmedia = [
        (item.file_name, item.kind, item.revision_id, item.platform)
        for item in artifact.manifest.files
        if item.kind != "media"
    ]
    if actual_nonmedia != expected_nonmedia:
        raise ExportArtifactInvalid("export_artifact_file_matrix_mismatch")
    if (artifact.archive_file is not None) != ("zip" in payload.formats):
        raise ExportArtifactInvalid("export_artifact_archive_mismatch")
    if not payload.include_media and any(item.kind == "media" for item in artifact.manifest.files):
        raise ExportArtifactInvalid("export_artifact_unrequested_media")
    variant_order = {
        (platform, revision_id): index
        for index, (platform, revision_id) in enumerate(zip(payload.platforms, payload.revision_ids, strict=True))
    }
    order = []
    kind_order = {"json": 0, "markdown": 1, "html": 2, "media": 3}
    for item in artifact.manifest.files:
        identity = (item.platform, item.revision_id)
        if identity not in variant_order:
            raise ExportArtifactInvalid("export_artifact_file_unbound")
        if item.kind == "media":
            path = PurePosixPath(item.file_name)
            if (
                item.media_asset_id is None
                or path.parent != PurePosixPath(item.platform, str(item.revision_id))
                or not path.name.startswith(f"media-{item.media_asset_id}.")
            ):
                raise ExportArtifactInvalid("export_artifact_media_identity_invalid")
        order.append((variant_order[identity], kind_order[item.kind]))
    if order != sorted(order):
        raise ExportArtifactInvalid("export_artifact_file_order_nondeterministic")


def _contract_http_error(exc: ExportContractError) -> HTTPException:
    if exc.code == "export_content_pack_missing":
        return HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)})
    if exc.code in {
        "export_revision_not_approved",
        "export_revision_hash_mismatch",
        "export_revision_identity_mismatch",
    }:
        return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})


@router.post(
    "/content-packs/{pack_id}/exports",
    response_model=JobAcceptedOut,
    status_code=202,
)
async def create_export(
    pack_id: UUID,
    body: ExportRequest,
    export_root: ExportRootDependency,
    media_root: MediaRootDependency,
    session: AsyncSession = SessionDependency,
) -> JobAcceptedOut:
    if body.content_pack_id != pack_id:
        raise HTTPException(status_code=409, detail="Path content pack must match request content_pack_id")
    try:
        payload = await ExportService(
            session,
            export_root=Path(export_root),
            media_root=Path(media_root),
        ).prepare_payload(body)
    except ExportContractError as exc:
        raise _contract_http_error(exc) from None
    result = await _enqueue_export_job(session, payload)
    await session.commit()
    return JobAcceptedOut(
        job_id=result.job.id,
        status=result.job.status,
        deduplicated=not result.created,
    )


@router.get("/exports", response_model=ExportArtifactListOut)
async def list_exports(
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=250),
    session: AsyncSession = SessionDependency,
) -> ExportArtifactListOut:
    statement = select(WorkflowJob).where(
        WorkflowJob.job_type == "build_export",
        WorkflowJob.finished_at.is_not(None),
        WorkflowJob.status.in_(
            (
                JobStatus.SUCCEEDED,
                JobStatus.FAILED,
            )
        ),
    )
    if cursor is not None:
        try:
            finished_at, job_id = decode_export_cursor(cursor)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        statement = statement.where(
            or_(
                WorkflowJob.finished_at < finished_at,
                (WorkflowJob.finished_at == finished_at) & (WorkflowJob.id < job_id),
            )
        )
    statement = statement.order_by(WorkflowJob.finished_at.desc(), WorkflowJob.id.desc()).limit(limit + 1)
    rows = list(await session.scalars(statement))
    page = rows[:limit]
    output: list[ExportArtifactOut] = []
    for job in page:
        artifact = None
        if str(job.status) == JobStatus.SUCCEEDED:
            try:
                artifact = _typed_artifact(job)
            except ExportArtifactInvalid as exc:
                # One bad artifact must not fail the page, but it must still be
                # recognisable: the specific code separates a tampered manifest
                # from a schema drift, and the log line is the only record an
                # operator gets that the integrity check fired at all.
                logger.warning(
                    "export artifact failed integrity validation",
                    extra={"export_id": str(job.id), "error_code": exc.code},
                )
                output.append(
                    ExportArtifactOut(
                        export_id=job.id,
                        status=str(job.status),
                        finished_at=job.finished_at,
                        artifact=None,
                        downloads=[],
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                )
                continue
        output.append(export_artifact_out(job, artifact))
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        if last.finished_at is not None:
            next_cursor = encode_export_cursor(last.finished_at, last.id)
    return ExportArtifactListOut(items=output, next_cursor=next_cursor)


@router.get("/exports/{export_id}", response_model=ExportArtifactOut)
async def get_export(
    export_id: UUID,
    session: AsyncSession = SessionDependency,
) -> ExportArtifactOut:
    job = await session.get(WorkflowJob, export_id)
    if job is None or job.job_type != "build_export":
        raise HTTPException(status_code=404, detail="Export not found")
    try:
        artifact = _typed_artifact(job)
    except ExportArtifactInvalid as exc:
        raise _artifact_conflict(exc) from None
    return export_artifact_out(job, artifact)


def _download_identity(artifact: ExportArtifact, file_name: str) -> tuple[str, int | None]:
    if file_name == artifact.manifest_file:
        return artifact.manifest_sha256, None
    if artifact.archive_file is not None and file_name == artifact.archive_file:
        if artifact.archive_sha256 is None:  # pragma: no cover - enforced by the value object
            raise HTTPException(status_code=409, detail="Export archive checksum is unavailable")
        return artifact.archive_sha256, None
    files = {item.file_name: item for item in artifact.manifest.files}
    item = files.get(file_name)
    if item is None:
        raise HTTPException(status_code=404, detail="Export file is not in the artifact manifest")
    return item.sha256, item.byte_length


def resolve_export_download(export_root: Path, artifact: ExportArtifact, file_name: str) -> Path:
    relative = PurePosixPath(file_name)
    if not file_name or relative.is_absolute() or ".." in relative.parts or "." in relative.parts or "\\" in file_name:
        raise HTTPException(status_code=404, detail="Export file not found")
    expected_sha256, expected_length = _download_identity(artifact, relative.as_posix())
    root = Path(export_root).absolute()
    if root.is_symlink():
        raise HTTPException(status_code=409, detail="Export storage root is unsafe")
    export_dir = root / str(artifact.export_id)
    candidate = export_dir.joinpath(*relative.parts)
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=404, detail="Export file not found") from None
    current = root
    for part in candidate.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise HTTPException(status_code=409, detail="Export storage path is unsafe")
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Export file not found") from None
    if not resolved.is_relative_to(resolved_root) or not stat.S_ISREG(resolved.stat().st_mode):
        raise HTTPException(status_code=409, detail="Export storage path is unsafe")
    if expected_length is not None and resolved.stat().st_size != expected_length:
        raise HTTPException(status_code=409, detail="Export file length does not match its manifest")
    digest = hashlib.sha256()
    with resolved.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise HTTPException(status_code=409, detail="Export file checksum does not match its manifest")
    return resolved


@router.get("/exports/{export_id}/download/{file_name:path}")
async def download_export(
    export_id: UUID,
    file_name: str,
    export_root: ExportRootDependency,
    session: AsyncSession = SessionDependency,
) -> FileResponse:
    job = await session.get(WorkflowJob, export_id)
    if job is None or job.job_type != "build_export":
        raise HTTPException(status_code=404, detail="Export not found")
    if str(job.status) != JobStatus.SUCCEEDED:
        raise HTTPException(status_code=409, detail="Export is not complete")
    try:
        artifact = _typed_artifact(job)
    except ExportArtifactInvalid as exc:
        raise _artifact_conflict(exc) from None
    if artifact is None:  # pragma: no cover - succeeded jobs either parse or raise
        raise HTTPException(status_code=409, detail="Export artifact is unavailable")
    if isinstance(artifact, ExpiredExportArtifact):
        raise HTTPException(status_code=410, detail="Export artifact has expired")
    path = resolve_export_download(Path(export_root), artifact, file_name)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=PurePosixPath(file_name).name,
    )
