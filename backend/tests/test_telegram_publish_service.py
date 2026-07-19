from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

import app.publishing.telegram.service as telegram_service
from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.handlers import sha256_canonical
from app.generation.models import PlatformVariant, PlatformVariantRevision
from app.generation.telegram_schema import TelegramEvidenceCitation, TelegramVariantContent
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowJob
from app.jobs.registry import build_default_registry
from app.jobs.types import JobOrigin
from app.publishing.models import Destination, Publication, PublishJob
from app.publishing.telegram.service import (
    PublishValidationError,
    ReviewedTelegramScheduleError,
    _load_context,
    _revalidate_claim,
    derive_telegram_permalink,
    ordered_receipt_remote_ids,
    schedule_reviewed_telegram,
    validate_publish_evidence,
    validate_receipt_plan,
)


def test_service_evidence_validator_accepts_exact_nonempty_snapshot_without_http_errors():
    snapshot_id = uuid4()
    text = "exact evidence"
    digest = hashlib.sha256(text.encode()).hexdigest()
    snapshot = SimpleNamespace(
        id=snapshot_id,
        evidence_key="telegram.source.1",
        source_url="https://t.me/source/1",
        content_text=text,
        content_sha256=digest,
    )
    evidence = [
        {
            "evidence_snapshot_id": str(snapshot_id),
            "evidence_key": snapshot.evidence_key,
            "source_url": snapshot.source_url,
            "locator": f"chars:0-{len(text)}",
            "excerpt_sha256": digest,
        }
    ]

    assert validate_publish_evidence(evidence, [snapshot]) == evidence


@pytest.mark.parametrize("evidence,snapshots", [([], []), ([{"bad": True}], []), ([], [object()])])
def test_service_evidence_validator_fails_closed(evidence, snapshots):
    with pytest.raises(PublishValidationError):
        validate_publish_evidence(evidence, snapshots)


def test_receipt_plan_must_match_every_exact_operation_and_never_drift():
    operations = [
        SimpleNamespace(index=0, key="a", method="sendMessage", request_hash="1" * 64),
        SimpleNamespace(index=1, key="b", method="sendPhoto", request_hash="2" * 64),
    ]
    receipts = [
        SimpleNamespace(operation_index=0, operation_key="a", method="sendMessage", request_hash="1" * 64),
        SimpleNamespace(operation_index=1, operation_key="b", method="sendPhoto", request_hash="2" * 64),
    ]
    validate_receipt_plan(receipts, operations)
    receipts[1].request_hash = "f" * 64
    with pytest.raises(PublishValidationError, match="drift"):
        validate_receipt_plan(receipts, operations)


def test_ordered_remote_ids_and_public_permalink_are_deterministic():
    receipts = [
        SimpleNamespace(operation_index=1, remote_message_ids=[12, 13]),
        SimpleNamespace(operation_index=0, remote_message_ids=[11]),
    ]
    assert ordered_receipt_remote_ids(receipts) == [11, 12, 13]
    assert derive_telegram_permalink("@public_target", [11, 12]) == "https://t.me/public_target/11"
    assert derive_telegram_permalink("-100123", [11]) is None


def test_ordered_remote_ids_require_positive_unique_values():
    with pytest.raises(PublishValidationError):
        ordered_receipt_remote_ids([SimpleNamespace(operation_index=0, remote_message_ids=[0])])
    with pytest.raises(PublishValidationError):
        ordered_receipt_remote_ids(
            [
                SimpleNamespace(operation_index=0, remote_message_ids=[1]),
                SimpleNamespace(operation_index=1, remote_message_ids=[1]),
            ]
        )


class _ProjectionRows:
    def __init__(self, values):
        self.values = list(values)

    def __iter__(self):
        return iter(self.values)

    def all(self):
        return list(self.values)

    def first(self):
        return self.values[0] if self.values else None


class _ReconciliationProjectionSession:
    def __init__(self, *, job_rows=(), receipts=()):
        self.job_rows = list(job_rows)
        self.receipts = list(receipts)
        self.execute_statements = []
        self.scalar_statements = []

    async def execute(self, statement):
        self.execute_statements.append(statement)
        return _ProjectionRows(self.job_rows)

    async def scalars(self, statement):
        self.scalar_statements.append(statement)
        return _ProjectionRows(self.receipts)

    def add(self, _value):
        raise AssertionError("Reconciliation projections must remain read-only")

    def add_all(self, _values):
        raise AssertionError("Reconciliation projections must remain read-only")

    async def flush(self):
        raise AssertionError("Reconciliation projections must remain read-only")

    async def commit(self):
        raise AssertionError("Reconciliation projections must remain read-only")


