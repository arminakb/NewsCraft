from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.automations.models import AutomationRoute, TelegramSourceConfig
from app.automations.telegram.contracts import (
    TelegramEnvelope,
    TelegramFetchResult,
    telegram_envelope_fingerprint,
)
from app.automations.telegram.handlers import build_telegram_route_handlers
from app.automations.telegram.registry import TelegramSourceRegistry
from app.db.models import Source
from app.generation.providers.registry import build_default_provider_registry
from app.jobs.errors import PermanentJobError, RetryableJobError
from app.jobs.models import AutomationControl, WorkflowJob
from app.jobs.registry import JobContext, build_default_registry

ROUTE_ID = UUID("00000000-0000-0000-0000-000000000501")
NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)


async def test_initialize_captures_boundary_posts_and_arrivals_before_marking_ready():
    fixture = HandlerFixture(
        responses=[
            fetch_result([envelope(92, second=2), envelope(91, second=1), envelope(90, second=-1)]),
            fetch_result([envelope(93, second=3)]),
            fetch_result([]),
        ]
    )
    fixture.route.cursor_state = {
        "status": "initializing",
        "activation_requested_at": "2026-07-11T09:00:00.817231+00:00",
    }

    result = await fixture.handlers.initialize(fixture.job(), fixture.context())

    assert [call.envelope.anchor_message_id for call in fixture.capture.calls] == [91, 92, 93]
    assert fixture.route.cursor_state["activation_boundary_at"] == "2026-07-11T09:00:00+00:00"
    assert fixture.route.cursor_state["activation_message_id"] == 90
    assert fixture.route.cursor_state["last_message_id"] == 93
    assert fixture.route.cursor_state["status"] == "ready"
    assert fixture.route.next_poll_at == NOW
    assert result == {
        "route_id": str(ROUTE_ID),
        "cursor": 93,
        "captured": 3,
        "initialized": True,
    }


async def test_initialize_includes_positive_message_id_in_normalized_boundary_second():
    fixture = HandlerFixture(
        responses=[
            fetch_result([envelope(91, second=0), envelope(90, second=-1)]),
            fetch_result([]),
        ]
    )

    result = await fixture.handlers.initialize(fixture.job(), fixture.context())

    assert [call.envelope.anchor_message_id for call in fixture.capture.calls] == [91]
    assert fixture.route.cursor_state["activation_message_id"] == 90
    assert result["cursor"] == 91


async def test_initialize_without_boundary_proof_remains_catching_up_and_enqueues_continuation():
    fixture = HandlerFixture(
        responses=[fetch_result([envelope(92), envelope(91)], complete=False, page_token="next")],
        page_budget=1,
    )

    result = await fixture.handlers.initialize(fixture.job(), fixture.context())

    assert result["continuation_enqueued"] is True
    assert fixture.route.cursor_state["status"] == "catching_up"
    assert fixture.route.cursor_state.get("last_message_id") is None
    assert_cursor_state_contains_tokens_only(fixture.route.cursor_state)
    assert fixture.media.jobs[0]["job_type"] == "telegram.route.initialize"
    assert fixture.media.jobs[0]["idempotency_key"].startswith(f"telegram-route-initialize-catch-up:{ROUTE_ID}:")


async def test_initialize_resumes_bounded_activation_scan_without_skipping_or_duplicates():
    fixture = HandlerFixture(
        responses=[
            fetch_result(
                [envelope(92, second=2), envelope(91, second=1)],
                complete=False,
                page_token="older",
            ),
            fetch_result([envelope(90, second=-1)]),
            fetch_result([envelope(93, second=3), envelope(92, second=2), envelope(91, second=1)]),
            fetch_result([]),
        ],
        page_budget=1,
    )

    first = await fixture.handlers.initialize(fixture.job(), fixture.context())
    second = await fixture.handlers.initialize(fixture.job(), fixture.context())
    third = await fixture.handlers.initialize(fixture.job(), fixture.context())

    assert first["continuation_enqueued"] is True
    assert second["continuation_enqueued"] is True
    assert third["initialized"] is True
    assert fixture.adapter.requests[1].page_token == "older"
    assert [call.envelope.anchor_message_id for call in fixture.capture.calls] == [91, 92, 93]
    keys = [job["idempotency_key"] for job in fixture.media.jobs]
    assert keys[0].startswith(f"telegram-route-initialize-catch-up:{ROUTE_ID}:91:activation_scan:")
    assert keys[1].startswith(f"telegram-route-initialize-catch-up:{ROUTE_ID}:93:catch_up_cycle:")


