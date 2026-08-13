from __future__ import annotations

import pytest

from app.retention.contracts import (
    RETENTION_CATEGORIES,
    RetentionConflict,
    RetentionCountSnapshot,
)

_SUMMARY = {"count": 2, "byte_length": 10, "oldest_at": None, "newest_at": None}


def _zero() -> dict[str, int]:
    return {category: 0 for category in RETENTION_CATEGORIES}


def test_preview_snapshot_round_trips_with_zeroed_execution() -> None:
    persisted = {"raw_payload": _SUMMARY}
    snapshot = RetentionCountSnapshot.from_snapshot(persisted)

    assert snapshot.categories["raw_payload"].count == 2
    assert snapshot.execution.scrubbed == _zero()
    assert snapshot.to_snapshot() == {"raw_payload": _SUMMARY, "execution": {
        "scrubbed": _zero(),
        "expired": _zero(),
        "skipped": _zero(),
        "database_skipped": _zero(),
        "filesystem_skipped": _zero(),
        "filesystem_deleted": _zero(),
    }}


def test_execution_snapshot_round_trips_unchanged() -> None:
    execution = {
        "scrubbed": {**_zero(), "raw_payload": 3},
        "expired": {**_zero(), "export_artifact": 1},
        "skipped": {**_zero(), "completed_job": 2},
        "database_skipped": {**_zero(), "completed_job": 2},
        "filesystem_skipped": _zero(),
        "filesystem_deleted": {**_zero(), "unreferenced_media": 4},
    }
    persisted = {"raw_payload": _SUMMARY, "execution": execution}

    assert RetentionCountSnapshot.from_snapshot(persisted).to_snapshot() == persisted


def test_legacy_rows_without_database_skipped_reuse_the_skipped_tally() -> None:
    """Rows written before the two skip tallies split still load."""
    persisted = {"execution": {"skipped": {**_zero(), "attempt_metadata": 5}}}

    snapshot = RetentionCountSnapshot.from_snapshot(persisted)

    assert snapshot.execution.database_skipped["attempt_metadata"] == 5
    assert snapshot.execution.skipped["attempt_metadata"] == 5


def test_partial_phase_tallies_are_completed_with_zeros() -> None:
    snapshot = RetentionCountSnapshot.from_snapshot({"execution": {"scrubbed": {"raw_payload": 1}}})

    assert snapshot.execution.scrubbed == {**_zero(), "raw_payload": 1}
    assert snapshot.execution.filesystem_deleted == _zero()


@pytest.mark.parametrize(
    "persisted",
    [
        {"execution": "not-an-object"},
        {"execution": {"scrubbed": "not-an-object"}},
        {"execution": {"scrubbed": {"raw_payload": "many"}}},
        {"execution": {"unknown_phase": {}}},
        {"not_a_category": {"count": 1}},
    ],
)
def test_an_unusable_snapshot_stops_the_run(persisted: dict[str, object]) -> None:
    """Deletion bookkeeping must fail loudly, never degrade into a skipped write."""
    with pytest.raises(RetentionConflict):
        RetentionCountSnapshot.from_snapshot(persisted)


def test_increment_and_reset_operate_on_the_live_tallies() -> None:
    snapshot = RetentionCountSnapshot.from_snapshot({})

    snapshot.execution.increment("scrubbed", "raw_payload")
    snapshot.execution.increment("scrubbed", "raw_payload")
    snapshot.execution.increment("filesystem_deleted", "unreferenced_media")
    snapshot.execution.reset("filesystem_deleted")

    assert snapshot.execution.scrubbed["raw_payload"] == 2
    assert snapshot.execution.filesystem_deleted == _zero()
