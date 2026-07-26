from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api.telegram_drafts as telegram_api
from app.api.telegram_drafts import (
    TelegramReconcileIn,
    _publication_out,
    _publish_job_out,
    _validate_reconciled_remote_ids,
    reconcile_telegram_publish_job,
    router,
)
from app.automations.telegram.handlers import sha256_canonical
from app.db.session import get_session
from app.publishing.telegram.service import (
    PublishValidationError,
    ReconciliationCase,
    ReconciliationDestination,
    ReconciliationOperationSummary,
    validate_reconciliation,
)
from tests.capability_fakes import AVAILABLE_CAPABILITIES


def _receipt(index: int, status: str):
    return SimpleNamespace(operation_index=index, status=status, remote_message_ids=[])


def _durable_receipt(
    index: int,
    status: str,
    *,
    method: str = "sendMessage",
    attempt_count: int = 2,
    remote_message_ids: list[int] | None = None,
    ambiguous_at: datetime | None = None,
):
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        operation_index=index,
        operation_key=f"telegram:{index}:safe",
        method=method,
        request_hash=f"{index + 1}" * 64,
        status=status,
        attempt_count=attempt_count,
        remote_message_ids=list(remote_message_ids or []),
        response_metadata={},
        next_attempt_at=None,
        ambiguous_at=ambiguous_at,
        completed_at=now if status == "succeeded" else None,
        created_at=now,
        updated_at=now,
    )


def _decision_hash(
    *,
    outcome: str,
    remote_message_ids: list[int],
    permalink: str | None,
    operator_note: str | None,
) -> str:
    return sha256_canonical(
        {
            "operator_note": operator_note,
            "outcome": outcome,
            "permalink": permalink,
            "remote_message_ids": remote_message_ids,
        }
    )


def _publish_job(*, workflow_job_id=None, status="reconciliation_required"):
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(),
        workflow_job_id=workflow_job_id or uuid4(),
        destination_id=uuid4(),
        platform_variant_revision_id=uuid4(),
        status=status,
        payload_hash="a" * 64,
        scheduled_for=None,
        created_at=now,
        updated_at=now,
    )


def _publication(publish_job, *, remote_message_ids: list[int]):
    return SimpleNamespace(
        id=uuid4(),
        publish_job_id=publish_job.id,
        destination_id=publish_job.destination_id,
        platform_variant_revision_id=publish_job.platform_variant_revision_id,
        remote_message_ids=list(remote_message_ids),
        permalink="https://t.me/target/700",
        payload_hash=publish_job.payload_hash,
        published_at=datetime(2026, 7, 13, 12, tzinfo=UTC),
        reconciliation_status="confirmed",
    )