def _reconciliation_projection_fixture():
    publish_job_id = uuid4()
    destination_id = uuid4()
    revision_id = uuid4()
    now = datetime(2026, 7, 13, 9, tzinfo=UTC)
    publish_job = SimpleNamespace(
        id=publish_job_id,
        workflow_job_id=uuid4(),
        destination_id=destination_id,
        platform_variant_revision_id=revision_id,
        status="reconciliation_required",
        updated_at=now,
    )
    destination = SimpleNamespace(
        id=destination_id,
        name="Editorial destination",
        target_ref="@editorial",
        secret_ref="TELEGRAM_BOT_TOKEN",
    )
    succeeded = SimpleNamespace(
        publish_job_id=publish_job_id,
        operation_index=0,
        operation_key="telegram:0:send-photo",
        method="sendPhoto",
        request_hash="a" * 64,
        status="succeeded",
        attempt_count=1,
        remote_message_ids=[701],
        response_metadata={
            "authorization": "Bearer receipt-secret",
            "headers": {"x-token": "header-secret"},
            "body": "upstream response body",
        },
        completed_at=now - timedelta(seconds=3),
        ambiguous_at=None,
        sanitized_payload={"token_ref": "TELEGRAM_BOT_TOKEN"},
    )
    ambiguous = SimpleNamespace(
        publish_job_id=publish_job_id,
        operation_index=1,
        operation_key="telegram:1:send-message",
        method="sendMessage",
        request_hash="b" * 64,
        status="ambiguous",
        attempt_count=1,
        remote_message_ids=[],
        response_metadata={"description": "timeout token=receipt-secret"},
        completed_at=None,
        ambiguous_at=now,
        sanitized_payload={"secret_ref": "TELEGRAM_BOT_TOKEN"},
    )
    return publish_job, destination, succeeded, ambiguous


@pytest.mark.asyncio
async def test_reconciliation_case_projection_is_strict_ordered_and_secret_free():
    publish_job, destination, succeeded, ambiguous = _reconciliation_projection_fixture()
    session = _ReconciliationProjectionSession(
        job_rows=[(publish_job, destination)],
        receipts=[ambiguous, succeeded],
    )

    cases = await telegram_service.list_reconciliation_cases(session)

    assert len(cases) == 1
    case = cases[0]
    assert case.publish_job_id == publish_job.id
    assert case.status == "pending"
    assert case.publish_status == "reconciliation_required"
    assert case.destination.model_dump() == {
        "id": destination.id,
        "name": "Editorial destination",
        "target_ref": "@editorial",
    }
    assert [operation.operation_index for operation in case.operations] == [0, 1]
    assert [operation.operation_key for operation in case.operations] == [
        "telegram:0:send-photo",
        "telegram:1:send-message",
    ]
    assert [operation.request_hash for operation in case.operations] == ["a" * 64, "b" * 64]
    assert [operation.status for operation in case.operations] == ["succeeded", "ambiguous"]
    assert [operation.sent_at for operation in case.operations] == [
        succeeded.completed_at,
        ambiguous.ambiguous_at,
    ]
    assert case.ambiguous_operation_key == ambiguous.operation_key
    assert case.ambiguous_at == ambiguous.ambiguous_at
    assert case.ambiguity_reason == "Telegram send outcome is ambiguous and requires operator verification"

    encoded = case.model_dump_json()
    for forbidden in (
        "sanitized_payload",
        "response_metadata",
        "authorization",
        "headers",
        "body",
        "secret_ref",
        "token_ref",
        "receipt-secret",
        "header-secret",
        "TELEGRAM_BOT_TOKEN",
    ):
        assert forbidden not in encoded

    invalid = case.model_dump(mode="json")
    invalid["destination"]["secret_ref"] = "TELEGRAM_BOT_TOKEN"
    with pytest.raises(ValidationError):
        type(case).model_validate(invalid)


@pytest.mark.asyncio
async def test_reconciliation_list_and_detail_are_open_case_read_models_keyed_by_publish_job():
    publish_job, destination, succeeded, ambiguous = _reconciliation_projection_fixture()
    list_session = _ReconciliationProjectionSession(
        job_rows=[(publish_job, destination)],
        receipts=[succeeded, ambiguous],
    )

    listed = await telegram_service.list_reconciliation_cases(list_session)

    assert [item.publish_job_id for item in listed] == [publish_job.id]
    list_sql = "\n".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in [*list_session.execute_statements, *list_session.scalar_statements]
    )
    assert "JOIN destinations" in list_sql
    assert "publish_operation_receipts.status = 'ambiguous'" in list_sql
    assert "ORDER BY publish_jobs.updated_at DESC, publish_jobs.id DESC" in list_sql
    assert "ORDER BY publish_operation_receipts.publish_job_id, publish_operation_receipts.operation_index" in list_sql
    assert all(keyword not in list_sql for keyword in ("UPDATE ", "DELETE ", "INSERT "))

    detail_session = _ReconciliationProjectionSession(
        job_rows=[(publish_job, destination)],
        receipts=[succeeded, ambiguous],
    )
    detail = await telegram_service.get_reconciliation_case(detail_session, publish_job.id)

    assert detail is not None
    assert detail.publish_job_id == publish_job.id
    detail_compiled = detail_session.execute_statements[0].compile(dialect=postgresql.dialect())
    assert publish_job.id in detail_compiled.params.values()
    assert "publish_operation_receipts.status" in str(detail_compiled)

    resolved_session = _ReconciliationProjectionSession(job_rows=[])
    assert await telegram_service.get_reconciliation_case(resolved_session, publish_job.id) is None
    assert resolved_session.scalar_statements == []


