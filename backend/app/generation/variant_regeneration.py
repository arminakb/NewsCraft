from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from app.core.faults import FaultInjector
from app.generation.generation_helpers import checkpoint_execution, job_payload, required_uuid
from app.generation.models import (
    ContentPack,
    PlatformVariant,
)
from app.generation.package_generation import build_pack_generation_handler
from app.generation.revision_fence import (
    RegenerationFenceOwner,
    clear_regeneration_fence,
)
from app.jobs.errors import PermanentJobError
from app.jobs.registry import JobContext
from app.jobs.types import JobExecution


def build_regenerate_handler(
    profile_resolver: Any,
    *,
    fault_injector: FaultInjector | None = None,
):
    async def handle(job: JobExecution, context: JobContext) -> dict[str, Any]:
        payload = job_payload(job)
        variant_id = required_uuid(payload, "variant_id")
        variant = await context.session.scalar(
            select(PlatformVariant).where(PlatformVariant.id == variant_id).execution_options(populate_existing=True)
        )
        if variant is None:
            raise PermanentJobError(
                code="generation_variant_missing",
                message="Regeneration variant context was not found",
            )
        pack = await context.session.get(ContentPack, variant.content_pack_id)
        if pack is None:
            raise PermanentJobError(
                code="generation_content_pack_missing",
                message="Regeneration variant context was not found",
            )
        required_uuid(payload, "base_revision_id")
        base_content_hash = payload.get("base_content_hash")
        if not isinstance(base_content_hash, str) or re.fullmatch(r"[0-9a-f]{64}", base_content_hash) is None:
            raise PermanentJobError(
                code="generation_regeneration_base_invalid",
                message="Regeneration base revision is invalid",
            )
        if payload.get("platforms") != [variant.platform]:
            raise PermanentJobError(
                code="generation_regeneration_platform_invalid",
                message="Regeneration platform does not match the target variant",
            )
        # Do not reject solely because the committed child is now current:
        # a worker may have crashed after the pack handler durably stored
        # its exact artifact. The pack handler either replays that artifact
        # and verifies its immutable parent, or its pre-provider callback
        # rejects a genuinely stale base before another paid call.
        payload.update(
            {"story_revision_id": str(pack.story_revision_id), "brand_profile_id": str(pack.brand_profile_id)}
        )
        delegated_job = await checkpoint_execution(job, context, payload=payload)
        fence_owner = None
        if (
            isinstance(getattr(job, "attempt_count", None), int)
            and job.attempt_count > 0
            and isinstance(getattr(job, "lease_owner", None), str)
            and bool(job.lease_owner.strip())
        ):
            fence_owner = RegenerationFenceOwner(
                workflow_job_id=job.id,
                workflow_attempt=job.attempt_count,
                lease_owner=job.lease_owner,
            )
        try:
            pack_handler = (
                build_pack_generation_handler(profile_resolver)
                if fault_injector is None
                else build_pack_generation_handler(
                    profile_resolver,
                    fault_injector=fault_injector,
                )
            )
            return await pack_handler(delegated_job, context)
        except Exception:
            if fence_owner is not None:
                await context.session.rollback()
                locked_variant = await context.session.scalar(
                    select(PlatformVariant)
                    .where(PlatformVariant.id == variant.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if locked_variant is not None:
                    await clear_regeneration_fence(
                        context.session,
                        variant_id=variant.id,
                        owner=fence_owner,
                    )
                await context.session.commit()
            raise

    return handle
