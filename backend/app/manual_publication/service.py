from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.telegram.handlers import sha256_canonical
from app.generation.models import PlatformVariant, PlatformVariantRevision
from app.generation.multiplatform import MANUAL_PLATFORM_ADAPTERS
from app.generation.platform_schemas import PlatformPayload
from app.generation.platform_validation import validate_platform_payload
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent
from app.manual_publication.models import (
    CHECKLIST_IDS_BY_PLATFORM,
    MANUAL_PLATFORMS,
    ManualPublicationPlan,
)

ManualPlatform = Literal["instagram", "x", "blog"]
TERMINAL_STATUSES = frozenset({"manual_published", "cancelled"})


class ManualChecklistItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str


_CHECKLISTS: dict[str, tuple[ManualChecklistItem, ...]] = {
    "instagram": (
        ManualChecklistItem(id="copy_reviewed", label="Review caption, call to action, and hashtags"),
        ManualChecklistItem(id="citations_verified", label="Verify citations and source links"),
        ManualChecklistItem(
            id="media_and_alt_text_ready",
            label="Prepare media, carousel order, and alternative text",
        ),
        ManualChecklistItem(
            id="platform_requirements_rechecked",
            label="Recheck current Instagram publishing requirements",
        ),
    ),
    "x": (
        ManualChecklistItem(id="thread_order_reviewed", label="Review every post and thread order"),
        ManualChecklistItem(
            id="citations_and_links_verified",
            label="Verify citations, links, and link placement",
        ),
        ManualChecklistItem(
            id="media_and_alt_text_ready",
            label="Prepare media and alternative text",
        ),
        ManualChecklistItem(
            id="platform_requirements_rechecked",
            label="Recheck current X publishing requirements",
        ),
    ),
    "blog": (
        ManualChecklistItem(id="article_reviewed", label="Review title, excerpt, and complete article"),
        ManualChecklistItem(
            id="citations_and_links_verified",
            label="Verify citations, canonical sources, and links",
        ),
        ManualChecklistItem(id="seo_fields_reviewed", label="Review slug, tags, and SEO description"),
        ManualChecklistItem(
            id="media_and_alt_text_ready",
            label="Prepare hero media and alternative text",
        ),
    ),
}

if {
    platform: tuple(item.id for item in items)
    for platform, items in _CHECKLISTS.items()
} != CHECKLIST_IDS_BY_PLATFORM:
    raise RuntimeError("manual checklist model and service contracts diverged")


class ManualPublicationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "manual_publication_invalid",
        status_code: int = 422,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def manual_checklist_for(platform: str) -> tuple[ManualChecklistItem, ...]:
    try:
        return _CHECKLISTS[platform]
    except KeyError:
        raise ManualPublicationError(
            "platform is not a supported manual platform",
            code="manual_platform_unsupported",
        ) from None


def _canonical_checklist(platform: str, state: dict[str, bool] | None = None) -> dict[str, bool]:
    values = state or {}
    return {item.id: values.get(item.id, False) for item in manual_checklist_for(platform)}


def _is_complete(platform: str, state: dict[str, bool]) -> bool:
    expected = _canonical_checklist(platform, state)
    return set(state) == set(expected) and all(expected.values())


def _safe_url(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) > 2_048 or not value or any(character.isspace() for character in value):
        raise ManualPublicationError(
            "external URL must be a safe HTTP(S) URL",
            code="manual_external_url_invalid",
        )
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ManualPublicationError(
            "external URL must be a safe HTTP(S) URL",
            code="manual_external_url_invalid",
        ) from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not 1 <= port <= 65_535)
    ):
        raise ManualPublicationError(
            "external URL must be a safe HTTP(S) URL",
            code="manual_external_url_invalid",
        )
    return value


class ManualPublicationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self._now = now or (lambda: datetime.now(UTC))

    def _observed_at(self) -> datetime:
        observed_at = self._now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise RuntimeError("manual publication clock must be timezone-aware")
        return observed_at.astimezone(UTC)

    async def latest_plan_for_revision(
        self,
        revision_id: UUID,
    ) -> ManualPublicationPlan | None:
        return await self.session.scalar(
            select(ManualPublicationPlan)
            .where(ManualPublicationPlan.platform_variant_revision_id == revision_id)
            .order_by(
                ManualPublicationPlan.created_at.desc(),
                ManualPublicationPlan.id.desc(),
            )
            .limit(1)
        )

    async def _lock_revision_context(
        self,
        revision_id: UUID,
    ) -> tuple[PlatformVariant, PlatformVariantRevision]:
        provisional = await self.session.get(PlatformVariantRevision, revision_id)
        if provisional is None:
            raise ManualPublicationError(
                "revision not found",
                code="manual_revision_not_found",
                status_code=404,
            )
        variant = await self.session.scalar(
            select(PlatformVariant)
            .where(PlatformVariant.id == provisional.platform_variant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if variant is None:
            raise ManualPublicationError(
                "platform variant not found",
                code="manual_variant_not_found",
                status_code=404,
            )
        revision = await self.session.scalar(
            select(PlatformVariantRevision)
            .where(PlatformVariantRevision.id == revision_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if revision is None or revision.platform_variant_id != variant.id:
            raise ManualPublicationError(
                "revision identity changed",
                code="manual_revision_conflict",
                status_code=409,
            )
        return variant, revision

    async def _current_revision_id(self, variant_id: UUID) -> UUID | None:
        return await self.session.scalar(
            select(PlatformVariantRevision.id)
            .where(PlatformVariantRevision.platform_variant_id == variant_id)
            .order_by(
                PlatformVariantRevision.revision_number.desc(),
                PlatformVariantRevision.created_at.desc(),
                PlatformVariantRevision.id.desc(),
            )
            .limit(1)
        )

    async def _require_publishable_revision(
        self,
        variant: PlatformVariant,
        revision: PlatformVariantRevision,
    ) -> PlatformPayload:
        if variant.platform not in MANUAL_PLATFORMS:
            raise ManualPublicationError(
                "revision is not for a supported manual platform",
                code="manual_platform_unsupported",
            )
        if revision.approval_state != "approved":
            raise ManualPublicationError(
                "revision is not approved",
                code="manual_revision_not_approved",
                status_code=409,
            )
        expected_hash = sha256_canonical(
            {"content": revision.content, "evidence_map": revision.evidence_map}
        )
        if revision.content_hash != expected_hash:
            raise ManualPublicationError(
                "revision content hash is invalid",
                code="manual_revision_hash_mismatch",
                status_code=409,
            )
        adapter = MANUAL_PLATFORM_ADAPTERS[variant.platform]
        try:
            payload = adapter.model_validate(revision.content)
        except ValidationError as exc:
            raise ManualPublicationError(
                "revision content is not schema-valid",
                code="manual_revision_schema_invalid",
                status_code=409,
            ) from exc
        issues = validate_platform_payload(variant.platform, payload)
        if any(issue.severity == "error" for issue in issues):
            raise ManualPublicationError(
                "revision content is not schema-valid",
                code="manual_revision_validation_failed",
                status_code=409,
            )
        if await self._current_revision_id(variant.id) != revision.id:
            raise ManualPublicationError(
                "revision is not current",
                code="manual_revision_not_current",
                status_code=409,
            )
        return payload

    async def _lock_plan_context(
        self,
        plan_id: UUID,
    ) -> tuple[PlatformVariant, PlatformVariantRevision, ManualPublicationPlan]:
        provisional_plan = await self.session.get(ManualPublicationPlan, plan_id)
        if provisional_plan is None:
            raise ManualPublicationError(
                "manual publication plan not found",
                code="manual_plan_not_found",
                status_code=404,
            )
        provisional_revision = await self.session.get(
            PlatformVariantRevision,
            provisional_plan.platform_variant_revision_id,
        )
        if provisional_revision is None:
            raise ManualPublicationError(
                "plan revision not found",
                code="manual_revision_not_found",
                status_code=409,
            )
        variant = await self.session.scalar(
            select(PlatformVariant)
            .where(PlatformVariant.id == provisional_revision.platform_variant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        revision = await self.session.scalar(
            select(PlatformVariantRevision)
            .where(PlatformVariantRevision.id == provisional_revision.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        plan = await self.session.scalar(
            select(ManualPublicationPlan)
            .where(ManualPublicationPlan.id == plan_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if variant is None or revision is None or plan is None:
            raise ManualPublicationError(
                "manual publication plan identity changed",
                code="manual_plan_conflict",
                status_code=409,
            )
        if (
            revision.platform_variant_id != variant.id
            or plan.platform_variant_revision_id != revision.id
            or plan.platform != variant.platform
        ):
            raise ManualPublicationError(
                "manual publication plan identity is invalid",
                code="manual_plan_identity_invalid",
                status_code=409,
            )
        return variant, revision, plan

    async def _record_event(
        self,
        event_type: str,
        plan: ManualPublicationPlan,
        *,
        observed_at: datetime,
        extra: dict[str, object] | None = None,
    ) -> None:
        event_data: dict[str, object] = {
            "plan_id": str(plan.id),
            "revision_id": str(plan.platform_variant_revision_id),
            "platform": plan.platform,
            "status": plan.status,
        }
        if extra:
            event_data.update(extra)
        self.session.add(
            WorkflowEvent(
                workflow_job_id=None,
                event_type=event_type,
                actor="operator",
                event_data=redact_event_data(event_data),
                created_at=observed_at,
            )
        )
        await self.session.flush()

    async def create_plan(
        self,
        revision_id: UUID,
        scheduled_for: datetime,
        display_timezone: str,
    ) -> ManualPublicationPlan:
        if scheduled_for.tzinfo is None or scheduled_for.utcoffset() is None:
            raise ManualPublicationError(
                "scheduled_for must be timezone-aware",
                code="manual_schedule_naive",
            )
        normalized_schedule = scheduled_for.astimezone(UTC)
        try:
            ZoneInfo(display_timezone)
        except (OSError, ZoneInfoNotFoundError, ValueError):
            raise ManualPublicationError(
                "display_timezone must be a valid IANA timezone",
                code="manual_timezone_invalid",
            ) from None

        variant, revision = await self._lock_revision_context(revision_id)
        await self._require_publishable_revision(variant, revision)
        existing = await self.session.scalar(
            select(ManualPublicationPlan)
            .where(
                ManualPublicationPlan.platform_variant_revision_id == revision.id,
                ManualPublicationPlan.status.in_(("planned", "ready")),
            )
            .order_by(ManualPublicationPlan.created_at.desc(), ManualPublicationPlan.id.desc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            existing_schedule = existing.scheduled_for
            if existing_schedule.tzinfo is None or existing_schedule.utcoffset() is None:
                raise ManualPublicationError(
                    "stored plan schedule is invalid",
                    code="manual_plan_schedule_invalid",
                    status_code=409,
                )
            if (
                existing_schedule.astimezone(UTC) == normalized_schedule
                and existing.display_timezone == display_timezone
            ):
                return existing
            raise ManualPublicationError(
                "revision already has a conflicting active manual publication plan",
                code="active_plan_conflict",
                status_code=409,
            )

        observed_at = self._observed_at()
        if normalized_schedule <= observed_at:
            raise ManualPublicationError(
                "scheduled_for must be strictly in the future",
                code="manual_schedule_not_future",
            )
        plan = ManualPublicationPlan(
            platform_variant_revision_id=revision.id,
            platform=variant.platform,
            scheduled_for=normalized_schedule,
            display_timezone=display_timezone,
            status="planned",
            checklist_state=_canonical_checklist(variant.platform),
            external_url=None,
            operator_note=None,
            completed_at=None,
            updated_at=observed_at,
        )
        self.session.add(plan)
        await self.session.flush()
        await self._record_event(
            "manual_publication.plan.created",
            plan,
            observed_at=observed_at,
            extra={"scheduled_for": normalized_schedule.isoformat()},
        )
        return plan

    async def update_checklist(
        self,
        plan_id: UUID,
        checklist_state: dict[str, bool],
    ) -> ManualPublicationPlan:
        _variant, _revision, plan = await self._lock_plan_context(plan_id)
        if plan.status in TERMINAL_STATUSES:
            raise ManualPublicationError(
                "terminal manual publication plans are immutable",
                code="manual_plan_terminal",
                status_code=409,
            )
        expected_ids = set(CHECKLIST_IDS_BY_PLATFORM[plan.platform])
        unknown = set(checklist_state) - expected_ids
        if unknown:
            raise ManualPublicationError(
                "unknown checklist item",
                code="manual_checklist_item_unknown",
            )
        if any(type(value) is not bool for value in checklist_state.values()):
            raise ManualPublicationError(
                "checklist values must be boolean",
                code="manual_checklist_value_invalid",
            )
        current = _canonical_checklist(plan.platform, plan.checklist_state)
        updated = current | checklist_state
        next_status = "ready" if _is_complete(plan.platform, updated) else "planned"
        if updated == current and plan.status == next_status:
            return plan
        observed_at = self._observed_at()
        changed_ids = sorted(
            key for key in updated if current.get(key) != updated.get(key)
        )
        plan.checklist_state = updated
        plan.status = next_status
        plan.updated_at = observed_at
        await self._record_event(
            "manual_publication.plan.checklist_updated",
            plan,
            observed_at=observed_at,
            extra={"changed_item_ids": changed_ids},
        )
        return plan

    async def mark_published(
        self,
        plan_id: UUID,
        *,
        external_url: str | None = None,
        note: str | None = None,
    ) -> ManualPublicationPlan:
        variant, revision, plan = await self._lock_plan_context(plan_id)
        if plan.status == "manual_published":
            safe_url = _safe_url(external_url)
            if plan.external_url == safe_url and plan.operator_note == note:
                return plan
            raise ManualPublicationError(
                "published manual publication plan is immutable",
                code="manual_plan_terminal",
                status_code=409,
            )
        if plan.status == "cancelled":
            raise ManualPublicationError(
                "cancelled manual publication plan is terminal",
                code="manual_plan_terminal",
                status_code=409,
            )
        if plan.status != "ready" or not _is_complete(plan.platform, plan.checklist_state):
            raise ManualPublicationError(
                "manual publication plan is not ready",
                code="manual_plan_not_ready",
                status_code=409,
            )
        safe_url = _safe_url(external_url)
        if note is not None and (len(note) > 2_000 or "\x00" in note):
            raise ManualPublicationError(
                "operator note is invalid",
                code="manual_operator_note_invalid",
            )
        await self._require_publishable_revision(variant, revision)
        observed_at = self._observed_at()
        plan.status = "manual_published"
        plan.external_url = safe_url
        plan.operator_note = note
        plan.completed_at = observed_at
        plan.updated_at = observed_at
        await self._record_event(
            "manual_publication.plan.published",
            plan,
            observed_at=observed_at,
            extra={
                "completed_at": observed_at.isoformat(),
                "has_external_url": safe_url is not None,
                "has_operator_note": note is not None,
            },
        )
        return plan

    async def cancel(self, plan_id: UUID) -> ManualPublicationPlan:
        _variant, _revision, plan = await self._lock_plan_context(plan_id)
        if plan.status == "cancelled":
            return plan
        if plan.status == "manual_published":
            raise ManualPublicationError(
                "published manual publication plan cannot be cancelled",
                code="manual_plan_terminal",
                status_code=409,
            )
        observed_at = self._observed_at()
        plan.status = "cancelled"
        plan.updated_at = observed_at
        await self._record_event(
            "manual_publication.plan.cancelled",
            plan,
            observed_at=observed_at,
        )
        return plan