def test_registry_registers_publish_capability_only_with_complete_dependency_bundle():
    client = object()

    def resolver(ref):
        return "token"

    registry = build_default_registry(telegram_client=client, destination_secret_resolver=resolver)
    assert registry.job_types() == (
        "ingest.collect",
        "manual_intake",
        "operations.canary.publishing",
        "operations.canary.source_generation",
        "story.group_pending",
        "telegram.destination.check",
        "telegram.publish",
    )
    with pytest.raises(ValueError, match="supplied together"):
        build_default_registry(telegram_client=client)


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _ScheduleSession:
    def __init__(self, *, scalars, objects):
        self.scalar_results = list(scalars)
        self.objects = objects
        self.statements = []
        self.added = []
        self.flushes = 0

    async def scalar(self, statement):
        self.statements.append(statement)
        if not self.scalar_results:
            raise AssertionError(f"Unexpected scalar query: {statement}")
        return self.scalar_results.pop(0)

    async def get(self, model, identity, **kwargs):
        return self.objects.get((model, identity))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushes += 1
        for value in self.added:
            if hasattr(value, "id") and value.id is None:
                value.id = uuid4()

    def begin_nested(self):
        return _Transaction()


class _RacingScheduleSession(_ScheduleSession):
    def __init__(self, fixture, *, publish_job, workflow_job):
        super().__init__(
            scalars=[],
            objects={(AutomationRoute, fixture.route.id): fixture.route},
        )
        self.fixture = fixture
        self.publish_job = publish_job
        self.workflow_job = workflow_job
        self.table_calls = {}
        self.raise_insert_conflict = True

    async def scalar(self, statement):
        self.statements.append(statement)
        sql = str(statement)
        if "FROM platform_variants" in sql:
            return self.fixture.variant
        if "FROM platform_variant_revisions" in sql:
            count = self.table_calls.get("revisions", 0)
            self.table_calls["revisions"] = count + 1
            return self.fixture.revision.id if count == 2 else self.fixture.revision
        if "FROM publish_jobs" in sql:
            count = self.table_calls.get("publish_jobs", 0)
            self.table_calls["publish_jobs"] = count + 1
            return None if count == 0 else self.publish_job
        if "FROM destinations" in sql:
            return self.fixture.destination
        if "FROM workflow_jobs" in sql:
            count = self.table_calls.get("workflow_jobs", 0)
            self.table_calls["workflow_jobs"] = count + 1
            return None if self.raise_insert_conflict else self.workflow_job
        if "FROM publications" in sql:
            return None
        raise AssertionError(f"Unexpected scalar query: {statement}")

    async def flush(self):
        if self.raise_insert_conflict:
            self.raise_insert_conflict = False
            raise IntegrityError("insert publish job", {}, RuntimeError("unique conflict"))
        await super().flush()


def _schedule_fixture(*, approval_state="approved", dry_run=False, hash_drift=False):
    revision_id = uuid4()
    variant_id = uuid4()
    destination_id = uuid4()
    route_id = uuid4()
    dispatch_id = uuid4()
    evidence_id = uuid4()
    content = TelegramVariantContent(
        body="Reviewed Telegram copy",
        source_item_id=uuid4(),
        source_url="https://t.me/source/42",
        media_policy="omit",
        media_asset_ids=[],
        direction="rtl",
        dry_run=dry_run,
    ).model_dump(mode="json")
    evidence_map = [
        TelegramEvidenceCitation(
            evidence_snapshot_id=evidence_id,
            evidence_key="telegram.source.42",
            source_url="https://t.me/source/42",
            locator="chars:0-8",
            excerpt_sha256="e" * 64,
        ).model_dump(mode="json")
    ]
    content_hash = sha256_canonical({"content": content, "evidence_map": evidence_map})
    revision = SimpleNamespace(
        id=revision_id,
        platform_variant_id=variant_id,
        parent_revision_id=None,
        revision_number=3,
        content=content,
        evidence_map=evidence_map,
        validation_results=[{"gate": "telegram_schema", "ok": True, "reason": None}],
        approval_state=approval_state,
        content_hash="f" * 64 if hash_drift else content_hash,
    )
    variant = PlatformVariant(
        id=variant_id,
        content_pack_id=uuid4(),
        platform="telegram",
    )
    destination = Destination(
        id=destination_id,
        name="Editorial channel",
        platform="telegram",
        target_ref="@editorial",
        secret_ref="TELEGRAM_BOT_TOKEN",
        enabled=True,
        health_status="unknown",
    )
    route = AutomationRoute(
        id=route_id,
        source_id=uuid4(),
        destination_id=destination_id,
        brand_profile_id=uuid4(),
        prompt_template_version_id=uuid4(),
        ai_provider_profile_id=uuid4(),
        name="Reviewed route",
    )
    dispatch = SimpleNamespace(id=dispatch_id, route_id=route_id)
    return SimpleNamespace(
        revision=revision,
        variant=variant,
        destination=destination,
        route=route,
        dispatch=dispatch,
    )


