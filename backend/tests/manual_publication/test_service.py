from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

NOW = datetime(2026, 7, 13, 8, 30, tzinfo=UTC)


def _citation() -> dict[str, object]:
    return {
        "evidence_key": "evidence:one",
        "evidence_snapshot_id": str(uuid4()),
        "source_url": "https://example.com/report",
        "locator": "chars:0-12",
        "excerpt_sha256": "a" * 64,
    }


def _instagram_content() -> dict[str, object]:
    return {
        "hook": "What changed?",
        "caption": "A grounded caption for a manual Instagram post.",
        "cta": "Read the cited report.",
        "hashtags": ["#NewsCraft"],
        "alt_text": "A source image illustrating the update.",
        "carousel": [],
        "citations": [_citation()],
        "manual_checklist": ["Provider prose is not used as a persistence key"],
    }


def _revision_fixture(*, approval_state: str = "approved", revision_number: int = 1):
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.models import PlatformVariant, PlatformVariantRevision

    variant = PlatformVariant(id=uuid4(), content_pack_id=uuid4(), platform="instagram")
    content = _instagram_content()
    evidence_map = [content["citations"][0]]
    revision = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=revision_number,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
        evidence_map=evidence_map,
        validation_results=[{"gate": "platform_schema", "ok": True, "reason": None}],
        approval_state=approval_state,
        approval_note=None,
        approved_at=NOW if approval_state == "approved" else None,
        created_by="test",
    )
    return variant, revision


class _Session:
    def __init__(self, *, variant, revisions, plans=()):
        self.variant = variant
        self.revisions = list(revisions)
        self.plans = list(plans)
        self.added: list[object] = []
        self.locked_entities: list[type] = []
        self.flushes = 0

    async def get(self, model, identifier):
        from app.generation.models import PlatformVariant, PlatformVariantRevision
        from app.manual_publication.models import ManualPublicationPlan

        if model is PlatformVariant:
            return self.variant if self.variant.id == identifier else None
        if model is PlatformVariantRevision:
            return next((item for item in self.revisions if item.id == identifier), None)
        if model is ManualPublicationPlan:
            return next((item for item in self.plans if item.id == identifier), None)
        raise AssertionError(f"unexpected get model: {model}")

    async def scalar(self, statement):
        from app.generation.models import PlatformVariant, PlatformVariantRevision
        from app.manual_publication.models import ManualPublicationPlan

        description = statement.column_descriptions[0]
        entity = description.get("entity")
        expression = description.get("expr")
        sql = str(statement)
        params = statement.compile().params
        identifiers = {value for value in params.values() if isinstance(value, UUID)}
        if "FOR UPDATE" in sql:
            self.locked_entities.append(entity)
        if entity is PlatformVariant:
            return self.variant if not identifiers or self.variant.id in identifiers else None
        if entity is PlatformVariantRevision:
            if expression is PlatformVariantRevision.id:
                matching = [item for item in self.revisions if item.platform_variant_id == self.variant.id]
                if not matching:
                    return None
                return max(matching, key=lambda item: (item.revision_number, item.id)).id
            return next((item for item in self.revisions if item.id in identifiers), None)
        if entity is ManualPublicationPlan:
            if "status IN" in sql:
                return next(
                    (
                        item
                        for item in self.plans
                        if item.platform_variant_revision_id in identifiers and item.status in {"planned", "ready"}
                    ),
                    None,
                )
            return next((item for item in self.plans if item.id in identifiers), None)
        raise AssertionError(f"unexpected scalar statement: {statement}")

    def add(self, value):
        from app.manual_publication.models import ManualPublicationPlan

        if isinstance(value, ManualPublicationPlan) and value not in self.plans:
            self.plans.append(value)
        self.added.append(value)

    async def flush(self):
        self.flushes += 1
        for value in self.plans:
            if value.id is None:
                value.id = uuid4()


def _service(session):
    from app.manual_publication.service import ManualPublicationService

    return ManualPublicationService(session, now=lambda: NOW)


def _events(session):
    from app.jobs.models import WorkflowEvent

    return [item for item in session.added if isinstance(item, WorkflowEvent)]


