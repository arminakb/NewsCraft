from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.automations.telegram.contracts import TelegramEnvelope
from app.automations.telegram.decisions import (
    ActivationPageDecision,
    BackfillEligibility,
    MediaPolicyDecision,
    PublicationFailureDecision,
    ReviewDecision,
    advance_poll_cursor,
    classify_activation_page,
    classify_publication_failure,
    evaluate_backfill_eligibility,
    evaluate_media_policy,
    evaluate_review_policy,
    reconciliation_required,
)
from app.jobs.errors import PermanentJobError
from app.publishing.telegram.client import (
    TelegramAmbiguousError,
    TelegramPermanentError,
    TelegramRateLimited,
    TelegramRetryableBeforeDispatch,
)

NOW = datetime(2026, 7, 11, 9, tzinfo=UTC)


def envelope(message_id: int, offset_seconds: int) -> TelegramEnvelope:
    return TelegramEnvelope(
        source_key=f"telegram:source:{message_id}",
        peer_id="source",
        channel_ref="@source",
        anchor_message_id=message_id,
        message_ids=(message_id,),
        grouped_id=None,
        text=f"message {message_id}",
        html=None,
        entities=(),
        published_at=NOW + timedelta(seconds=offset_seconds),
        edited_at=None,
        source_url=f"https://t.me/source/{message_id}",
    )


@pytest.mark.parametrize(
    ("items", "complete", "expected"),
    [
        (
            [envelope(92, 2), envelope(90, -1), envelope(91, 1)],
            False,
            ActivationPageDecision((envelope(92, 2), envelope(91, 1)), 90, True),
        ),
        ([envelope(91, 1)], True, ActivationPageDecision((envelope(91, 1),), 0, True)),
        ([envelope(91, 1)], False, ActivationPageDecision((envelope(91, 1),), None, False)),
        ([envelope(1, 0)], False, ActivationPageDecision((envelope(1, 0),), None, False)),
    ],
)
def test_activation_boundary_is_second_normalized_and_fail_closed(items, complete, expected):
    assert classify_activation_page(items, boundary=NOW, complete=complete) == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, BackfillEligibility(True)),
        ({"enabled": False}, BackfillEligibility(False, "route_not_initialized")),
        ({"route_status": "initializing"}, BackfillEligibility(False, "route_not_initialized")),
        ({"cursor": None}, BackfillEligibility(False, "route_not_initialized")),
        (
            {"since": NOW - timedelta(days=31)},
            BackfillEligibility(False, "backfill_since_out_of_range"),
        ),
        (
            {"since": NOW + timedelta(seconds=1)},
            BackfillEligibility(False, "backfill_since_out_of_range"),
        ),
    ],
)
def test_backfill_is_only_eligible_for_a_ready_route_and_a_bounded_window(overrides, expected):
    values = {
        "enabled": True,
        "route_status": "ready",
        "cursor": 42,
        "since": NOW - timedelta(days=1),
        "now": NOW,
        **overrides,
    }
    assert evaluate_backfill_eligibility(**values) == expected


@pytest.mark.parametrize(
    ("current", "observed", "expected"),
    [(None, (), None), (None, (4, 5), 5), (10, (8, 9), 10), (10, (11, 13, 12), 13)],
)
def test_poll_cursor_only_advances(current, observed, expected):
    assert advance_poll_cursor(current, observed) == expected


@pytest.mark.parametrize(
    ("policy", "media", "expected"),
    [
        ("omit", [], MediaPolicyDecision((), True)),
        ("replace_manually", [], MediaPolicyDecision((), False, "media_replacement_required")),
        (
            "preserve",
            [SimpleNamespace(id=uuid4(), fetch_status="expired", storage_path=None, checksum_sha256=None)],
            MediaPolicyDecision((), False, terminal_reason="media_expired"),
        ),
    ],
)
def test_media_policy_is_explicit(policy, media, expected):
    assert evaluate_media_policy(policy, media) == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, ReviewDecision(True, None)),
        ({"publishing_policy": "review_required"}, ReviewDecision(False, "review_required")),
        ({"explicit_force_review": True}, ReviewDecision(False, "forced_review")),
        ({"dispatch_kind": "source_edit"}, ReviewDecision(False, "forced_review")),
        ({"dispatch_kind": "dry_run"}, ReviewDecision(False, "forced_review")),
        ({"media_policy": "replace_manually"}, ReviewDecision(False, "forced_review")),
        (
            {"auto_publish_allowed": False, "auto_publish_reason": "destination_unhealthy"},
            ReviewDecision(False, "destination_unhealthy"),
        ),
    ],
)
def test_review_policy_never_auto_publishes_an_exception(overrides, expected):
    values = {
        "publishing_policy": "auto_publish",
        "explicit_force_review": False,
        "dispatch_kind": "live",
        "media_policy": "omit",
        "auto_publish_allowed": True,
        "auto_publish_reason": None,
        **overrides,
    }
    assert evaluate_review_policy(**values) == expected


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TelegramRateLimited(retry_after=42), PublicationFailureDecision("retry", 42)),
        (TelegramRetryableBeforeDispatch("connect"), PublicationFailureDecision("retry", 30)),
        (TelegramAmbiguousError("timeout"), PublicationFailureDecision("reconcile")),
        (RuntimeError("unknown send outcome"), PublicationFailureDecision("reconcile")),
        (TelegramPermanentError("rejected"), PublicationFailureDecision("terminal")),
        (PermanentJobError(code="invalid", message="invalid"), PublicationFailureDecision("terminal")),
    ],
)
def test_publication_failure_classification_is_fail_closed(error, expected):
    assert classify_publication_failure(error) == expected


@pytest.mark.parametrize(
    ("status", "stale", "expected"),
    [
        ("ambiguous", False, True),
        ("dispatching", True, True),
        ("dispatching", False, False),
        ("pending", True, False),
        ("failed", False, False),
    ],
)
def test_reconciliation_is_required_only_for_ambiguous_or_stale_dispatch(status, stale, expected):
    assert reconciliation_required(receipt_status=status, dispatch_stale=stale) is expected