def _schedule_request(fixture, due, *, content_hash=None, destination_id=None):
    return SimpleNamespace(
        content_hash=content_hash or fixture.revision.content_hash,
        destination_id=destination_id or fixture.destination.id,
        scheduled_for=due,
    )


def _schedule_session(fixture, *, publish_job=None, workflow_job=None, publication=None, latest_id=None):
    return _ScheduleSession(
        scalars=[
            fixture.revision,
            fixture.variant,
            fixture.revision,
            fixture.revision.id if latest_id is None else latest_id,
            publish_job,
            fixture.destination,
            workflow_job,
            *([publication] if publish_job is not None and workflow_job is not None else []),
        ],
        objects={
            (AutomationRoute, fixture.route.id): fixture.route,
        },
    )


@pytest.mark.asyncio
async def test_reviewed_schedule_creates_identical_durable_due_times_and_one_redacted_event(monkeypatch):
    fixture = _schedule_fixture()
    now = datetime(2026, 7, 13, 4, 0, tzinfo=UTC)
    due = datetime(2026, 7, 13, 9, 0, tzinfo=timezone(timedelta(hours=3, minutes=30)))
    normalized_due = due.astimezone(UTC)
    session = _schedule_session(fixture)
    observed = {}

    async def dispatch_for_revision(_session, revision):
        assert revision is fixture.revision
        return fixture.dispatch

    class Repository:
        def __init__(self, repository_session):
            assert repository_session is session

        async def enqueue_job(self, **kwargs):
            observed.update(kwargs)
            job = WorkflowJob(
                id=uuid4(),
                job_type=kwargs["job_type"],
                status="queued",
                payload=kwargs["payload"],
                idempotency_key=kwargs["idempotency_key"],
                origin=kwargs["origin"],
                pause_sensitive=kwargs["pause_sensitive"],
                scheduled_for=kwargs["scheduled_for"],
            )
            return SimpleNamespace(job=job, created=True)

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", dispatch_for_revision)
    monkeypatch.setattr("app.publishing.telegram.service.JobRepository", Repository)

    result = await schedule_reviewed_telegram(
        session,
        revision_id=fixture.revision.id,
        request=_schedule_request(fixture, due),
        clock=lambda: now,
    )

    key = f"telegram-publish:{fixture.destination.id}:{fixture.revision.id}:{fixture.revision.content_hash}"
    assert result.created is True
    assert result.publish_job.status == "scheduled"
    assert result.publish_job.scheduled_for == normalized_due
    assert result.publish_job.destination_id == fixture.destination.id
    assert result.publish_job.platform_variant_revision_id == fixture.revision.id
    assert result.publish_job.idempotency_key == key
    assert result.publish_job.payload_hash == fixture.revision.content_hash
    assert result.publish_job.workflow_job_id == result.workflow_job.id
    assert observed == {
        "job_type": "telegram.publish",
        "payload": {"publish_job_id": str(result.publish_job.id)},
        "idempotency_key": key,
        "origin": JobOrigin.MANUAL,
        "scheduled_for": normalized_due,
        "pause_sensitive": True,
    }
    scheduled_events = [
        item
        for item in session.added
        if isinstance(item, WorkflowEvent) and item.event_type == "telegram.publish.scheduled"
    ]
    assert len(scheduled_events) == 1
    assert scheduled_events[0].workflow_job_id == result.workflow_job.id
    assert scheduled_events[0].actor == "operator"
    assert "TELEGRAM_BOT_TOKEN" not in str(scheduled_events[0].event_data)
    query_order = [str(statement) for statement in session.statements]
    assert "platform_variant_revisions" in query_order[0]
    assert "FOR UPDATE" not in query_order[0]
    assert "platform_variants" in query_order[1]
    assert "FOR UPDATE" in query_order[1]
    assert "platform_variant_revisions" in query_order[2]
    assert "FOR UPDATE" in query_order[2]
    assert session.statements[2].get_execution_options().get("populate_existing") is True
    assert "platform_variant_revisions" in query_order[3]
    assert "publish_jobs" in query_order[4]
    assert "destinations" in query_order[5]
    assert "workflow_jobs" in query_order[6]