def test_manual_checklist_ids_are_stable_platform_contracts_not_generated_prose():
    from app.manual_publication.service import manual_checklist_for

    instagram = manual_checklist_for("instagram")
    assert [item.id for item in instagram] == [
        "copy_reviewed",
        "citations_verified",
        "media_and_alt_text_ready",
        "platform_requirements_rechecked",
    ]
    assert all(item.label and "Provider prose" not in item.label for item in instagram)
    assert {item.id for item in manual_checklist_for("x")} != {item.id for item in instagram}
    assert {item.id for item in manual_checklist_for("blog")} != {item.id for item in instagram}


@pytest.mark.asyncio
async def test_latest_plan_for_revision_is_read_only_and_uses_stable_newest_order():
    from app.manual_publication.models import ManualPublicationPlan
    from app.manual_publication.service import ManualPublicationService, manual_checklist_for

    _variant, revision = _revision_fixture()
    latest = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW + timedelta(hours=1),
        display_timezone="Asia/Tehran",
        status="planned",
        checklist_state={item.id: False for item in manual_checklist_for("instagram")},
    )

    class ReadSession:
        statement = None

        async def scalar(self, statement):
            self.statement = statement
            return latest

    session = ReadSession()
    result = await ManualPublicationService(session).latest_plan_for_revision(revision.id)

    assert result is latest
    sql = str(session.statement)
    assert "manual_publication_plans.platform_variant_revision_id =" in sql
    assert "manual_publication_plans.created_at DESC" in sql
    assert "manual_publication_plans.id DESC" in sql
    assert "FOR UPDATE" not in sql


@pytest.mark.asyncio
async def test_create_plan_locks_variant_revision_plan_and_persists_exact_approved_revision():
    from app.manual_publication.models import ManualPublicationPlan

    variant, revision = _revision_fixture()
    session = _Session(variant=variant, revisions=[revision])

    plan = await _service(session).create_plan(
        revision.id,
        NOW + timedelta(hours=2),
        "Asia/Tehran",
    )

    assert plan.platform_variant_revision_id == revision.id
    assert plan.platform == "instagram"
    assert plan.scheduled_for == NOW + timedelta(hours=2)
    assert plan.status == "planned"
    assert set(plan.checklist_state) == {
        item.id
        for item in __import__(
            "app.manual_publication.service", fromlist=["manual_checklist_for"]
        ).manual_checklist_for("instagram")
    }
    assert not any(plan.checklist_state.values())
    assert session.locked_entities[:3] == [
        type(variant),
        type(revision),
        ManualPublicationPlan,
    ]
    assert [event.event_type for event in _events(session)] == ["manual_publication.plan.created"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("pending", "revision is not approved"),
        ("stale_hash", "content hash"),
        ("invalid_schema", "schema-valid"),
        ("not_current", "revision is not current"),
        ("telegram", "manual platform"),
    ],
)
async def test_create_plan_rejects_non_publishable_exact_revisions(mutation, message):
    from app.generation.models import PlatformVariantRevision
    from app.manual_publication.service import ManualPublicationError

    variant, revision = _revision_fixture(approval_state="pending_review" if mutation == "pending" else "approved")
    revisions = [revision]
    if mutation == "stale_hash":
        revision.content_hash = "0" * 64
    elif mutation == "invalid_schema":
        from app.automations.telegram.handlers import sha256_canonical

        revision.content = {"caption": "incomplete"}
        revision.content_hash = sha256_canonical({"content": revision.content, "evidence_map": revision.evidence_map})
    elif mutation == "not_current":
        newer = PlatformVariantRevision(
            id=uuid4(),
            platform_variant_id=variant.id,
            parent_revision_id=revision.id,
            generation_attempt_id=None,
            revision_number=2,
            content=revision.content,
            content_hash=revision.content_hash,
            evidence_map=revision.evidence_map,
            validation_results=[],
            approval_state="approved",
            approved_at=NOW,
            created_by="test",
        )
        revisions.append(newer)
    elif mutation == "telegram":
        variant.platform = "telegram"

    with pytest.raises(ManualPublicationError, match=message):
        await _service(_Session(variant=variant, revisions=revisions)).create_plan(
            revision.id,
            NOW + timedelta(hours=1),
            "Asia/Tehran",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scheduled_for", "timezone", "message"),
    [
        (datetime(2026, 7, 13, 9, 30), "Asia/Tehran", "timezone-aware"),
        (NOW, "Asia/Tehran", "strictly in the future"),
        (NOW + timedelta(hours=1), "Mars/Olympus", "IANA timezone"),
    ],
)
async def test_create_plan_requires_future_aware_schedule_and_iana_timezone(scheduled_for, timezone, message):
    from app.manual_publication.service import ManualPublicationError

    variant, revision = _revision_fixture()
    with pytest.raises(ManualPublicationError, match=message):
        await _service(_Session(variant=variant, revisions=[revision])).create_plan(
            revision.id,
            scheduled_for,
            timezone,
        )


