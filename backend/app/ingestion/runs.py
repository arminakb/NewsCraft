"""The shape every ingest run starts in.

Standalone runs and source-collection snapshots differ in status and
collection linkage; everything else — the counter columns and the seven-key
stats document the workflow accumulates into — is the same, so it is defined
once here instead of being retyped at each construction site.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.db.models import IngestRun


def initial_ingest_stats() -> dict[str, Any]:
    """The zeroed stats document an ingest run accumulates into."""

    return {
        "checked": 0,
        "fetched": 0,
        "skipped": 0,
        "failed": 0,
        "items": 0,
        "media_candidates": 0,
        "errors": [],
    }


def new_ingest_run(
    *,
    trigger: str,
    parser_version: str,
    status: str,
    run_id: UUID | None = None,
    started_at: datetime | None = None,
    source_collection_id: UUID | None = None,
    source_collection_name_at_start: str | None = None,
    source_count: int = 0,
) -> IngestRun:
    values: dict[str, Any] = {
        "trigger": trigger,
        "parser_version": parser_version,
        "status": status,
        "stats": initial_ingest_stats(),
        "source_collection_id": source_collection_id,
        "source_collection_name_at_start": source_collection_name_at_start,
        "source_count": source_count,
        "processed_count": 0,
        "success_count": 0,
        "failure_count": 0,
    }
    if run_id is not None:
        values["id"] = run_id
    if started_at is not None:
        values["started_at"] = started_at
    return IngestRun(**values)
