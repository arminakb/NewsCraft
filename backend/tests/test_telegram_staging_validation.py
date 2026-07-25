from argparse import Namespace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.faults import InjectedFault
from app.jobs.errors import NeedsReviewJobError
from app.validation import telegram_staging


def _args(scenario="success"):
    return Namespace(
        scenario=scenario,
        destination_id=str(uuid4()),
        revision_id=str(uuid4()),
        content_hash="a" * 64,
        marker="NC-STAGING-ABCDEF12",
        expected_target_ref="-100123456789",
        expected_chat_id=-100123456789,
        expected_chat_title="NewsCraft Private Staging",
        authorization_ticket="CHANGE-123",
        observer_one="editor-a",
        observer_two="editor-b",
        secret_root="/run/secrets",
        signing_key_file="/run/secrets/signing",
        output="report.json",
        confirm_live_send=scenario in {"success", "ambiguity"},
        expected_operation_count=1,
        expected_remote_message_count=1,
        remote_message_ids="501",
        observation_ticket="OBS-123",
        confirm_exactly_one_remote_marker=scenario == "verify",
        evidence_json="",
    )


def _state(*, ambiguous=False, publication=True):
    return {
        "publish_job_id": str(uuid4()),
        "publish_status": "reconciliation_required" if ambiguous else "succeeded",
        "workflow_job_id": str(uuid4()),
        "workflow_status": "queued",
        "publication_id": str(uuid4()) if publication else None,
        "publication_payload_hash": "a" * 64 if publication else None,
        "publication_remote_message_ids": [501] if publication else [],
        "publication_permalink": None,
        "reconciliation_status": "confirmed" if publication else None,
        "receipts": [
            {
                "operation_index": 0,
                "operation_key": "telegram:0:safe",
                "method": "sendMessage",
                "request_hash": "b" * 64,
                "status": "ambiguous" if ambiguous else "succeeded",
                "attempt_count": 1,
                "remote_message_ids": [] if ambiguous else [501],
                "response_metadata": {},
                "ambiguous_at": "2026-07-19T00:00:00+00:00" if ambiguous else None,
            }
        ],
    }


class _Http:
    async def aclose(self):
        return None


class _Telegram:
    async def get_chat(self, target_ref, token):
        assert token == "staging-token-canary"
        return {"id": -100123456789, "type": "channel", "title": "NewsCraft Private Staging"}

    async def execute(self, operation, token):
        return SimpleNamespace(remote_message_ids=(501,), response_metadata={"ok": True})


def _patch_boundaries(monkeypatch, state):
    destination = SimpleNamespace(
        id=uuid4(),
        target_ref="-100123456789",
        secret_ref="TELEGRAM_STAGING_TOKEN",
    )

    async def preflight(args):
        return destination, SimpleNamespace(), SimpleNamespace()

    async def enqueue(args):
        return uuid4()

    async def durable_state(publish_job_id):
        return state

    monkeypatch.setattr(telegram_staging, "_load_preflight", preflight)
    monkeypatch.setattr(telegram_staging, "_enqueue", enqueue)
    monkeypatch.setattr(telegram_staging, "_state", durable_state)
    monkeypatch.setattr(telegram_staging, "build_outbound_http_client", lambda **kwargs: _Http())
    monkeypatch.setattr(telegram_staging, "TelegramBotClient", lambda http: _Telegram())
    monkeypatch.setattr(
        telegram_staging,
        "FileSecretResolver",
        lambda root: SimpleNamespace(resolve=lambda reference: "staging-token-canary"),
    )


def test_staging_arguments_require_explicit_scope_two_observers_and_authorization(monkeypatch):
    args = _args()
    monkeypatch.setenv("NEWSCRAFT_LIVE_TELEGRAM_STAGING", "authorized")
    telegram_staging._validate_common_arguments(args)

    args.observer_two = args.observer_one
    with pytest.raises(telegram_staging.StagingQualificationError, match="distinct"):
        telegram_staging._validate_common_arguments(args)