@pytest.mark.asyncio
async def test_create_plan_rechecks_future_schedule_after_waiting_for_domain_locks():
    from app.manual_publication.service import ManualPublicationError, ManualPublicationService

    variant, revision = _revision_fixture()
    session = _Session(variant=variant, revisions=[revision])
    service = ManualPublicationService(
        session,
        now=lambda: NOW + timedelta(hours=2) if session.locked_entities else NOW,
    )

    with pytest.raises(ManualPublicationError, match="strictly in the future"):
        await service.create_plan(revision.id, NOW + timedelta(hours=1), "Asia/Tehran")


@pytest.mark.asyncio
async def test_create_plan_exact_replay_reuses_without_event_but_conflicting_active_plan_is_409():
    from app.manual_publication.models import ManualPublicationPlan
    from app.manual_publication.service import ManualPublicationError

    variant, revision = _revision_fixture()
    existing = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW + timedelta(hours=2),
        display_timezone="Asia/Tehran",
        status="planned",
        checklist_state={item: False for item in ("copy_reviewed",)},
    )
    replay_session = _Session(variant=variant, revisions=[revision], plans=[existing])

    assert (
        await _service(replay_session).create_plan(revision.id, existing.scheduled_for, existing.display_timezone)
        is existing
    )
    assert _events(replay_session) == []

    with pytest.raises(ManualPublicationError) as error:
        await _service(_Session(variant=variant, revisions=[revision], plans=[existing])).create_plan(
            revision.id,
            existing.scheduled_for + timedelta(hours=1),
            existing.display_timezone,
        )
    assert error.value.status_code == 409
    assert error.value.code == "active_plan_conflict"


@pytest.mark.asyncio
async def test_cancelled_plan_is_preserved_while_new_active_plan_is_created_for_exact_revision():
    from app.manual_publication.models import ManualPublicationPlan
    from app.manual_publication.service import manual_checklist_for

    variant, revision = _revision_fixture()
    cancelled = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW + timedelta(hours=1),
        display_timezone="Asia/Tehran",
        status="cancelled",
        checklist_state={item.id: False for item in manual_checklist_for("instagram")},
    )
    session = _Session(variant=variant, revisions=[revision], plans=[cancelled])

    replacement = await _service(session).create_plan(
        revision.id,
        NOW + timedelta(hours=3),
        "Asia/Tehran",
    )

    assert cancelled in session.plans
    assert cancelled.status == "cancelled"
    assert replacement is not cancelled
    assert replacement.platform_variant_revision_id == revision.id
    assert replacement.status == "planned"
    assert [plan for plan in session.plans if plan.status in {"planned", "ready"}] == [replacement]
    assert [event.event_type for event in _events(session)] == ["manual_publication.plan.created"]