async def test_initialize_forward_snapshot_continues_past_page_budget_with_tokens_only():
    fixture = HandlerFixture(
        responses=[
            fetch_result([envelope(90, second=-1)]),
            fetch_result([envelope(94, second=4)], complete=False, page_token="older"),
            fetch_result([envelope(93, second=3), envelope(92, second=2)]),
            fetch_result([envelope(94, second=4)]),
            fetch_result([]),
        ],
        page_budget=1,
    )

    first = await fixture.handlers.initialize(fixture.job(job_type="telegram.route.initialize"), fixture.context())
    second = await fixture.handlers.initialize(fixture.job(job_type="telegram.route.initialize"), fixture.context())
    third = await fixture.handlers.initialize(fixture.job(job_type="telegram.route.initialize"), fixture.context())
    fourth = await fixture.handlers.initialize(fixture.job(job_type="telegram.route.initialize"), fixture.context())

    assert first["continuation_enqueued"] is True
    assert second["continuation_enqueued"] is True
    assert third["continuation_enqueued"] is True
    assert fourth["initialized"] is True
    assert [call.envelope.anchor_message_id for call in fixture.capture.calls] == [92, 93, 94]
    assert_cursor_state_contains_tokens_only(fixture.route.cursor_state)


async def test_initialize_forward_scan_and_capture_continuation_keys_never_collide():
    fixture = HandlerFixture(
        responses=[
            fetch_result([envelope(90, second=-1)]),
            fetch_result([envelope(100, second=10)], complete=False, page_token="p2"),
            fetch_result([envelope(99, second=9)], complete=False, page_token="p3"),
            fetch_result([envelope(98, second=8)], complete=False, page_token="p4"),
            fetch_result([envelope(97, second=7)]),
            fetch_result([envelope(98, second=8)]),
            fetch_result([envelope(99, second=9)]),
            fetch_result([envelope(100, second=10)]),
            fetch_result([]),
        ],
        page_budget=1,
    )

    for _ in range(8):
        await fixture.handlers.initialize(fixture.job(job_type="telegram.route.initialize"), fixture.context())

    keys = [item["idempotency_key"] for item in fixture.media.jobs]
    assert len(keys) == len(set(keys)) == 7
    assert sum(":scan:" in key for key in keys) >= 3
    assert sum(":capture:" in key for key in keys) >= 3
    assert [call.envelope.anchor_message_id for call in fixture.capture.calls] == [97, 98, 99, 100]


async def test_stale_activation_cannot_overwrite_continuation_state_after_network_fetch():
    fixture = HandlerFixture(
        responses=[fetch_result([envelope(92)], complete=False, page_token="older")],
        page_budget=1,
    )
    fixture.adapter.on_fetch = lambda: fixture.route.cursor_state.update(
        {"activation_requested_at": "2026-07-11T09:01:00+00:00"}
    )

    with pytest.raises(PermanentJobError, match="activation changed"):
        await fixture.handlers.initialize(fixture.job(), fixture.context())

    assert fixture.route.cursor_state.get("activation_page_token") is None
    assert fixture.media.jobs == []


async def test_empty_incomplete_activation_page_retries_without_self_deduplicating_continuation():
    fixture = HandlerFixture(
        responses=[fetch_result([], complete=False, page_token="older")],
        page_budget=1,
    )

    with pytest.raises(RetryableJobError, match="made no progress"):
        await fixture.handlers.initialize(fixture.job(), fixture.context())

    assert fixture.media.jobs == []
    assert fixture.route.cursor_state.get("activation_page_token") is None


