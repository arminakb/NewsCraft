from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.retention.models import RETENTION_SCHEMA_REVISION, RetentionRun
from app.retention.service import (
    RetentionCandidate,
    RetentionPolicyInput,
    RetentionService,
    build_preview_token,
    summarize_candidates,
)

NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)


def _candidate(
    category: str,
    value: int,
    *,
    record_type: str | None = None,
    state_hash: str | None = None,
    byte_length: int | None = 10,
) -> RetentionCandidate:
    default_record_types = {
        "raw_payload": "raw_payload",
        "completed_job": "workflow_job",
        "attempt_metadata": "generation_attempt",
        "export_artifact": "workflow_job",
        "unreferenced_media": "media_asset",
    }
    return RetentionCandidate(
        category=category,
        record_type=record_type or default_record_types[category],
        record_id=UUID(int=value),
        operation="expire" if category in {"export_artifact", "unreferenced_media"} else "scrub",
        occurred_at=NOW - timedelta(days=value),
        byte_length=byte_length,
        state_hash=state_hash or f"{value:064x}",
    )


def test_retention_policy_input_enforces_locked_bounds_and_defaults():
    assert RetentionPolicyInput().model_dump() == {
        "raw_payload_days": 30,
        "completed_job_days": 90,
        "attempt_metadata_days": 90,
        "export_artifact_days": 14,
        "unreferenced_media_days": 30,
    }

    invalid_values = (
        {"raw_payload_days": 6},
        {"completed_job_days": 13},
        {"attempt_metadata_days": 3651},
        {"export_artifact_days": 0},
        {"unreferenced_media_days": 6},
    )
    for value in invalid_values:
        with pytest.raises(ValidationError):
            RetentionPolicyInput.model_validate(value)


def test_preview_token_is_canonical_and_bound_to_every_category_state():
    policy = RetentionPolicyInput()
    candidates = [
        _candidate("raw_payload", 1),
        _candidate("completed_job", 2),
        _candidate("attempt_metadata", 3),
        _candidate("export_artifact", 4),
        _candidate("unreferenced_media", 5),
    ]

    token = build_preview_token(
        policy,
        list(reversed(candidates)),
        schema_revision=RETENTION_SCHEMA_REVISION,
    )

    assert token == build_preview_token(
        policy,
        candidates,
        schema_revision=RETENTION_SCHEMA_REVISION,
    )
    assert len(token) == 64
    assert token != build_preview_token(
        policy.model_copy(update={"raw_payload_days": 31}),
        candidates,
        schema_revision=RETENTION_SCHEMA_REVISION,
    )
    assert token != build_preview_token(
        policy,
        [*candidates[:-1], candidates[-1].model_copy(update={"state_hash": "f" * 64})],
        schema_revision=RETENTION_SCHEMA_REVISION,
    )
    assert token != build_preview_token(
        policy,
        [
            *candidates[:2],
            candidates[2].model_copy(update={"record_type": "research_attempt"}),
            *candidates[3:],
        ],
        schema_revision=RETENTION_SCHEMA_REVISION,
    )
    assert token != build_preview_token(
        policy,
        candidates,
        schema_revision="future-retention-schema",
    )


def test_candidate_summaries_cover_all_policy_categories_and_unknown_bytes_truthfully():
    candidates = [
        _candidate("raw_payload", 1, byte_length=10),
        _candidate("raw_payload", 2, byte_length=15),
        _candidate("completed_job", 3, byte_length=20),
        _candidate("attempt_metadata", 4, byte_length=30),
        _candidate("export_artifact", 5, byte_length=None),
        _candidate("unreferenced_media", 6, byte_length=40),
    ]

    summaries = summarize_candidates(candidates)

    assert set(summaries) == {
        "raw_payload",
        "completed_job",
        "attempt_metadata",
        "export_artifact",
        "unreferenced_media",
    }
    assert summaries["raw_payload"].model_dump() == {
        "count": 2,
        "byte_length": 25,
        "oldest_at": NOW - timedelta(days=2),
        "newest_at": NOW - timedelta(days=1),
    }
    assert summaries["export_artifact"].count == 1
    assert summaries["export_artifact"].byte_length is None
    assert summaries["unreferenced_media"].byte_length == 40


def test_candidate_record_type_is_strictly_bound_to_its_category():
    with pytest.raises(ValidationError):
        _candidate("raw_payload", 1, record_type="generation_attempt")

    for record_type in ("research_attempt", "generation_attempt", "publish_attempt"):
        assert _candidate("attempt_metadata", 2, record_type=record_type).record_type == record_type


@pytest.mark.asyncio
async def test_all_skipped_reset_requires_current_candidates_and_zero_prior_mutations(monkeypatch):
    candidate = _candidate("export_artifact", 7)
    zero_counts = {
        category: 0
        for category in (
            "raw_payload",
            "completed_job",
            "attempt_metadata",
            "export_artifact",
            "unreferenced_media",
        )
    }
    run = RetentionRun(
        status="succeeded",
        preview_token="a" * 64,
        schema_revision=RETENTION_SCHEMA_REVISION,
        policy_snapshot=RetentionPolicyInput().model_dump(mode="json"),
        candidate_snapshot=[candidate.model_dump(mode="json")],
        cleanup_intent_snapshot=[],
        count_snapshot={
            "execution": {
                "scrubbed": dict(zero_counts),
                "expired": dict(zero_counts),
                "database_skipped": {**zero_counts, "export_artifact": 1},
                "filesystem_deleted": dict(zero_counts),
            }
        },
        error_snapshot=[],
        previewed_at=NOW,
        preview_expires_at=NOW + timedelta(minutes=30),
    )
    service = RetentionService(object(), clock=lambda: NOW, media_root=Path("/tmp/media"))

    async def current_candidates(*args, **kwargs):
        return [candidate]

    monkeypatch.setattr(service, "_collect_candidates", current_candidates)

    assert await service._reset_all_skipped_database_run(run) is True

    run.count_snapshot["execution"]["expired"]["export_artifact"] = 1
    assert await service._reset_all_skipped_database_run(run) is False

    run.count_snapshot["execution"]["expired"]["export_artifact"] = 0
    run.cleanup_intent_snapshot = [{"operation": "delete_tree"}]
    assert await service._reset_all_skipped_database_run(run) is False
