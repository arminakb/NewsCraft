from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.telegram_drafts import require_revision_transition
from app.generation.editorial_service import (
    ApprovalRequest,
    EditorialService,
    InvalidGenerationRequest,
)
from app.generation.revision_validation import (
    RevisionValidationError,
    validate_approvable_revision,
)


def revision(**changes):
    row = {
        "id": uuid4(),
        "content_hash": "a" * 64,
        "approval_state": "pending_review",
        "content": {
            "body": "Verified body",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": None,
            "source_url": None,
            "media_policy": "omit",
            "media_asset_ids": [],
            "direction": "ltr",
            "dry_run": False,
        },
        "evidence_map": [
            {
                "evidence_snapshot_id": str(uuid4()),
                "evidence_key": "source.1",
                "source_url": None,
                "locator": "chars:0-8",
                "excerpt_sha256": "b" * 64,
            }
        ],
        "validation_results": [{"gate": "telegram_schema", "ok": True, "reason": None}],
    }
    row.update(changes)
    return SimpleNamespace(**row)


@pytest.mark.parametrize(
    "changes",
    [
        {"content": {"body": "missing exact Telegram schema"}},
        {"evidence_map": []},
        {"evidence_map": [{"evidence_key": "broken"}]},
        {"validation_results": []},
        {"validation_results": [{"gate": "media", "ok": False, "reason": "missing"}]},
    ],
)
def test_central_revision_validator_fails_closed(changes):
    with pytest.raises(RevisionValidationError):
        validate_approvable_revision(revision(**changes))


def test_historical_valid_gate_without_reason_remains_compatible():
    validate_approvable_revision(revision(validation_results=[{"gate": "telegram_schema", "ok": True}]))


@pytest.mark.asyncio
async def test_editorial_approval_rejects_invalid_revision_without_state_mutation():
    invalid = revision(evidence_map=[])

    class Session:
        async def scalar(self, statement):
            return invalid

    with pytest.raises(InvalidGenerationRequest):
        await EditorialService(Session()).approve_revision(
            invalid.id,
            ApprovalRequest(expected_content_hash=invalid.content_hash, note=None),
        )
    assert invalid.approval_state == "pending_review"


def test_publish_transition_helper_fails_closed_without_validation_results():
    invalid = revision(validation_results=[])
    invalid.approval_state = "approved"
    with pytest.raises(HTTPException, match="validation results are empty"):
        require_revision_transition(invalid, content_hash=invalid.content_hash)