async def test_success_sends_once_and_replay_does_not_send_again(monkeypatch):
    args = _args("success")
    _patch_boundaries(monkeypatch, _state())
    calls = 0

    async def publish_once(job_id, *, client, resolver, fault_injector=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return await client.execute(SimpleNamespace(), "staging-token-canary")
        return {"idempotent": True}

    monkeypatch.setattr(telegram_staging, "_publish_once", publish_once)
    report = await telegram_staging._run(args)

    assert report["remote_send_count"] == 1
    assert report["remote_ids_observed_before_fault"] == [501]
    assert report["publish"]["publication_payload_hash"] == args.content_hash
    assert "staging-token-canary" not in str(report)


async def test_success_rejects_remote_ids_that_do_not_match_the_publication(monkeypatch):
    args = _args("success")
    mismatched = _state()
    mismatched["publication_remote_message_ids"] = [999]
    _patch_boundaries(monkeypatch, mismatched)

    async def publish_once(job_id, *, client, resolver, fault_injector=None):
        if client.send_count == 0:
            return await client.execute(SimpleNamespace(), "staging-token-canary")
        return {"idempotent": True}

    monkeypatch.setattr(telegram_staging, "_publish_once", publish_once)
    with pytest.raises(telegram_staging.StagingQualificationError, match="exact local publication"):
        await telegram_staging._run(args)


async def test_ambiguity_stops_after_send_and_replay_requires_reconciliation(monkeypatch):
    args = _args("ambiguity")
    _patch_boundaries(monkeypatch, _state(ambiguous=True, publication=False))
    calls = 0

    async def publish_once(job_id, *, client, resolver, fault_injector=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            await client.execute(SimpleNamespace(), "staging-token-canary")
            raise InjectedFault("telegram.after_send_before_receipt", {})
        raise NeedsReviewJobError(
            code="telegram_publish_reconciliation_required",
            message="Telegram publish requires reconciliation",
        )

    monkeypatch.setattr(telegram_staging, "_publish_once", publish_once)
    report = await telegram_staging._run(args)

    assert report["remote_send_count"] == 1
    assert report["primary_error"] == "injected_after_send_before_receipt"
    assert report["replay_error"] == "telegram_publish_reconciliation_required"
    assert report["publish"]["publication_id"] is None


async def test_dry_run_calls_no_remote_send_and_creates_no_publication(monkeypatch):
    args = _args("dry-run")
    _patch_boundaries(monkeypatch, _state(publication=False))

    async def publish_once(job_id, *, client, resolver, fault_injector=None):
        raise NeedsReviewJobError(code="telegram_publish_gate_blocked", message="Dry run")

    monkeypatch.setattr(telegram_staging, "_publish_once", publish_once)
    report = await telegram_staging._run(args)

    assert report["remote_send_count"] == 0
    assert report["publish"]["publication_id"] is None


async def test_verify_rejects_a_public_channel_permalink_mismatch(monkeypatch):
    args = _args("verify")
    args.expected_target_ref = "@newscraft_stage"
    destination = SimpleNamespace(
        id=uuid4(),
        target_ref="@newscraft_stage",
        secret_ref="TELEGRAM_STAGING_TOKEN",
    )
    publication = SimpleNamespace(
        payload_hash=args.content_hash,
        reconciliation_status="confirmed",
        remote_message_ids=[501],
        permalink="https://t.me/newscraft_stage/999",
        publish_job_id=uuid4(),
    )

    async def preflight(_args):
        return destination, SimpleNamespace(), SimpleNamespace()

    class Session:
        async def scalar(self, statement):
            return publication

    class SessionContext:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(telegram_staging, "_load_preflight", preflight)
    monkeypatch.setattr(telegram_staging, "async_session", lambda: SessionContext())
    monkeypatch.setattr(telegram_staging, "build_outbound_http_client", lambda **kwargs: _Http())
    monkeypatch.setattr(telegram_staging, "TelegramBotClient", lambda http: _Telegram())
    monkeypatch.setattr(
        telegram_staging,
        "FileSecretResolver",
        lambda root: SimpleNamespace(resolve=lambda reference: "staging-token-canary"),
    )

    with pytest.raises(telegram_staging.StagingQualificationError, match="manual observation"):
        await telegram_staging._verify(args)
