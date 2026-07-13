from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select

from app.jobs.models import WorkflowJob

REGENERATION_FENCE_RESULT_KEY = "_regeneration_fence"


class RegenerationFenceConflict(RuntimeError):
    """A live regeneration lease owns the right to advance a variant."""


@dataclass(frozen=True)
class RegenerationFenceOwner:
    workflow_job_id: UUID
    workflow_attempt: int
    lease_owner: str


@dataclass(frozen=True)
class _RegenerationFence:
    variant_id: UUID
    base_revision_id: UUID
    base_content_hash: str
    owner: RegenerationFenceOwner


def public_job_result(result: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(result or {}).items()
        if key != REGENERATION_FENCE_RESULT_KEY
    }


def _fence_from_job(job: Any) -> _RegenerationFence | None:
    raw = dict(job.result or {}).get(REGENERATION_FENCE_RESULT_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        fence = _RegenerationFence(
            variant_id=UUID(str(raw["variant_id"])),
            base_revision_id=UUID(str(raw["base_revision_id"])),
            base_content_hash=str(raw["base_content_hash"]),
            owner=RegenerationFenceOwner(
                workflow_job_id=UUID(str(raw["workflow_job_id"])),
                workflow_attempt=int(raw["workflow_attempt"]),
                lease_owner=str(raw["lease_owner"]),
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if re.fullmatch(r"[0-9a-f]{64}", fence.base_content_hash) is None:
        return None
    if fence.owner.workflow_job_id != job.id:
        return None
    return fence


def _is_live(job: Any, fence: _RegenerationFence, now: datetime) -> bool:
    return (
        str(job.status) == "running"
        and job.attempt_count == fence.owner.workflow_attempt
        and job.lease_owner == fence.owner.lease_owner
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
    )


def _has_live_lease(job: Any, now: datetime) -> bool:
    return (
        str(job.status) == "running"
        and isinstance(job.attempt_count, int)
        and job.attempt_count > 0
        and isinstance(job.lease_owner, str)
        and bool(job.lease_owner.strip())
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
    )


def _raw_fence_targets_variant(job: Any, variant_id: UUID) -> bool:
    raw = dict(job.result or {}).get(REGENERATION_FENCE_RESULT_KEY)
    if not isinstance(raw, dict):
        return False
    try:
        return UUID(str(raw.get("variant_id"))) == variant_id
    except (TypeError, ValueError):
        return False


async def _locked_regeneration_jobs(
    session: Any,
    *,
    variant_id: UUID,
    owner_job_id: UUID | None = None,
) -> list[Any]:
    target_variant = (
        func.lower(
            WorkflowJob.result[REGENERATION_FENCE_RESULT_KEY]["variant_id"].astext
        )
        == str(variant_id)
    )
    target = target_variant
    if owner_job_id is not None:
        target = or_(WorkflowJob.id == owner_job_id, target_variant)
    return list(
        await session.scalars(
            select(WorkflowJob)
            .where(
                WorkflowJob.job_type == "content_pack.regenerate",
                WorkflowJob.status == "running",
                WorkflowJob.lease_expires_at.is_not(None),
                target,
            )
            .order_by(WorkflowJob.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


async def acquire_regeneration_fence(
    session: Any,
    *,
    variant_id: UUID,
    base_revision_id: UUID,
    base_content_hash: str,
    workflow_job_id: UUID,
    workflow_attempt: int,
    lease_owner: str | None,
    now: datetime | None = None,
) -> RegenerationFenceOwner:
    if (
        workflow_attempt <= 0
        or not isinstance(lease_owner, str)
        or not lease_owner.strip()
        or re.fullmatch(r"[0-9a-f]{64}", base_content_hash) is None
    ):
        raise RegenerationFenceConflict("Regeneration fence owner or base is invalid")
    observed_at = now or datetime.now(UTC)
    jobs = await _locked_regeneration_jobs(
        session,
        variant_id=variant_id,
        owner_job_id=workflow_job_id,
    )
    owner_job = next((job for job in jobs if job.id == workflow_job_id), None)
    owner = RegenerationFenceOwner(
        workflow_job_id=workflow_job_id,
        workflow_attempt=workflow_attempt,
        lease_owner=lease_owner,
    )
    if (
        owner_job is None
        or str(owner_job.status) != "running"
        or owner_job.attempt_count != workflow_attempt
        or owner_job.lease_owner != lease_owner
        or owner_job.lease_expires_at is None
        or owner_job.lease_expires_at <= observed_at
    ):
        raise RegenerationFenceConflict("Regeneration worker lease is no longer active")

    for job in jobs:
        fence = _fence_from_job(job)
        if (
            fence is None
            and _raw_fence_targets_variant(job, variant_id)
            and _has_live_lease(job, observed_at)
        ):
            raise RegenerationFenceConflict("Live regeneration fence is invalid")
        if fence is None or fence.variant_id != variant_id or not _is_live(job, fence, observed_at):
            continue
        if (
            fence.owner != owner
            or fence.base_revision_id != base_revision_id
            or fence.base_content_hash != base_content_hash
        ):
            raise RegenerationFenceConflict("Variant regeneration is already in progress")

    owner_job.result = {
        **dict(owner_job.result or {}),
        REGENERATION_FENCE_RESULT_KEY: {
            "variant_id": str(variant_id),
            "base_revision_id": str(base_revision_id),
            "base_content_hash": base_content_hash,
            "workflow_job_id": str(workflow_job_id),
            "workflow_attempt": workflow_attempt,
            "lease_owner": lease_owner,
        },
    }
    await session.flush()
    return owner


async def require_revision_write_allowed(
    session: Any,
    *,
    variant_id: UUID,
    owner: RegenerationFenceOwner | None = None,
    expected_base_revision_id: UUID | None = None,
    expected_base_content_hash: str | None = None,
    now: datetime | None = None,
) -> None:
    observed_at = now or datetime.now(UTC)
    live = []
    for job in await _locked_regeneration_jobs(session, variant_id=variant_id):
        fence = _fence_from_job(job)
        if (
            fence is None
            and _raw_fence_targets_variant(job, variant_id)
            and _has_live_lease(job, observed_at)
        ):
            raise RegenerationFenceConflict("Live regeneration fence is invalid")
        if fence is not None and fence.variant_id == variant_id and _is_live(job, fence, observed_at):
            live.append(fence)
    if owner is None:
        if live:
            raise RegenerationFenceConflict("Variant regeneration is in progress")
        return
    if len(live) != 1:
        raise RegenerationFenceConflict("Regeneration fence ownership was lost")
    fence = live[0]
    if (
        fence.owner != owner
        or fence.base_revision_id != expected_base_revision_id
        or fence.base_content_hash != expected_base_content_hash
    ):
        raise RegenerationFenceConflict("Regeneration fence ownership was lost")


async def clear_regeneration_fence(
    session: Any,
    *,
    variant_id: UUID,
    owner: RegenerationFenceOwner,
    now: datetime | None = None,
) -> bool:
    del now  # Clearing is keyed by the immutable owner token, not current liveness.
    for job in await _locked_regeneration_jobs(
        session,
        variant_id=variant_id,
        owner_job_id=owner.workflow_job_id,
    ):
        fence = _fence_from_job(job)
        if fence is None or fence.variant_id != variant_id or fence.owner != owner:
            continue
        job.result = public_job_result(job.result)
        await session.flush()
        return True
    return False