async def test_paused_initialization_defers_durably_and_resumes_without_network_while_paused():
    fixture = HandlerFixture(responses=[fetch_result([envelope(90, second=-1)]), fetch_result([])])
    fixture.route.paused_at = NOW

    held = await fixture.handlers.initialize(fixture.job(job_type="telegram.route.initialize"), fixture.context())

    assert held["reason"] == "route_pause"
    assert held["deferred_until"] == (NOW + timedelta(seconds=300)).isoformat()
    assert fixture.adapter.requests == []
    assert fixture.media.jobs[0]["job_type"] == "telegram.route.initialize"
    assert fixture.media.jobs[0]["scheduled_for"] == NOW + timedelta(seconds=300)

    fixture.route.paused_at = None
    resumed = await fixture.handlers.initialize(fixture.job(job_type="telegram.route.initialize"), fixture.context())
    assert resumed["initialized"] is True


async def test_poll_captures_source_edits_before_new_live_messages_in_ascending_order():
    changed = envelope(110, text="corrected")
    unchanged = envelope(120, text="unchanged")
    live_121 = envelope(121)
    live_122 = envelope(122)
    fixture = HandlerFixture(
        responses=[
            fetch_result([live_122, live_121]),
            fetch_result([changed, unchanged]),
        ]
    )
    fixture.route.cursor_state = {
        "status": "ready",
        "last_message_id": 120,
        "recent_fingerprints": {
            "110": "old-hash",
            "120": telegram_envelope_fingerprint(unchanged),
        },
    }
    fixture.route.publishing_policy = "auto_publish"

    result = await fixture.handlers.poll(fixture.job(), fixture.context())

    assert [(call.envelope.anchor_message_id, call.dispatch_kind) for call in fixture.capture.calls] == [
        (110, "source_edit"),
        (121, "live"),
        (122, "live"),
    ]
    assert fixture.capture.calls[0].force_review is True
    assert fixture.route.cursor_state["last_message_id"] == 122
    assert result == {"captured": 2, "source_edits": 1, "filtered": 0}


async def test_poll_collects_all_stable_forward_pages_before_advancing_cursor():
    fixture = HandlerFixture(
        responses=[
            fetch_result([envelope(124), envelope(123)], complete=False, page_token="older"),
            fetch_result([envelope(122), envelope(121)]),
            fetch_result([]),
        ]
    )
    fixture.route.cursor_state = {"status": "ready", "last_message_id": 120}

    result = await fixture.handlers.poll(fixture.job(), fixture.context())

    assert [call.envelope.anchor_message_id for call in fixture.capture.calls] == [121, 122, 123, 124]
    assert fixture.adapter.requests[0].after_id == 120
    assert fixture.adapter.requests[1].after_id == 120
    assert fixture.adapter.requests[1].page_token == "older"
    assert fixture.route.cursor_state["last_message_id"] == 124
    assert result["captured"] == 4


async def test_incomplete_forward_page_without_continuation_does_not_advance_poll_state():
    fixture = HandlerFixture(responses=[fetch_result([envelope(121)], complete=False)])
    fixture.route.cursor_state = {"status": "ready", "last_message_id": 120}

    with pytest.raises(RetryableJobError, match="progressing forward page"):
        await fixture.handlers.poll(fixture.job(), fixture.context())

    assert fixture.capture.calls == []
    assert fixture.route.cursor_state["last_message_id"] == 120
    assert fixture.route.last_polled_at is None


