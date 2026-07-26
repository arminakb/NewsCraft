from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from app.automations.telegram.contracts import TelegramEnvelope


@dataclass(frozen=True, slots=True)
class ActivationPageDecision:
    newer: tuple[TelegramEnvelope, ...]
    predecessor_id: int | None
    boundary_proven: bool


def classify_activation_page(
    envelopes: Sequence[TelegramEnvelope],
    *,
    boundary: datetime,
    complete: bool,
) -> ActivationPageDecision:
    ordered = sorted(
        envelopes,
        key=lambda item: (item.published_at, item.anchor_message_id),
        reverse=True,
    )
    newer = tuple(item for item in ordered if (item.published_at, item.anchor_message_id) > (boundary, 0))
    predecessors = [
        item.anchor_message_id
        for item in ordered
        if (item.published_at, item.anchor_message_id) <= (boundary, 0)
    ]
    if predecessors:
        return ActivationPageDecision(newer, max(predecessors), True)
    if complete:
        return ActivationPageDecision(newer, 0, True)
    return ActivationPageDecision(newer, None, False)


@dataclass(frozen=True, slots=True)
class BackfillEligibility:
    allowed: bool
    reason: str | None = None


def evaluate_backfill_eligibility(
    *,
    enabled: bool,
    route_status: str | None,
    cursor: int | None,
    since: datetime | None,
    now: datetime,
) -> BackfillEligibility:
    if not enabled or route_status != "ready" or cursor is None:
        return BackfillEligibility(False, "route_not_initialized")
    if since is not None and (since > now or since < now - timedelta(days=30)):
        return BackfillEligibility(False, "backfill_since_out_of_range")
    return BackfillEligibility(True)


def advance_poll_cursor(current: int | None, message_ids: Iterable[int]) -> int | None:
    observed = tuple(message_ids)
    if not observed:
        return current
    highest = max(observed)
    return max(current, highest) if current is not None else highest


@dataclass(frozen=True, slots=True)
class MediaPolicyDecision:
    media_asset_ids: tuple[UUID, ...]
    ready: bool
    reason: str | None = None
    terminal_reason: str | None = None


def evaluate_media_policy(policy: str, media: Sequence[Any]) -> MediaPolicyDecision:
    if policy == "omit":
        return MediaPolicyDecision((), True)
    if policy == "replace_manually":
        return MediaPolicyDecision((), False, "media_replacement_required")
    if any(item.fetch_status == "expired" for item in media):
        return MediaPolicyDecision((), False, terminal_reason="media_expired")
    ready = all(
        item.fetch_status == "downloaded" and bool(item.storage_path) and bool(item.checksum_sha256)
        for item in media
    )
    return MediaPolicyDecision(
        tuple(item.id for item in media),
        ready,
        None if ready else "media_not_ready",
    )


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    approved: bool
    note: str | None


def evaluate_review_policy(
    *,
    publishing_policy: str,
    explicit_force_review: bool,
    dispatch_kind: str,
    media_policy: str,
    auto_publish_allowed: bool,
    auto_publish_reason: str | None,
) -> ReviewDecision:
    force_review = (
        explicit_force_review
        or dispatch_kind in {"source_edit", "dry_run"}
        or media_policy == "replace_manually"
    )
    approved = publishing_policy == "auto_publish" and auto_publish_allowed and not force_review
    if approved:
        return ReviewDecision(True, None)
    return ReviewDecision(
        False,
        "forced_review" if force_review else auto_publish_reason or "review_required",
    )


PublicationFailureKind = Literal["retry", "reconcile", "terminal"]


@dataclass(frozen=True, slots=True)
class PublicationFailureDecision:
    kind: PublicationFailureKind
    retry_delay_seconds: int | None = None


def classify_publication_failure(error: BaseException) -> PublicationFailureDecision:
    from app.jobs.errors import PermanentJobError
    from app.publishing.telegram.client import (
        TelegramAmbiguousError,
        TelegramPermanentError,
        TelegramRateLimited,
        TelegramRetryableBeforeDispatch,
    )

    if isinstance(error, TelegramRateLimited):
        return PublicationFailureDecision("retry", error.retry_after)
    if isinstance(error, TelegramRetryableBeforeDispatch):
        return PublicationFailureDecision("retry", 30)
    if isinstance(error, (TelegramPermanentError, PermanentJobError)):
        return PublicationFailureDecision("terminal")
    if isinstance(error, TelegramAmbiguousError) or isinstance(error, Exception):
        return PublicationFailureDecision("reconcile")
    raise error


def reconciliation_required(*, receipt_status: str, dispatch_stale: bool = False) -> bool:
    return receipt_status == "ambiguous" or (receipt_status == "dispatching" and dispatch_stale)