@pytest.mark.asyncio
async def test_reviewed_schedule_exact_replay_reuses_both_rows_without_event_or_enqueue(monkeypatch):
    fixture = _schedule_fixture()
    now = datetime(2026, 7, 13, 4, 0, tzinfo=UTC)
    due = now + timedelta(hours=2)
    key = f"telegram-publish:{fixture.destination.id}:{fixture.revision.id}:{fixture.revision.content_hash}"
    workflow = WorkflowJob(
        id=uuid4(),
        job_type="telegram.publish",
        status="queued",
        payload={},
        idempotency_key=key,
        origin="manual",
        pause_sensitive=True,
        scheduled_for=due,
    )
    publish = PublishJob(
        id=uuid4(),
        workflow_job_id=workflow.id,
        destination_id=fixture.destination.id,
        platform_variant_revision_id=fixture.revision.id,
        status="scheduled",
        idempotency_key=key,
        payload_hash=fixture.revision.content_hash,
        scheduled_for=due,
    )
    workflow.payload = {"publish_job_id": str(publish.id)}
    session = _schedule_session(fixture, publish_job=publish, workflow_job=workflow)

    async def dispatch_for_revision(_session, _revision):
        return fixture.dispatch

    class Repository:
        def __init__(self, _session):
            raise AssertionError("Exact replay must not call JobRepository")

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", dispatch_for_revision)
    monkeypatch.setattr("app.publishing.telegram.service.JobRepository", Repository)

    result = await schedule_reviewed_telegram(
        session,
        revision_id=fixture.revision.id,
        request=_schedule_request(fixture, due),
        clock=lambda: now,
    )

    assert result.created is False
    assert result.publish_job is publish
    assert result.workflow_job is workflow
    assert not [item for item in session.added if isinstance(item, WorkflowEvent)]


@pytest.mark.asyncio
async def test_reviewed_schedule_exact_replay_survives_a_lost_response_after_due_time(monkeypatch):
    fixture = _schedule_fixture()
    due = datetime(2026, 7, 13, 6, 0, tzinfo=UTC)
    now = due + timedelta(minutes=5)
    key = f"telegram-publish:{fixture.destination.id}:{fixture.revision.id}:{fixture.revision.content_hash}"
    workflow = WorkflowJob(
        id=uuid4(),
        job_type="telegram.publish",
        status="queued",
        payload={},
        idempotency_key=key,
        origin="manual",
        pause_sensitive=True,
        scheduled_for=due,
    )
    publish = PublishJob(
        id=uuid4(),
        workflow_job_id=workflow.id,
        destination_id=fixture.destination.id,
        platform_variant_revision_id=fixture.revision.id,
        status="scheduled",
        idempotency_key=key,
        payload_hash=fixture.revision.content_hash,
        scheduled_for=due,
    )
    workflow.payload = {"publish_job_id": str(publish.id)}
    session = _schedule_session(fixture, publish_job=publish, workflow_job=workflow)

    async def dispatch_for_revision(_session, _revision):
        return fixture.dispatch

    class Repository:
        def __init__(self, _session):
            raise AssertionError("Past-due exact replay must not enqueue")

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", dispatch_for_revision)
    monkeypatch.setattr("app.publishing.telegram.service.JobRepository", Repository)

    result = await schedule_reviewed_telegram(
        session,
        revision_id=fixture.revision.id,
        request=_schedule_request(fixture, due),
        clock=lambda: now,
    )

    assert result.created is False
    assert result.publish_job is publish
    assert result.workflow_job is workflow
    assert not [item for item in session.added if isinstance(item, WorkflowEvent)]


@pytest.mark.asyncio
async def test_reviewed_schedule_recovers_insert_race_as_exact_replay(monkeypatch):
    fixture = _schedule_fixture()
    now = datetime(2026, 7, 13, 4, 0, tzinfo=UTC)
    due = now + timedelta(hours=2)
    key = f"telegram-publish:{fixture.destination.id}:{fixture.revision.id}:{fixture.revision.content_hash}"
    workflow = WorkflowJob(
        id=uuid4(),
        job_type="telegram.publish",
        status="queued",
        payload={},
        idempotency_key=key,
        origin="manual",
        pause_sensitive=True,
        scheduled_for=due,
    )
    publish = PublishJob(
        id=uuid4(),
        workflow_job_id=workflow.id,
        destination_id=fixture.destination.id,
        platform_variant_revision_id=fixture.revision.id,
        status="scheduled",
        idempotency_key=key,
        payload_hash=fixture.revision.content_hash,
        scheduled_for=due,
    )
    workflow.payload = {"publish_job_id": str(publish.id)}
    session = _RacingScheduleSession(
        fixture,
        publish_job=publish,
        workflow_job=workflow,
    )

    async def dispatch_for_revision(_session, _revision):
        return fixture.dispatch

    class Repository:
        def __init__(self, _session):
            raise AssertionError("Recovered exact replay must not enqueue")

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", dispatch_for_revision)
    monkeypatch.setattr("app.publishing.telegram.service.JobRepository", Repository)

    result = await schedule_reviewed_telegram(
        session,
        revision_id=fixture.revision.id,
        request=_schedule_request(fixture, due),
        clock=lambda: now,
    )

    assert result.created is False
    assert result.publish_job is publish
    assert result.workflow_job is workflow
    assert session.table_calls["publish_jobs"] == 2
    assert not [item for item in session.added if isinstance(item, WorkflowEvent)]