async def test_forward_page_budget_continuations_eventually_capture_ascending_without_loss():
    fixture = HandlerFixture(
        responses=[
            fetch_result([envelope(124, second=4)], complete=False, page_token="p2"),
            fetch_result([envelope(123, second=3)], complete=False, page_token="p3"),
            fetch_result([envelope(122, second=2), envelope(121, second=1)]),
            fetch_result([]),
            fetch_result([envelope(123, second=3)]),
            fetch_result([]),
            fetch_result([envelope(124, second=4)]),
            fetch_result([]),
        ],
        page_budget=1,
    )
    fixture.route.cursor_state = {"status": "ready", "last_message_id": 120}

    results = []
    for _ in range(5):
        results.append(await fixture.handlers.poll(fixture.job(), fixture.context()))
        assert_cursor_state_contains_tokens_only(fixture.route.cursor_state)

    assert all(result.get("continuation_enqueued") for result in results[:4])
    assert [call.envelope.anchor_message_id for call in fixture.capture.calls] == [121, 122, 123, 124]
    assert fixture.route.cursor_state["last_message_id"] == 124
    assert "poll_forward" not in fixture.route.cursor_state
    assert [request.page_token for request in fixture.adapter.requests[0:3]] == [
        None,
        "p2",
        "p3",
    ]
    assert fixture.adapter.requests[4].page_token == "p2"
    assert fixture.adapter.requests[6].page_token is None


@pytest.mark.parametrize("job_kind", ["poll", "backfill", "dry_run"])
async def test_paused_route_jobs_defer_unique_continuation_and_resume(job_kind):
    responses = {
        "poll": [fetch_result([]), fetch_result([])],
        "backfill": [fetch_result([envelope(90)])],
        "dry_run": [fetch_result([envelope(120)])],
    }[job_kind]
    fixture = HandlerFixture(responses=responses)
    fixture.route.cursor_state = {"status": "ready", "last_message_id": 120}
    fixture.route.paused_at = NOW
    payload = {"route_id": str(ROUTE_ID)}
    if job_kind == "backfill":
        payload["count"] = 1
    if job_kind == "dry_run":
        payload["source_message_id"] = 120

    held = await getattr(fixture.handlers, job_kind)(
        fixture.job(payload=payload, job_type=f"telegram.route.{job_kind}"), fixture.context()
    )

    assert held["reason"] == "route_pause"
    assert held["deferred_until"] == (NOW + timedelta(seconds=300)).isoformat()
    assert fixture.adapter.requests == []
    deferred = fixture.media.jobs[-1]
    assert deferred["job_type"] == f"telegram.route.{job_kind}"
    assert str(fixture.job_id) in deferred["idempotency_key"]

    fixture.route.paused_at = None
    resumed = await getattr(fixture.handlers, job_kind)(
        fixture.job(payload=payload, job_type=f"telegram.route.{job_kind}"), fixture.context()
    )
    assert resumed.get("held") is not True


async def test_backfill_pages_stable_snapshot_until_count_then_captures_ascending():
    fixture = HandlerFixture(
        responses=[
            fetch_result([envelope(92, second=2)], complete=False, page_token="older"),
            fetch_result([envelope(91, second=1)]),
        ]
    )
    fixture.route.cursor_state = {"status": "ready", "last_message_id": 120}

    result = await fixture.handlers.backfill(
        fixture.job(payload={"route_id": str(ROUTE_ID), "count": 2}),
        fixture.context(),
    )

    assert [call.envelope.anchor_message_id for call in fixture.capture.calls] == [91, 92]
    assert fixture.adapter.requests[1].snapshot_token == "snapshot"
    assert fixture.adapter.requests[1].page_token == "older"
    assert result["captured"] == 2


async def test_since_backfill_pages_until_boundary_completion_and_stays_below_live_cursor():
    fixture = HandlerFixture(
        responses=[
            fetch_result([envelope(92, second=2)], complete=False, page_token="older"),
            fetch_result([envelope(91, second=1)]),
        ]
    )
    fixture.route.cursor_state = {"status": "ready", "last_message_id": 120}
    since = NOW - timedelta(days=1)

    result = await fixture.handlers.backfill(
        fixture.job(
            payload={"route_id": str(ROUTE_ID), "since": since.isoformat()},
            job_type="telegram.route.backfill",
        ),
        fixture.context(),
    )

    assert [call.envelope.anchor_message_id for call in fixture.capture.calls] == [91, 92]
    assert all(request.before_id == 120 for request in fixture.adapter.requests)
    assert fixture.adapter.requests[1].page_token == "older"
    assert result["captured"] == 2