def _prior_decision_event(
    publish_job,
    receipt,
    *,
    outcome: str,
    decision_hash: str,
    ambiguous_at: datetime,
    publication_id=None,
    requeued_workflow_job_id=None,
    requeued_job_status=None,
    requeued_job_deduplicated=None,
):
    return SimpleNamespace(
        event_data={
            "publish_job_id": str(publish_job.id),
            "decision_hash": decision_hash,
            "operation_keys": [receipt.operation_key],
            "outcome": outcome,
            "remote_message_ids": list(receipt.remote_message_ids),
            "permalink": None,
            "operator_note": "[REDACTED]",
            "publication_id": str(publication_id) if publication_id is not None else None,
            "requeued_workflow_job_id": (
                str(requeued_workflow_job_id) if requeued_workflow_job_id is not None else None
            ),
            "requeued_job_status": requeued_job_status,
            "requeued_job_deduplicated": requeued_job_deduplicated,
            "reconciliation_generation": {
                "operation_key": receipt.operation_key,
                "attempt_count": receipt.attempt_count,
                "ambiguous_at": ambiguous_at.isoformat(),
            },
        }
    )


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class ReconciliationSession:
    def __init__(
        self,
        *,
        publish_job,
        receipts,
        prior_event=None,
        publication=None,
        destination=None,
        workflow_job=None,
        allow_writes=False,
    ):
        self.publish_job = publish_job
        self.receipts = list(receipts)
        self.prior_event = prior_event
        self.publication = publication
        self.destination = destination or SimpleNamespace(
            id=publish_job.destination_id,
            platform="telegram",
            target_ref="@target",
        )
        self.workflow_job = workflow_job
        self.allow_writes = allow_writes
        self.added: list[object] = []
        self.scalar_sql: list[str] = []

    def begin(self):
        return _Transaction()

    async def scalar(self, statement):
        sql = str(statement)
        self.scalar_sql.append(sql)
        if "FROM publish_jobs" in sql:
            return self.publish_job
        if "FROM workflow_events" in sql:
            return self.prior_event
        if "FROM publications" in sql:
            return self.publication
        if "FROM publish_attempts" in sql:
            raise AssertionError("Reconciliation must not query or update PublishAttempt")
        if "FROM automation_dispatches" in sql:
            return None
        raise AssertionError(f"Unexpected scalar query: {sql}")

    async def scalars(self, statement):
        sql = str(statement)
        if "FROM publish_operation_receipts" in sql:
            return list(self.receipts)
        if "FROM workflow_events" in sql:
            return [self.prior_event] if self.prior_event is not None else []
        raise AssertionError(f"Unexpected scalars query: {sql}")

    async def get(self, model, identity):
        if model.__name__ == "Destination" and identity == self.publish_job.destination_id:
            return self.destination
        if model.__name__ == "WorkflowJob" and self.workflow_job is not None:
            if identity == self.workflow_job.id:
                return self.workflow_job
        if model.__name__ == "PlatformVariantRevision":
            return None
        return None

    def add(self, value):
        if not self.allow_writes:
            raise AssertionError("Exact replay and conflicts must be read-only")
        self.added.append(value)

    async def flush(self):
        if not self.allow_writes:
            raise AssertionError("Exact replay and conflicts must not flush")
        for value in self.added:
            if value.__class__.__name__ == "Publication" and value.id is None:
                value.id = uuid4()


def test_reconciliation_schema_is_conservative():
    published = TelegramReconcileIn.model_validate(
        {
            "outcome": "published",
            "remote_message_ids": [501, 502],
            "permalink": "https://t.me/target/501",
            "operator_note": "Verified in the destination channel",
        }
    )
    assert published.remote_message_ids == [501, 502]
    assert published.operator_note == "Verified in the destination channel"
    assert (
        TelegramReconcileIn.model_validate(
            {
                "outcome": "not_published",
                "operator_note": "  Verified manually  ",
            }
        ).operator_note
        == "Verified manually"
    )
    assert TelegramReconcileIn.model_validate({"outcome": "not_published"}).operator_note is None
    with pytest.raises(ValidationError):
        TelegramReconcileIn.model_validate({"outcome": "unknown"})
    with pytest.raises(ValidationError):
        TelegramReconcileIn.model_validate({"outcome": "not_published", "permalink": "https://t.me/target/501"})
    for invalid_note in ("four", "     ", "x" * 1_001):
        with pytest.raises(ValidationError):
            TelegramReconcileIn.model_validate({"outcome": "not_published", "operator_note": invalid_note})


def test_published_reconciliation_only_confirms_one_ambiguous_operation_with_all_others_succeeded():
    receipts = [_receipt(0, "succeeded"), _receipt(1, "ambiguous")]
    ambiguous = validate_reconciliation(receipts, outcome="published", remote_message_ids=[501, 502])
    assert ambiguous.operation_index == 1

    for invalid in (
        [_receipt(0, "pending"), _receipt(1, "ambiguous")],
        [_receipt(0, "ambiguous"), _receipt(1, "ambiguous")],
        [_receipt(0, "succeeded")],
    ):
        with pytest.raises(PublishValidationError):
            validate_reconciliation(invalid, outcome="published", remote_message_ids=[501])


def test_not_published_resets_only_one_ambiguous_operation_and_requires_no_remote_ids():
    receipts = [_receipt(0, "succeeded"), _receipt(1, "ambiguous")]
    assert validate_reconciliation(receipts, outcome="not_published", remote_message_ids=[]).operation_index == 1
    with pytest.raises(PublishValidationError):
        validate_reconciliation(receipts, outcome="not_published", remote_message_ids=[501])
    with pytest.raises(PublishValidationError):
        validate_reconciliation(
            [_receipt(0, "dispatching"), _receipt(1, "ambiguous")],
            outcome="not_published",
            remote_message_ids=[],
        )