@pytest.mark.asyncio
async def test_create_plan_exact_replay_remains_idempotent_after_scheduled_instant_passes():
    from app.manual_publication.models import ManualPublicationPlan

    variant, revision = _revision_fixture()
    existing = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW - timedelta(minutes=1),
        display_timezone="Asia/Tehran",
        status="planned",
        checklist_state={"copy_reviewed": False},
    )
    session = _Session(variant=variant, revisions=[revision], plans=[existing])

    replay = await _service(session).create_plan(
        revision.id,
        existing.scheduled_for,
        existing.display_timezone,
    )

    assert replay is existing
    assert _events(session) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("rejected", "revision is not approved"),
        ("hash", "content hash"),
        ("schema", "schema-valid"),
        ("not_current", "revision is not current"),
    ],
)
async def test_active_replay_still_enforces_exact_revision_gates(mutation, message):
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.models import PlatformVariantRevision
    from app.manual_publication.models import ManualPublicationPlan
    from app.manual_publication.service import ManualPublicationError, manual_checklist_for

    variant, revision = _revision_fixture()
    revisions = [revision]
    if mutation == "rejected":
        revision.approval_state = "rejected"
    elif mutation == "hash":
        revision.content_hash = "0" * 64
    elif mutation == "schema":
        revision.content = {"caption": "incomplete"}
        revision.content_hash = sha256_canonical({"content": revision.content, "evidence_map": revision.evidence_map})
    else:
        revisions.append(
            PlatformVariantRevision(
                id=uuid4(),
                platform_variant_id=variant.id,
                parent_revision_id=revision.id,
                generation_attempt_id=None,
                revision_number=2,
                content=revision.content,
                content_hash=revision.content_hash,
                evidence_map=revision.evidence_map,
                validation_results=[],
                approval_state="approved",
                approved_at=NOW,
                created_by="test",
            )
        )
    existing = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW + timedelta(hours=1),
        display_timezone="Asia/Tehran",
        status="planned",
        checklist_state={item.id: False for item in manual_checklist_for("instagram")},
    )

    with pytest.raises(ManualPublicationError, match=message):
        await _service(_Session(variant=variant, revisions=revisions, plans=[existing])).create_plan(
            revision.id,
            existing.scheduled_for,
            existing.display_timezone,
        )


@pytest.mark.asyncio
async def test_checklist_partial_updates_drive_ready_iff_all_items_are_checked_and_replay_is_quiet():
    from app.manual_publication.models import ManualPublicationPlan
    from app.manual_publication.service import manual_checklist_for

    variant, revision = _revision_fixture()
    initial = {item.id: False for item in manual_checklist_for("instagram")}
    plan = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW + timedelta(hours=2),
        display_timezone="Asia/Tehran",
        status="planned",
        checklist_state=initial,
    )
    session = _Session(variant=variant, revisions=[revision], plans=[plan])
    service = _service(session)

    await service.update_checklist(plan.id, {next(iter(initial)): True})
    assert plan.status == "planned"
    await service.update_checklist(plan.id, {key: True for key in initial})
    assert plan.status == "ready"
    event_count = len(_events(session))
    await service.update_checklist(plan.id, dict(plan.checklist_state))
    assert len(_events(session)) == event_count
    await service.update_checklist(plan.id, {next(iter(initial)): False})
    assert plan.status == "planned"


@pytest.mark.asyncio
async def test_checklist_rejects_unknown_non_boolean_and_terminal_mutation():
    from app.manual_publication.models import ManualPublicationPlan
    from app.manual_publication.service import ManualPublicationError, manual_checklist_for

    variant, revision = _revision_fixture()
    state = {item.id: False for item in manual_checklist_for("instagram")}
    plan = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW + timedelta(hours=1),
        display_timezone="Asia/Tehran",
        status="planned",
        checklist_state=state,
    )
    service = _service(_Session(variant=variant, revisions=[revision], plans=[plan]))
    with pytest.raises(ManualPublicationError, match="unknown checklist"):
        await service.update_checklist(plan.id, {"provider_generated_prose": True})
    with pytest.raises(ManualPublicationError, match="boolean"):
        await service.update_checklist(plan.id, {next(iter(state)): 1})
    plan.status = "cancelled"
    with pytest.raises(ManualPublicationError, match="terminal"):
        await service.update_checklist(plan.id, {next(iter(state)): True})


@pytest.mark.asyncio
async def test_mark_published_requires_ready_and_revalidates_current_approval_hash_and_schema():
    from app.manual_publication.models import ManualPublicationPlan
    from app.manual_publication.service import ManualPublicationError, manual_checklist_for

    variant, revision = _revision_fixture()
    state = {item.id: True for item in manual_checklist_for("instagram")}
    plan = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW + timedelta(hours=1),
        display_timezone="Asia/Tehran",
        status="planned",
        checklist_state=state,
    )
    with pytest.raises(ManualPublicationError, match="ready"):
        await _service(_Session(variant=variant, revisions=[revision], plans=[plan])).mark_published(plan.id)

    plan.status = "ready"
    revision.approval_state = "rejected"
    with pytest.raises(ManualPublicationError, match="revision is not approved"):
        await _service(_Session(variant=variant, revisions=[revision], plans=[plan])).mark_published(
            plan.id,
            external_url="https://instagram.com/p/rejected",
        )