async def test_edit_lookback_pages_until_newest_fifty_are_collected():
    recent_newer = [envelope(message_id) for message_id in range(101, 131)]
    changed = envelope(90, text="corrected")
    recent_older = [envelope(message_id) for message_id in range(81, 101)]
    recent_older[9] = changed
    fixture = HandlerFixture(
        responses=[
            fetch_result([]),
            fetch_result(recent_newer, complete=False, page_token="older"),
            fetch_result(recent_older),
        ]
    )
    fixture.route.cursor_state = {
        "status": "ready",
        "last_message_id": 130,
        "recent_fingerprints": {"90": "old-hash"},
    }

    result = await fixture.handlers.poll(fixture.job(), fixture.context())

    assert [(call.envelope.anchor_message_id, call.dispatch_kind) for call in fixture.capture.calls] == [
        (90, "source_edit")
    ]
    assert fixture.adapter.requests[2].page_token == "older"
    assert result["source_edits"] == 1


async def test_pause_during_forward_fetch_defers_before_locked_capture():
    fixture = HandlerFixture(responses=[fetch_result([envelope(121)]), fetch_result([])])
    fixture.route.cursor_state = {"status": "ready", "last_message_id": 120}
    fixture.adapter.on_fetch = lambda: setattr(fixture.route, "paused_at", NOW)

    result = await fixture.handlers.poll(fixture.job(), fixture.context())

    assert result["reason"] == "route_pause"
    assert fixture.capture.calls == []
    assert fixture.media.jobs[-1]["job_type"] == "telegram.route.poll"


async def test_reactivation_identity_change_during_fetch_prevents_locked_capture():
    fixture = HandlerFixture(responses=[fetch_result([envelope(121)]), fetch_result([])])
    fixture.route.cursor_state = {
        "status": "ready",
        "last_message_id": 120,
        "activation_requested_at": "2026-07-11T09:00:00+00:00",
    }
    fixture.adapter.on_fetch = lambda: fixture.route.cursor_state.update(
        {"activation_requested_at": "2026-07-11T09:01:00+00:00"}
    )

    with pytest.raises(PermanentJobError, match="activation changed"):
        await fixture.handlers.poll(fixture.job(), fixture.context())

    assert fixture.capture.calls == []


@pytest.mark.parametrize(
    "failure",
    ["token", "snapshot", "envelope"],
)
async def test_forward_pagination_rejects_token_snapshot_and_envelope_nonprogress(failure):
    responses = {
        "token": [
            fetch_result([envelope(122)], complete=False, page_token="repeat"),
            fetch_result([envelope(121)], complete=False, page_token="repeat"),
        ],
        "snapshot": [
            fetch_result([envelope(122)], complete=False, page_token="older", snapshot="one"),
            fetch_result([envelope(121)], snapshot="two"),
        ],
        "envelope": [
            fetch_result([envelope(122)], complete=False, page_token="older"),
            fetch_result([envelope(122)], complete=False, page_token="older-again"),
        ],
    }[failure]
    fixture = HandlerFixture(responses=responses, page_budget=2)
    fixture.route.cursor_state = {"status": "ready", "last_message_id": 120}

    with pytest.raises(RetryableJobError):
        await fixture.handlers.poll(fixture.job(), fixture.context())

    assert fixture.capture.calls == []
    assert fixture.media.jobs == []


async def test_backfill_and_lookback_reject_repeated_nonprogressing_page_tokens():
    backfill = HandlerFixture(
        responses=[
            fetch_result([envelope(92)], complete=False, page_token="repeat"),
            fetch_result([envelope(92)], complete=False, page_token="repeat"),
        ]
    )
    backfill.route.cursor_state = {"status": "ready", "last_message_id": 120}
    with pytest.raises(RetryableJobError):
        await backfill.handlers.backfill(
            backfill.job(
                payload={"route_id": str(ROUTE_ID), "count": 2},
                job_type="telegram.route.backfill",
            ),
            backfill.context(),
        )

    lookback = HandlerFixture(
        responses=[
            fetch_result([]),
            fetch_result([envelope(100)], complete=False, page_token="repeat"),
            fetch_result([envelope(100)], complete=False, page_token="repeat"),
        ]
    )
    lookback.route.cursor_state = {"status": "ready", "last_message_id": 120}
    with pytest.raises(RetryableJobError):
        await lookback.handlers.poll(lookback.job(), lookback.context())