@pytest.mark.parametrize(
    ("method", "remote_ids", "valid"),
    [
        ("sendMessage", [501], True),
        ("sendPhoto", [501], True),
        ("sendMessage", [501, 502], False),
        ("sendMediaGroup", [501], False),
        ("sendMediaGroup", [501, 502], True),
        ("sendMediaGroup", [501, 501], False),
    ],
)
def test_operator_confirmed_ids_must_match_operation_semantics(method, remote_ids, valid):
    receipt = SimpleNamespace(method=method)
    if valid:
        _validate_reconciled_remote_ids(receipt, remote_ids)
    else:
        with pytest.raises(HTTPException) as error:
            _validate_reconciled_remote_ids(receipt, remote_ids)
        assert error.value.status_code == 422


def test_operator_confirmed_ids_must_match_persisted_exact_upload_count():
    receipt = SimpleNamespace(method="sendMediaGroup")

    _validate_reconciled_remote_ids(receipt, [501, 502, 503], expected_count=3)
    with pytest.raises(HTTPException) as error:
        _validate_reconciled_remote_ids(receipt, [501, 502], expected_count=3)

    assert error.value.status_code == 422


def test_publish_job_projection_contains_only_safe_durable_fields():
    now = datetime.now(UTC)
    publish_job = SimpleNamespace(
        id=uuid4(),
        workflow_job_id=uuid4(),
        destination_id=uuid4(),
        platform_variant_revision_id=uuid4(),
        status="reconciliation_required",
        payload_hash="a" * 64,
        scheduled_for=None,
        created_at=now,
        updated_at=now,
    )
    receipt = SimpleNamespace(
        id=uuid4(),
        operation_index=0,
        operation_key="telegram:0:safe",
        method="sendMessage",
        request_hash="b" * 64,
        status="ambiguous",
        attempt_count=1,
        remote_message_ids=[],
        response_metadata={"error": "timeout", "authorization": "secret-token"},
        next_attempt_at=None,
        ambiguous_at=now,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )

    output = _publish_job_out(publish_job, [receipt], None)
    encoded = json.dumps(output, default=str)

    assert output["receipts"][0]["operation_key"] == "telegram:0:safe"
    assert output["receipts"][0]["response_metadata"]["authorization"] == "[REDACTED]"
    assert "storage_path" not in encoded
    assert "secret_ref" not in encoded
    assert "secret-token" not in encoded


def test_publication_projection_is_exact_and_secret_free():
    publication = SimpleNamespace(
        id=uuid4(),
        publish_job_id=uuid4(),
        destination_id=uuid4(),
        platform_variant_revision_id=uuid4(),
        remote_message_ids=[501, 502],
        permalink="https://t.me/target/501",
        payload_hash="a" * 64,
        published_at=datetime.now(UTC),
        reconciliation_status="confirmed",
    )

    output = _publication_out(publication)

    assert output["remote_message_ids"] == [501, 502]
    assert output["reconciliation_status"] == "confirmed"
    assert "secret_ref" not in output


def test_publication_and_reconciliation_routes_are_public():
    app = FastAPI()
    app.include_router(router)
    paths = set(app.openapi()["paths"])

    assert "/telegram/publish-jobs/{publish_job_id}" in paths
    assert "/telegram/publish-jobs/{publish_job_id}/reconcile" in paths
    assert "/telegram/reconciliation" in paths
    assert "/telegram/reconciliation/{publish_job_id}" in paths
    assert "/telegram/publication-outcomes" in paths
    assert "/telegram/revisions/{revision_id}/publication-context" in paths