@pytest.mark.asyncio
async def test_mark_published_allows_missing_external_url_and_replays_exactly():
    from app.manual_publication.models import ManualPublicationPlan
    from app.manual_publication.service import manual_checklist_for

    variant, revision = _revision_fixture()
    plan = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW + timedelta(hours=1),
        display_timezone="Asia/Tehran",
        status="ready",
        checklist_state={item.id: True for item in manual_checklist_for("instagram")},
    )

    session = _Session(variant=variant, revisions=[revision], plans=[plan])
    service = _service(session)

    completed = await service.mark_published(plan.id)

    assert completed.status == "manual_published"
    assert completed.external_url is None
    assert completed.operator_note is None
    assert completed.completed_at == NOW
    assert _events(session)[0].event_data["has_external_url"] is False
    assert await service.mark_published(plan.id) is plan
    assert len(_events(session)) == 1


@pytest.mark.asyncio
async def test_mark_published_preserves_identity_evidence_and_exact_replay_has_one_redacted_event():
    from app.manual_publication.models import ManualPublicationPlan
    from app.manual_publication.service import manual_checklist_for

    variant, revision = _revision_fixture()
    state = {item.id: True for item in manual_checklist_for("instagram")}
    plan = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW + timedelta(hours=1),
        display_timezone="Asia/Tehran",
        status="ready",
        checklist_state=state,
    )
    session = _Session(variant=variant, revisions=[revision], plans=[plan])
    service = _service(session)
    url = "https://instagram.com/p/abc?token=do-not-log"
    note = "Posted from mobile password=do-not-log"

    completed = await service.mark_published(plan.id, external_url=url, note=note)
    assert completed.platform_variant_revision_id == revision.id
    assert completed.status == "manual_published"
    assert completed.completed_at == NOW
    assert completed.external_url == url
    assert completed.operator_note == note
    event = _events(session)[0]
    assert event.event_type == "manual_publication.plan.published"
    assert "do-not-log" not in str(event.event_data)
    assert event.event_data["has_external_url"] is True
    assert event.event_data["has_operator_note"] is True

    assert await service.mark_published(plan.id, external_url=url, note=note) is plan
    assert len(_events(session)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/post",
        "https://user:password@example.com/post",
        "https:///missing-host",
        "https://example.com/post\nnext",
    ],
)
async def test_mark_published_rejects_unsafe_external_url(url):
    from app.manual_publication.models import ManualPublicationPlan
    from app.manual_publication.service import ManualPublicationError, manual_checklist_for

    variant, revision = _revision_fixture()
    plan = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW + timedelta(hours=1),
        display_timezone="Asia/Tehran",
        status="ready",
        checklist_state={item.id: True for item in manual_checklist_for("instagram")},
    )
    with pytest.raises(ManualPublicationError, match="HTTP"):
        await _service(_Session(variant=variant, revisions=[revision], plans=[plan])).mark_published(
            plan.id, external_url=url
        )


@pytest.mark.asyncio
async def test_cancel_is_idempotent_and_terminal_states_are_immutable():
    from app.manual_publication.models import ManualPublicationPlan
    from app.manual_publication.service import ManualPublicationError, manual_checklist_for

    variant, revision = _revision_fixture()
    plan = ManualPublicationPlan(
        id=uuid4(),
        platform_variant_revision_id=revision.id,
        platform="instagram",
        scheduled_for=NOW + timedelta(hours=1),
        display_timezone="Asia/Tehran",
        status="ready",
        checklist_state={item.id: True for item in manual_checklist_for("instagram")},
    )
    session = _Session(variant=variant, revisions=[revision], plans=[plan])
    service = _service(session)
    assert (await service.cancel(plan.id)).status == "cancelled"
    assert await service.cancel(plan.id) is plan
    assert [event.event_type for event in _events(session)] == ["manual_publication.plan.cancelled"]

    plan.status = "manual_published"
    with pytest.raises(ManualPublicationError, match="published"):
        await service.cancel(plan.id)


def test_manual_publication_errors_expose_stable_api_metadata():
    from app.manual_publication.service import ManualPublicationError

    error = ManualPublicationError("conflict", code="manual_conflict", status_code=409)
    assert error.code == "manual_conflict"
    assert error.status_code == 409
    assert str(error) == "conflict"