async def test_activation_and_capture_replay_reject_token_or_snapshot_loops():
    activation = HandlerFixture(
        responses=[
            fetch_result([envelope(92)], complete=False, page_token="repeat"),
            fetch_result([envelope(91)], complete=False, page_token="repeat"),
        ],
        page_budget=2,
    )
    with pytest.raises(RetryableJobError):
        await activation.handlers.initialize(activation.job(job_type="telegram.route.initialize"), activation.context())

    capture = HandlerFixture(
        responses=[fetch_result([envelope(121)], snapshot="changed")],
        page_budget=1,
    )
    capture.route.cursor_state = {
        "status": "ready",
        "last_message_id": 120,
        "poll_forward": {
            "phase": "capture",
            "base_after_id": 120,
            "snapshot_token": "pinned",
            "page_tokens": [None],
            "last_scanned_id": 121,
            "last_captured_id": 120,
        },
    }
    with pytest.raises(RetryableJobError):
        await capture.handlers.poll(capture.job(), capture.context())


async def test_paused_job_replay_uses_one_stable_successor_key_and_schedule():
    fixture = HandlerFixture(responses=[])
    fixture.route.cursor_state = {"status": "ready", "last_message_id": 120}
    fixture.route.paused_at = NOW
    job = fixture.job(job_type="telegram.route.dry_run")
    job.payload = {"route_id": str(ROUTE_ID), "source_message_id": 120}

    first = await fixture.handlers.dry_run(job, fixture.context())
    fixture.now = NOW + timedelta(hours=1)
    second = await fixture.handlers.dry_run(job, fixture.context())

    assert first["deferred_until"] == (NOW + timedelta(seconds=300)).isoformat()
    assert second["deferred_until"] == (fixture.now + timedelta(seconds=300)).isoformat()
    assert len(fixture.media.jobs) == 1
    assert fixture.media.jobs[0]["scheduled_for"] == NOW + timedelta(seconds=300)
    assert fixture.media.jobs[0]["idempotency_key"].endswith(f"{job.id}:1")
    assert fixture.media.jobs[0]["payload"]["defer_root_job_id"] == str(job.id)


@pytest.mark.parametrize("failure", ["state", "repository"])
async def test_staged_media_is_cleaned_after_locked_state_or_repository_failure(failure):
    fixture = HandlerFixture(responses=[fetch_result([envelope(121)]), fetch_result([])])
    fixture.route.cursor_state = {
        "status": "ready",
        "last_message_id": 120,
        "activation_requested_at": "2026-07-11T09:00:00+00:00",
    }
    fixture.media.materialized = ("staged-media",)
    if failure == "state":
        fixture.adapter.on_fetch = lambda: fixture.route.cursor_state.update(
            {"activation_requested_at": "2026-07-11T09:01:00+00:00"}
        )
    else:
        fixture.capture.error = RuntimeError("capture failed")

    with pytest.raises((PermanentJobError, RuntimeError)):
        await fixture.handlers.poll(fixture.job(), fixture.context())

    assert fixture.media.cleaned == [("staged-media",)]


async def test_pause_performs_no_source_network_call():
    fixture = HandlerFixture(responses=[], global_pause=True)

    result = await fixture.handlers.poll(fixture.job(), fixture.context())

    assert result == {
        "held": True,
        "reason": "global_pause",
        "deferred_until": (NOW + timedelta(seconds=300)).isoformat(),
    }
    assert fixture.adapter.requests == []