def test_reconciliation_case_routes_use_strict_read_only_service_projections(monkeypatch):
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    publish_job_id = uuid4()
    case = ReconciliationCase(
        publish_job_id=publish_job_id,
        publish_status="reconciliation_required",
        workflow_job_id=uuid4(),
        platform_variant_revision_id=uuid4(),
        destination=ReconciliationDestination(
            id=uuid4(),
            name="Newsroom",
            target_ref="@newsroom",
        ),
        operations=[
            ReconciliationOperationSummary(
                operation_index=0,
                operation_key="telegram:0:safe",
                method="sendMessage",
                request_hash="a" * 64,
                status="ambiguous",
                attempt_count=2,
                remote_message_ids=[],
                sent_at=now,
            )
        ],
        ambiguous_operation_key="telegram:0:safe",
        ambiguous_at=now,
        ambiguity_reason="Telegram outcome is ambiguous",
    )
    session = object()
    calls: list[tuple[str, object]] = []

    async def fake_list(received_session):
        calls.append(("list", received_session))
        return [case]

    async def fake_get(received_session, received_publish_job_id):
        calls.append(("detail", received_session))
        assert received_publish_job_id == publish_job_id
        return case

    monkeypatch.setattr(telegram_api, "list_reconciliation_cases", fake_list, raising=False)
    monkeypatch.setattr(telegram_api, "get_reconciliation_case", fake_get, raising=False)
    api = FastAPI()
    api.include_router(router)

    async def override_session():
        yield session

    api.dependency_overrides[get_session] = override_session
    with TestClient(api) as client:
        listed = client.get("/telegram/reconciliation")
        detail = client.get(f"/telegram/reconciliation/{publish_job_id}")

    assert listed.status_code == detail.status_code == 200
    assert listed.json() == [detail.json()]
    assert detail.json() == case.model_dump(mode="json")
    assert calls == [("list", session), ("detail", session)]


