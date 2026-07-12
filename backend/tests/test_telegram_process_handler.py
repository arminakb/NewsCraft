from __future__ import annotations

import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.automations.telegram.handlers import (
    build_evidence_map,
    sha256_canonical,
    validate_evidence_snapshot,
)
from app.automations.telegram.policy import evaluate_auto_publish


def valid_gate_input() -> dict:
    return {
        "global_pause": False,
        "global_dry_run": False,
        "route_paused": False,
        "destination_enabled": True,
        "destination_health": "healthy",
        "destination_allows_auto": True,
        "validation_ok": True,
        "evidence_ready": True,
        "media_ready": True,
    }


@pytest.mark.parametrize(
    ("override", "allowed", "reason"),
    [
        ({}, True, None),
        ({"global_pause": True}, False, "global_pause"),
        ({"global_dry_run": True}, False, "global_dry_run"),
        ({"route_paused": True}, False, "route_paused"),
        ({"destination_enabled": False}, False, "destination_disabled"),
        ({"destination_health": "broken"}, False, "destination_unhealthy"),
        ({"destination_allows_auto": False}, False, "destination_auto_disabled"),
        ({"validation_ok": False}, False, "variant_invalid"),
        ({"evidence_ready": False}, False, "evidence_invalid"),
        ({"media_ready": False}, False, "media_not_ready"),
    ],
)
def test_auto_publish_gate_is_fail_closed(override, allowed, reason):
    decision = evaluate_auto_publish(**{**valid_gate_input(), **override})

    assert (decision.allowed, decision.reason) == (allowed, reason)


def test_captured_snapshot_is_verified_and_cited_exactly():
    text = "متن منبع"
    snapshot = SimpleNamespace(
        id=uuid4(),
        evidence_key="telegram:channel:42",
        source_url="https://t.me/channel/42",
        content_text=text,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )

    validate_evidence_snapshot(snapshot)
    evidence = build_evidence_map(snapshot)

    assert evidence == [
        {
            "evidence_snapshot_id": str(snapshot.id),
            "evidence_key": snapshot.evidence_key,
            "source_url": snapshot.source_url,
            "locator": f"chars:0-{len(text)}",
            "excerpt_sha256": snapshot.content_sha256,
        }
    ]
    assert sha256_canonical({"content": {"body": "x"}, "evidence_map": evidence}) == (
        sha256_canonical({"evidence_map": evidence, "content": {"body": "x"}})
    )


@pytest.mark.parametrize("text,digest", [("", hashlib.sha256(b"").hexdigest()), ("body", "0" * 64)])
def test_invalid_snapshot_fails_before_generation(text, digest):
    snapshot = SimpleNamespace(content_text=text, content_sha256=digest)

    with pytest.raises(ValueError, match="evidence"):
        validate_evidence_snapshot(snapshot)