async def test_backfill_and_dry_run_are_review_only_and_cursor_independent():
    fixture = HandlerFixture(
        responses=[
            fetch_result([envelope(92), envelope(91), envelope(90)]),
            fetch_result([envelope(120)]),
        ]
    )
    fixture.route.cursor_state = {"status": "ready", "last_message_id": 120}
    original = dict(fixture.route.cursor_state)

    backfill = await fixture.handlers.backfill(
        fixture.job(payload={"route_id": str(ROUTE_ID), "count": 2}), fixture.context()
    )
    dry_run = await fixture.handlers.dry_run(
        fixture.job(payload={"route_id": str(ROUTE_ID), "source_message_id": 120}),
        fixture.context(),
    )

    assert [call.dispatch_kind for call in fixture.capture.calls] == [
        "backfill",
        "backfill",
        "dry_run",
    ]
    assert all(call.force_review for call in fixture.capture.calls)
    assert fixture.route.cursor_state == original
    assert backfill["captured"] == 2
    assert dry_run["force_review"] is True


@pytest.mark.parametrize(
    "since",
    [NOW + timedelta(seconds=1), NOW - timedelta(days=30, seconds=1)],
)
async def test_backfill_rejects_out_of_range_since_before_network(since):
    fixture = HandlerFixture(responses=[])
    fixture.route.cursor_state = {"status": "ready", "last_message_id": 120}

    with pytest.raises(PermanentJobError, match="previous 30 days"):
        await fixture.handlers.backfill(
            fixture.job(payload={"route_id": str(ROUTE_ID), "since": since.isoformat()}),
            fixture.context(),
        )

    assert fixture.adapter.requests == []


async def test_invalid_payload_fails_permanently_before_network():
    fixture = HandlerFixture(responses=[])

    with pytest.raises(PermanentJobError, match="payload"):
        await fixture.handlers.poll(fixture.job(payload={"route_id": "invalid"}), fixture.context())

    assert fixture.adapter.requests == []


def test_default_registry_adds_only_source_handlers_when_dependencies_are_supplied():
    fixture = HandlerFixture(responses=[])

    registry = build_default_registry(
        source_registry=fixture.handlers_source_registry,
        media_stager=fixture.media,
    )

    assert registry.job_types() == (
        "ingest.collect",
        "ingest.collection.continuous_cycle",
        "manual_intake",
        "operations.canary.source_generation",
        "story.group_pending",
        "telegram.route.backfill",
        "telegram.route.dry_run",
        "telegram.route.initialize",
        "telegram.route.poll",
    )


def envelope(message_id: int, *, text: str | None = None, second: int = 10) -> TelegramEnvelope:
    return TelegramEnvelope(
        source_key=f"message:{message_id}",
        peer_id="-100500",
        channel_ref="channel",
        anchor_message_id=message_id,
        message_ids=(message_id,),
        grouped_id=None,
        text=text or f"Post {message_id}",
        html=None,
        entities=(),
        published_at=datetime(2026, 7, 11, 9, 0, tzinfo=UTC) + timedelta(seconds=second),
        edited_at=None,
        source_url=None,
        media=(),
    )


def fetch_result(envelopes, *, complete=True, page_token=None, snapshot="snapshot"):
    return TelegramFetchResult(
        peer_id="-100500",
        envelopes=tuple(envelopes),
        fetched_at=NOW,
        snapshot_token=snapshot,
        next_page_token=page_token,
        complete=complete,
    )


def assert_cursor_state_contains_tokens_only(value):
    forbidden = {
        "text",
        "html",
        "entities",
        "media",
        "source_url",
        "remote_ref",
        "activation_pending_envelopes",
    }

    def visit(item):
        if isinstance(item, dict):
            assert forbidden.isdisjoint(item)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)