def test_reconciliation_detail_returns_404_for_missing_or_resolved_case(monkeypatch):
    async def fake_get(_session, _publish_job_id):
        return None

    monkeypatch.setattr(telegram_api, "get_reconciliation_case", fake_get, raising=False)
    api = FastAPI()
    api.include_router(router)

    async def override_session():
        yield object()

    api.dependency_overrides[get_session] = override_session
    with TestClient(api) as client:
        response = client.get(f"/telegram/reconciliation/{uuid4()}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_published_exact_decision_replay_reuses_immutable_publication():
    note = "Verified token=first-secret in the destination channel"
    ambiguity_time = datetime(2026, 7, 13, 11, 59, tzinfo=UTC)
    publish_job = _publish_job(status="succeeded")
    receipt = _durable_receipt(
        0,
        "succeeded",
        method="sendMediaGroup",
        remote_message_ids=[701, 702],
    )
    publication = _publication(publish_job, remote_message_ids=[701, 702])
    prior_event = _prior_decision_event(
        publish_job,
        receipt,
        outcome="published",
        decision_hash=_decision_hash(
            outcome="published",
            remote_message_ids=[701, 702],
            permalink=None,
            operator_note=note,
        ),
        ambiguous_at=ambiguity_time,
        publication_id=publication.id,
    )
    session = ReconciliationSession(
        publish_job=publish_job,
        receipts=[receipt],
        prior_event=prior_event,
        publication=publication,
    )

    result = await reconcile_telegram_publish_job(
        publish_job.id,
        TelegramReconcileIn(
            outcome="published",
            remote_message_ids=[701, 702],
            operator_note=note,
        ),
        Response(),
        session,
        AVAILABLE_CAPABILITIES,
    )

    assert result == _publication_out(publication)
    assert session.added == []
    assert not any("publish_attempts" in sql for sql in session.scalar_sql)


@pytest.mark.asyncio
async def test_not_published_exact_replay_returns_same_queued_job():
    note = "Checked the destination channel carefully"
    ambiguity_time = datetime(2026, 7, 13, 11, 59, tzinfo=UTC)
    workflow_job = SimpleNamespace(id=uuid4(), status="queued")
    publish_job = _publish_job(workflow_job_id=workflow_job.id, status="queued")
    receipt = _durable_receipt(0, "pending", attempt_count=3)
    prior_event = _prior_decision_event(
        publish_job,
        receipt,
        outcome="not_published",
        decision_hash=_decision_hash(
            outcome="not_published",
            remote_message_ids=[],
            permalink=None,
            operator_note=note,
        ),
        ambiguous_at=ambiguity_time,
        requeued_workflow_job_id=workflow_job.id,
        requeued_job_status="queued",
        requeued_job_deduplicated=False,
    )
    session = ReconciliationSession(
        publish_job=publish_job,
        receipts=[receipt],
        prior_event=prior_event,
        workflow_job=workflow_job,
    )
    response = Response()

    result = await reconcile_telegram_publish_job(
        publish_job.id,
        TelegramReconcileIn(outcome="not_published", operator_note=note),
        response,
        session,
        AVAILABLE_CAPABILITIES,
    )

    assert response.status_code == 202
    assert result["job"] == {
        "job_id": workflow_job.id,
        "status": "queued",
        "deduplicated": False,
    }
    assert session.added == []


@pytest.mark.asyncio
async def test_same_generation_conflict_uses_raw_note_hash_not_redacted_note():
    ambiguity_time = datetime(2026, 7, 13, 11, 59, tzinfo=UTC)
    publish_job = _publish_job(status="succeeded")
    receipt = _durable_receipt(0, "succeeded", remote_message_ids=[701])
    publication = _publication(publish_job, remote_message_ids=[701])
    first_note = "Verified token=first-secret in channel"
    second_note = "Verified token=second-secret in channel"
    prior_event = _prior_decision_event(
        publish_job,
        receipt,
        outcome="published",
        decision_hash=_decision_hash(
            outcome="published",
            remote_message_ids=[701],
            permalink=None,
            operator_note=first_note,
        ),
        ambiguous_at=ambiguity_time,
        publication_id=publication.id,
    )
    session = ReconciliationSession(
        publish_job=publish_job,
        receipts=[receipt],
        prior_event=prior_event,
        publication=publication,
    )

    with pytest.raises(HTTPException) as error:
        await reconcile_telegram_publish_job(
            publish_job.id,
            TelegramReconcileIn(
                outcome="published",
                remote_message_ids=[701],
                operator_note=second_note,
            ),
            Response(),
            session,
            AVAILABLE_CAPABILITIES,
        )

    assert error.value.status_code == 409
    assert error.value.detail == "Conflicting reconciliation decision"
    assert session.added == []


@pytest.mark.asyncio
async def test_new_ambiguity_generation_can_be_decided_and_records_complete_redacted_audit(
    monkeypatch,
):
    first_ambiguity = datetime(2026, 7, 13, 11, 50, tzinfo=UTC)
    second_ambiguity = datetime(2026, 7, 13, 12, tzinfo=UTC)
    old_note = "Checked token=old-secret in channel"
    new_note = "Checked token=new-secret in channel"
    succeeded = _durable_receipt(0, "succeeded", attempt_count=1, remote_message_ids=[700])
    ambiguous = _durable_receipt(
        1,
        "ambiguous",
        attempt_count=2,
        ambiguous_at=second_ambiguity,
    )
    requeued_job = SimpleNamespace(id=uuid4(), status="queued")
    publish_job = _publish_job(status="reconciliation_required")
    prior_event = _prior_decision_event(
        publish_job,
        SimpleNamespace(
            operation_key=ambiguous.operation_key,
            attempt_count=1,
            remote_message_ids=[],
        ),
        outcome="not_published",
        decision_hash=_decision_hash(
            outcome="not_published",
            remote_message_ids=[],
            permalink=None,
            operator_note=old_note,
        ),
        ambiguous_at=first_ambiguity,
        requeued_workflow_job_id=uuid4(),
    )
    session = ReconciliationSession(
        publish_job=publish_job,
        receipts=[succeeded, ambiguous],
        prior_event=prior_event,
        allow_writes=True,
    )

    async def fake_enqueue(_repository, **_kwargs):
        return SimpleNamespace(job=requeued_job, created=True)

    monkeypatch.setattr(
        "app.publishing.telegram.reconciliation_operation.JobRepository.enqueue_job",
        fake_enqueue,
    )

    response = Response()
    result = await reconcile_telegram_publish_job(
        publish_job.id,
        TelegramReconcileIn(outcome="not_published", operator_note=new_note),
        response,
        session,
        AVAILABLE_CAPABILITIES,
    )

    assert response.status_code == 202
    assert result["job"]["job_id"] == requeued_job.id
    assert succeeded.status == "succeeded"
    assert succeeded.remote_message_ids == [700]
    assert ambiguous.status == "pending"
    event = next(value for value in session.added if value.__class__.__name__ == "WorkflowEvent")
    assert event.event_data == {
        "publish_job_id": str(publish_job.id),
        "decision_hash": _decision_hash(
            outcome="not_published",
            remote_message_ids=[],
            permalink=None,
            operator_note=new_note,
        ),
        "operation_keys": [succeeded.operation_key, ambiguous.operation_key],
        "outcome": "not_published",
        "remote_message_ids": [],
        "permalink": None,
        "operator_note": "Checked token=[REDACTED] in channel",
        "requeued_workflow_job_id": str(requeued_job.id),
        "requeued_job_status": "queued",
        "requeued_job_deduplicated": False,
        "reconciliation_generation": {
            "operation_key": ambiguous.operation_key,
            "attempt_count": 2,
            "ambiguous_at": second_ambiguity.isoformat(),
        },
    }


@pytest.mark.asyncio
async def test_stale_exact_decision_from_older_generation_is_rejected(monkeypatch):
    first_ambiguity = datetime(2026, 7, 13, 11, 50, tzinfo=UTC)
    second_ambiguity = datetime(2026, 7, 13, 12, tzinfo=UTC)
    note = "Checked the destination channel carefully"
    publish_job = _publish_job(status="reconciliation_required")
    current_receipt = _durable_receipt(
        0,
        "ambiguous",
        attempt_count=2,
        ambiguous_at=second_ambiguity,
    )
    prior_event = _prior_decision_event(
        publish_job,
        SimpleNamespace(
            operation_key=current_receipt.operation_key,
            attempt_count=1,
            remote_message_ids=[],
        ),
        outcome="not_published",
        decision_hash=_decision_hash(
            outcome="not_published",
            remote_message_ids=[],
            permalink=None,
            operator_note=note,
        ),
        ambiguous_at=first_ambiguity,
        requeued_workflow_job_id=uuid4(),
    )
    session = ReconciliationSession(
        publish_job=publish_job,
        receipts=[current_receipt],
        prior_event=prior_event,
        allow_writes=True,
    )

    async def fake_enqueue(_repository, **_kwargs):
        return SimpleNamespace(
            job=SimpleNamespace(id=uuid4(), status="queued"),
            created=True,
        )

    monkeypatch.setattr(
        "app.publishing.telegram.reconciliation_operation.JobRepository.enqueue_job",
        fake_enqueue,
    )

    with pytest.raises(HTTPException) as error:
        await reconcile_telegram_publish_job(
            publish_job.id,
            TelegramReconcileIn(outcome="not_published", operator_note=note),
            Response(),
            session,
            AVAILABLE_CAPABILITIES,
        )

    assert error.value.status_code == 409
    assert error.value.detail == "Stale reconciliation decision"
    assert current_receipt.status == "ambiguous"
    assert session.added == []


@pytest.mark.asyncio
async def test_published_decision_uses_receipt_semantics_without_publish_attempt_dependency():
    ambiguity_time = datetime(2026, 7, 13, 12, tzinfo=UTC)
    note = "Verified in the destination channel"
    succeeded = _durable_receipt(0, "succeeded", remote_message_ids=[700])
    ambiguous = _durable_receipt(
        1,
        "ambiguous",
        method="sendMediaGroup",
        remote_message_ids=[],
        ambiguous_at=ambiguity_time,
    )
    publish_job = _publish_job(status="reconciliation_required")
    session = ReconciliationSession(
        publish_job=publish_job,
        receipts=[succeeded, ambiguous],
        allow_writes=True,
    )

    result = await reconcile_telegram_publish_job(
        publish_job.id,
        TelegramReconcileIn(
            outcome="published",
            remote_message_ids=[701, 702],
            operator_note=note,
        ),
        Response(),
        session,
        AVAILABLE_CAPABILITIES,
    )

    assert result["remote_message_ids"] == [700, 701, 702]
    assert succeeded.status == "succeeded"
    assert succeeded.remote_message_ids == [700]
    assert ambiguous.status == "succeeded"
    assert not any("publish_attempts" in sql for sql in session.scalar_sql)
    event = next(value for value in session.added if value.__class__.__name__ == "WorkflowEvent")
    assert event.event_data["operation_keys"] == [
        succeeded.operation_key,
        ambiguous.operation_key,
    ]
    assert event.event_data["operator_note"] == note
    assert event.event_data["outcome"] == "published"
    assert event.event_data["remote_message_ids"] == [701, 702]
    assert event.event_data["publication_id"] == str(result["id"])
