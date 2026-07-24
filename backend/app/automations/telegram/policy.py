from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AutoPublishDecision:
    allowed: bool
    reason: str | None = None


def evaluate_auto_publish(
    *,
    global_pause: bool,
    global_dry_run: bool,
    route_paused: bool,
    destination_enabled: bool,
    destination_health: str,
    validation_ok: bool,
    evidence_ready: bool,
    media_ready: bool,
) -> AutoPublishDecision:
    gates = (
        (global_pause, "global_pause"),
        (global_dry_run, "global_dry_run"),
        (route_paused, "route_paused"),
        (not destination_enabled, "destination_disabled"),
        (destination_health != "healthy", "destination_unhealthy"),
        (not validation_ok, "variant_invalid"),
        (not evidence_ready, "evidence_invalid"),
        (not media_ready, "media_not_ready"),
    )
    for blocked, reason in gates:
        if blocked:
            return AutoPublishDecision(False, reason)
    return AutoPublishDecision(True)