@pytest.mark.asyncio
async def test_reviewed_schedule_maps_concurrent_immediate_intent_to_stable_conflict(monkeypatch):
    fixture = _schedule_fixture()
    now = datetime(2026, 7, 13, 4, 0, tzinfo=UTC)
    due = now + timedelta(hours=2)
    key = f"telegram-publish:{fixture.destination.id}:{fixture.revision.id}:{fixture.revision.content_hash}"
    workflow = WorkflowJob(
        id=uuid4(),
        job_type="telegram.publish",
        status="queued",
        payload={},
        idempotency_key=key,
        origin="automation",
        pause_sensitive=True,
        scheduled_for=now,
    )
    publish = PublishJob(
        id=uuid4(),
        workflow_job_id=workflow.id,
        destination_id=fixture.destination.id,
        platform_variant_revision_id=fixture.revision.id,
        status="queued",
        idempotency_key=key,
        payload_hash=fixture.revision.content_hash,
        scheduled_for=None,
    )
    workflow.payload = {"publish_job_id": str(publish.id)}
    session = _RacingScheduleSession(
        fixture,
        publish_job=publish,
        workflow_job=workflow,
    )

    async def dispatch_for_revision(_session, _revision):
        return fixture.dispatch

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", dispatch_for_revision)

    with pytest.raises(ReviewedTelegramScheduleError, match="conflicts"):
        await schedule_reviewed_telegram(
            session,
            revision_id=fixture.revision.id,
            request=_schedule_request(fixture, due),
            clock=lambda: now,
        )