class HandlerFixture:
    def __init__(self, *, responses, global_pause=False, page_budget=10):
        self.route = AutomationRoute(
            id=ROUTE_ID,
            name="Route",
            source_id=uuid4(),
            destination_id=uuid4(),
            brand_profile_id=uuid4(),
            prompt_template_version_id=uuid4(),
            ai_provider_profile_id=uuid4(),
            access_mode="public_html",
            research_mode="off",
            content_filters={},
            media_policy="preserve",
            attribution_policy="preserve",
            publishing_policy="review_required",
            poll_interval_seconds=300,
            quiet_hours={},
            retry_policy={"max_attempts": 3, "base_delay_seconds": 30, "max_delay_seconds": 90},
            cursor_state={
                "status": "initializing",
                "activation_requested_at": "2026-07-11T09:00:00.817231+00:00",
            },
            enabled=True,
            paused_at=None,
        )
        self.source = Source(
            id=self.route.source_id,
            platform="telegram_public",
            name="Source",
            source_group="telegram",
        )
        self.config = TelegramSourceConfig(
            source_id=self.source.id,
            access_mode="public_html",
            channel_ref="channel",
        )
        self.control = AutomationControl(id="global", global_pause=global_pause, dry_run=False)
        self.session = FakeSession(self.route, self.source, self.config, self.control)
        self.adapter = FakeAdapter(responses)
        registry = TelegramSourceRegistry()
        registry.register("public_html", self.adapter)
        self.handlers_source_registry = registry
        self.capture = FakeCapture(self.route)
        self.media = FakeMediaStager(self.capture)
        self.now = NOW
        # The fake plays both roles, but each role is now wired explicitly:
        # production code no longer sniffs the stager for ``enqueue_job``.
        self.handlers = build_telegram_route_handlers(
            registry,
            self.media,
            page_budget=page_budget,
            clock=lambda: self.now,
            job_repository=self.media,
        )
        self.job_id = uuid4()

    def job(self, *, payload=None, job_type="telegram.route.poll"):
        return WorkflowJob(
            id=self.job_id,
            job_type=job_type,
            payload=payload or {"route_id": str(ROUTE_ID)},
            idempotency_key=str(uuid4()),
            origin="automation",
        )

    def context(self):
        return JobContext(session=self.session, providers=build_default_provider_registry())


class FakeSession:
    def __init__(self, route, source, config, control):
        self.values = {
            (AutomationRoute, route.id): route,
            (Source, source.id): source,
            (TelegramSourceConfig, config.source_id): config,
            (AutomationControl, "global"): control,
        }

    async def get(self, model, identifier):
        return self.values.get((model, identifier))

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        return next((value for (model, _), value in self.values.items() if model is entity), None)

    @asynccontextmanager
    async def begin(self):
        yield

    async def flush(self):
        return None

    async def commit(self):
        return None


class FakeAdapter:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.on_fetch = None

    async def fetch(self, request):
        self.requests.append(request)
        if self.on_fetch is not None:
            self.on_fetch()
        return self.responses.pop(0)


class FakeCapture:
    def __init__(self, route):
        self.route = route
        self.calls = []
        self.error = None

    async def capture_and_enqueue(self, **kwargs):
        if self.error is not None:
            raise self.error
        call = SimpleNamespace(**kwargs)
        self.calls.append(call)
        fingerprint = telegram_envelope_fingerprint(call.envelope)
        if call.dispatch_kind in {"live", "source_edit"}:
            state = dict(self.route.cursor_state)
            recent = dict(state.get("recent_fingerprints", {}))
            recent[str(call.envelope.anchor_message_id)] = fingerprint
            state["recent_fingerprints"] = recent
            if call.dispatch_kind == "live":
                state["last_message_id"] = max(int(state.get("last_message_id") or 0), call.envelope.anchor_message_id)
            self.route.cursor_state = state
        return SimpleNamespace(id=uuid4(), status="captured")

    def cleanup_staged_media(self, materialized):
        return None


class FakeMediaStager:
    def __init__(self, capture):
        self.capture = capture
        self.jobs = []
        self.materialized = ()
        self.cleaned = []

    def capture_repository(self, session):
        return self.capture

    async def materialize(self, adapter, envelope):
        return self.materialized

    def cleanup(self, materialized):
        self.cleaned.append(materialized)

    async def enqueue_job(self, **kwargs):
        existing = next(
            (item for item in self.jobs if item["idempotency_key"] == kwargs["idempotency_key"]),
            None,
        )
        if existing is not None:
            return existing["result"]
        result = SimpleNamespace(created=True, job=SimpleNamespace(id=uuid4()))
        kwargs["result"] = result
        self.jobs.append(kwargs)
        return result
