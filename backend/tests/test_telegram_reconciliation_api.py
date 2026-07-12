from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app.api.telegram_drafts import (
    TelegramReconcileIn,
    _publication_out,
    _publish_job_out,
    _validate_reconciled_remote_ids,
    get_telegram_draft_media,
    router,
)
from app.publishing.telegram.service import PublishValidationError, validate_reconciliation


def _receipt(index: int, status: str):
    return SimpleNamespace(operation_index=index, status=status, remote_message_ids=[])


def test_reconciliation_schema_is_conservative():
    published = TelegramReconcileIn.model_validate(
        {"outcome": "published", "remote_message_ids": [501, 502], "permalink": "https://t.me/target/501"}
    )
    assert published.remote_message_ids == [501, 502]
    with pytest.raises(ValidationError):
        TelegramReconcileIn.model_validate({"outcome": "unknown"})
    with pytest.raises(ValidationError):
        TelegramReconcileIn.model_validate(
            {"outcome": "not_published", "permalink": "https://t.me/target/501"}
        )


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


def test_publish_job_read_and_reconciliation_routes_do_not_shadow_draft_routes():
    app = FastAPI()
    app.include_router(router)
    paths = set(app.openapi()["paths"])

    assert "/telegram/publish-jobs/{publish_job_id}" in paths
    assert "/telegram/publish-jobs/{publish_job_id}/reconcile" in paths
    assert "/telegram/drafts/{revision_id}" in paths
    assert "/telegram/drafts/{revision_id}/media/{media_asset_id}" in paths


@pytest.mark.asyncio
async def test_draft_media_preview_is_revision_scoped_checksum_verified_and_path_safe(tmp_path):
    revision_id = uuid4()
    media_id = uuid4()
    payload = b"exact captured image"
    path = tmp_path / "private-storage-name.jpg"
    path.write_bytes(payload)
    revision = SimpleNamespace(
        content={
            "body": "body",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": str(uuid4()),
            "source_url": "https://t.me/source/1",
            "media_policy": "preserve",
            "media_asset_ids": [str(media_id)],
            "direction": "rtl",
            "dry_run": False,
        }
    )
    asset = SimpleNamespace(
        id=media_id,
        kind="image",
        fetch_status="downloaded",
        storage_path=str(path),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        mime_type="image/jpeg",
    )

    class Session:
        async def scalar(self, statement):
            return revision

        async def get(self, model, key):
            return asset if key == media_id else None

    response = await get_telegram_draft_media(revision_id, media_id, Session())

    assert response.media_type == "image/jpeg"
    assert "telegram-media-" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert str(tmp_path) not in response.headers["content-disposition"]

    asset.checksum_sha256 = "0" * 64
    with pytest.raises(HTTPException) as error:
        await get_telegram_draft_media(revision_id, media_id, Session())
    assert error.value.status_code == 409
