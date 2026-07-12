from __future__ import annotations

import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.jobs.registry import build_default_registry
from app.publishing.telegram.service import (
    PublishValidationError,
    derive_telegram_permalink,
    ordered_receipt_remote_ids,
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


def test_registry_registers_publish_capability_only_with_complete_dependency_bundle():
    client = object()

    def resolver(ref):
        return "token"
    registry = build_default_registry(telegram_client=client, destination_secret_resolver=resolver)
    assert registry.job_types() == (
        "ingest.collect",
        "manual_intake",
        "story.group_pending",
        "telegram.destination.check",
        "telegram.publish",
    )
    with pytest.raises(ValueError, match="supplied together"):
        build_default_registry(telegram_client=client)