@pytest.mark.parametrize(
    ("revision_changes", "request_changes", "destination_changes", "latest_changes", "match"),
    [
        ({"approval_state": "pending_review"}, {}, {}, {}, "approved"),
        ({"content": {"dry_run": False}}, {}, {}, {}, "schema"),
        ({"content": None}, {}, {}, {}, "schema"),
        ({}, {"content_hash": "a" * 64}, {}, {}, "content changed"),
        ({"content_hash": "f" * 64}, {}, {}, {}, "hash"),
        ({}, {}, {"platform": "instagram"}, {}, "Telegram"),
        ({}, {}, {"enabled": False}, {}, "enabled"),
        ({}, {}, {}, {"latest_id": uuid4()}, "current"),
    ],
)
@pytest.mark.asyncio
async def test_reviewed_schedule_rejects_unpublishable_revision_or_destination(
    monkeypatch,
    revision_changes,
    request_changes,
    destination_changes,
    latest_changes,
    match,
):
    fixture = _schedule_fixture()
    for key, value in revision_changes.items():
        setattr(fixture.revision, key, value)
    for key, value in destination_changes.items():
        setattr(fixture.destination, key, value)
    due = datetime(2026, 7, 13, 6, 0, tzinfo=UTC)
    request = _schedule_request(fixture, due, **request_changes)
    session = _schedule_session(fixture, **latest_changes)

    async def dispatch_for_revision(_session, _revision):
        return fixture.dispatch

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", dispatch_for_revision)

    with pytest.raises(ReviewedTelegramScheduleError, match=match):
        await schedule_reviewed_telegram(
            session,
            revision_id=fixture.revision.id,
            request=request,
            clock=lambda: datetime(2026, 7, 13, 5, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "due",
    [
        datetime(2026, 7, 13, 5, 0),
        datetime(2026, 7, 13, 5, 0, tzinfo=UTC),
        datetime(2026, 7, 13, 4, 59, 59, tzinfo=UTC),
    ],
)
@pytest.mark.asyncio
async def test_reviewed_schedule_requires_aware_strictly_future_due_time(monkeypatch, due):
    fixture = _schedule_fixture()
    session = _schedule_session(fixture)

    async def dispatch_for_revision(_session, _revision):
        return fixture.dispatch

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", dispatch_for_revision)

    with pytest.raises(ReviewedTelegramScheduleError, match="future|timezone-aware"):
        await schedule_reviewed_telegram(
            session,
            revision_id=fixture.revision.id,
            request=_schedule_request(fixture, due),
            clock=lambda: datetime(2026, 7, 13, 5, 0, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_reviewed_schedule_resamples_clock_after_lock_wait_before_new_insert(monkeypatch):
    fixture = _schedule_fixture()
    due = datetime(2026, 7, 13, 6, 0, tzinfo=UTC)
    observed_times = iter(
        [
            datetime(2026, 7, 13, 5, 59, tzinfo=UTC),
            datetime(2026, 7, 13, 6, 1, tzinfo=UTC),
        ]
    )
    session = _schedule_session(fixture)

    async def dispatch_for_revision(_session, _revision):
        return fixture.dispatch

    class Repository:
        def __init__(self, _session):
            raise AssertionError("Elapsed new schedule must not enqueue")

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", dispatch_for_revision)
    monkeypatch.setattr("app.publishing.telegram.service.JobRepository", Repository)

    with pytest.raises(ReviewedTelegramScheduleError, match="strictly in the future"):
        await schedule_reviewed_telegram(
            session,
            revision_id=fixture.revision.id,
            request=_schedule_request(fixture, due),
            clock=lambda: next(observed_times),
        )

    assert not [item for item in session.added if isinstance(item, PublishJob)]


@pytest.mark.asyncio
async def test_reviewed_schedule_resamples_after_enqueue_before_linking_or_event(monkeypatch):
    fixture = _schedule_fixture()
    due = datetime(2026, 7, 13, 6, 0, tzinfo=UTC)
    observed_times = iter(
        [
            datetime(2026, 7, 13, 5, 0, tzinfo=UTC),
            datetime(2026, 7, 13, 5, 30, tzinfo=UTC),
            datetime(2026, 7, 13, 6, 1, tzinfo=UTC),
        ]
    )
    session = _schedule_session(fixture)

    async def dispatch_for_revision(_session, _revision):
        return fixture.dispatch

    class Repository:
        def __init__(self, repository_session):
            assert repository_session is session

        async def enqueue_job(self, **kwargs):
            return SimpleNamespace(
                job=WorkflowJob(
                    id=uuid4(),
                    job_type=kwargs["job_type"],
                    status="queued",
                    payload=kwargs["payload"],
                    idempotency_key=kwargs["idempotency_key"],
                    origin=kwargs["origin"],
                    pause_sensitive=kwargs["pause_sensitive"],
                    scheduled_for=kwargs["scheduled_for"],
                ),
                created=True,
            )

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", dispatch_for_revision)
    monkeypatch.setattr("app.publishing.telegram.service.JobRepository", Repository)

    with pytest.raises(ReviewedTelegramScheduleError, match="strictly in the future"):
        await schedule_reviewed_telegram(
            session,
            revision_id=fixture.revision.id,
            request=_schedule_request(fixture, due),
            clock=lambda: next(observed_times),
        )

    created_publish_jobs = [item for item in session.added if isinstance(item, PublishJob)]
    assert len(created_publish_jobs) == 1
    assert created_publish_jobs[0].workflow_job_id is None
    assert not [
        item
        for item in session.added
        if isinstance(item, WorkflowEvent) and item.event_type == "telegram.publish.scheduled"
    ]


@pytest.mark.parametrize(
    ("publish_change", "workflow_change", "publication", "match"),
    [
        ({"scheduled_for": datetime(2026, 7, 13, 7, 0, tzinfo=UTC)}, {}, None, "conflicts"),
        ({"scheduled_for": None, "status": "queued"}, {}, None, "conflicts"),
        ({"status": "running"}, {}, None, "conflicts"),
        ({"status": "succeeded"}, {}, None, "conflicts"),
        ({}, {"scheduled_for": datetime(2026, 7, 13, 7, 0, tzinfo=UTC)}, None, "drift"),
        ({}, {"status": "running"}, None, "drift"),
        ({}, {"origin": "automation"}, None, "drift"),
        ({}, {"pause_sensitive": False}, None, "drift"),
        ({}, {"payload": {"publish_job_id": str(uuid4())}}, None, "drift"),
        ({}, {}, object(), "published"),
    ],
)
@pytest.mark.asyncio
async def test_reviewed_schedule_rejects_existing_intent_or_workflow_drift(
    monkeypatch,
    publish_change,
    workflow_change,
    publication,
    match,
):
    fixture = _schedule_fixture()
    now = datetime(2026, 7, 13, 5, 0, tzinfo=UTC)
    due = now + timedelta(hours=1)
    key = f"telegram-publish:{fixture.destination.id}:{fixture.revision.id}:{fixture.revision.content_hash}"
    workflow = WorkflowJob(
        id=uuid4(),
        job_type="telegram.publish",
        status="queued",
        payload={},
        idempotency_key=key,
        origin="manual",
        pause_sensitive=True,
        scheduled_for=due,
    )
    publish = PublishJob(
        id=uuid4(),
        workflow_job_id=workflow.id,
        destination_id=fixture.destination.id,
        platform_variant_revision_id=fixture.revision.id,
        status="scheduled",
        idempotency_key=key,
        payload_hash=fixture.revision.content_hash,
        scheduled_for=due,
    )
    workflow.payload = {"publish_job_id": str(publish.id)}
    for key_name, value in publish_change.items():
        setattr(publish, key_name, value)
    for key_name, value in workflow_change.items():
        setattr(workflow, key_name, value)
    session = _schedule_session(
        fixture,
        publish_job=publish,
        workflow_job=workflow,
        publication=publication,
    )

    async def dispatch_for_revision(_session, _revision):
        return fixture.dispatch

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", dispatch_for_revision)

    with pytest.raises(ReviewedTelegramScheduleError, match=match):
        await schedule_reviewed_telegram(
            session,
            revision_id=fixture.revision.id,
            request=_schedule_request(fixture, due),
            clock=lambda: now,
        )


@pytest.mark.asyncio
async def test_reviewed_schedule_requires_dispatch_ancestry_and_matching_route_destination(monkeypatch):
    fixture = _schedule_fixture()
    now = datetime(2026, 7, 13, 5, 0, tzinfo=UTC)
    due = now + timedelta(hours=1)

    async def missing_dispatch(_session, _revision):
        return None

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", missing_dispatch)
    with pytest.raises(ReviewedTelegramScheduleError, match="route provenance"):
        await schedule_reviewed_telegram(
            _schedule_session(fixture),
            revision_id=fixture.revision.id,
            request=_schedule_request(fixture, due),
            clock=lambda: now,
        )

    fixture.route.destination_id = uuid4()

    async def dispatch_for_revision(_session, _revision):
        return fixture.dispatch

    monkeypatch.setattr("app.publishing.telegram.service._revision_dispatch", dispatch_for_revision)
    with pytest.raises(ReviewedTelegramScheduleError, match="route.*destination"):
        await schedule_reviewed_telegram(
            _schedule_session(fixture),
            revision_id=fixture.revision.id,
            request=_schedule_request(fixture, due),
            clock=lambda: now,
        )


class _PublishLockProbeSession:
    def __init__(self, *, revision, publish_job):
        self.revision = revision
        self.publish_job = publish_job
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        entity = statement.column_descriptions[0].get("entity")
        sql = str(statement)
        if entity is PublishJob:
            if sql.lstrip().startswith("SELECT publish_jobs.platform_variant_revision_id"):
                return self.revision.id
            return self.publish_job
        if entity is PlatformVariantRevision:
            return self.revision
        if entity in {
            Publication,
            Destination,
            AutomationDispatch,
            AutomationRoute,
            AutomationControl,
        }:
            return None
        raise AssertionError(f"Unexpected scalar entity: {entity}")

    async def get(self, model, identity, **kwargs):
        return None


@pytest.mark.asyncio
async def test_publish_prepare_locks_fresh_revision_before_fresh_publish_job():
    revision = SimpleNamespace(id=uuid4(), platform_variant_id=uuid4())
    publish_job = PublishJob(
        id=uuid4(),
        destination_id=uuid4(),
        platform_variant_revision_id=revision.id,
        status="queued",
        idempotency_key="publish-lock-order",
        payload_hash="a" * 64,
    )
    session = _PublishLockProbeSession(revision=revision, publish_job=publish_job)

    from app.jobs.errors import PermanentJobError

    with pytest.raises(PermanentJobError, match="context is incomplete"):
        await _load_context(
            session,
            publish_job.id,
            datetime(2026, 7, 13, tzinfo=UTC),
        )

    locked = [statement for statement in session.statements if "FOR UPDATE" in str(statement)]
    assert [statement.column_descriptions[0].get("entity") for statement in locked[:2]] == [
        PlatformVariantRevision,
        PublishJob,
    ]
    assert all(statement.get_execution_options().get("populate_existing") is True for statement in locked[:2])


@pytest.mark.asyncio
async def test_publish_claim_revalidation_locks_fresh_revision_before_fresh_publish_job():
    revision_id = uuid4()
    publish_job = PublishJob(
        id=uuid4(),
        destination_id=uuid4(),
        platform_variant_revision_id=revision_id,
        status="queued",
        idempotency_key="claim-lock-order",
        payload_hash="a" * 64,
    )
    session = _PublishLockProbeSession(
        revision=SimpleNamespace(id=revision_id),
        publish_job=publish_job,
    )
    context = SimpleNamespace(
        revision_id=revision_id,
        publish_job_id=publish_job.id,
        dispatch_id=uuid4(),
        destination_id=publish_job.destination_id,
        route_id=uuid4(),
    )

    from app.jobs.errors import NeedsReviewJobError

    with pytest.raises(NeedsReviewJobError, match="context changed"):
        await _revalidate_claim(session, context)

    locked = [statement for statement in session.statements if "FOR UPDATE" in str(statement)]
    assert [statement.column_descriptions[0].get("entity") for statement in locked[:6]] == [
        PlatformVariantRevision,
        PublishJob,
        AutomationDispatch,
        AutomationRoute,
        AutomationControl,
        Destination,
    ]
    assert all(statement.get_execution_options().get("populate_existing") is True for statement in locked[:6])
