from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

FAULT_POINTS = frozenset(
    {
        "worker.after_claim",
        "worker.before_heartbeat",
        "worker.after_handler_before_terminal",
        "worker.after_terminal_commit",
        "research.after_provider_before_persist",
        "generation.after_provider_before_persist",
        "telegram_process.after_provider_before_persist",
        "export.after_manifest_before_commit",
        "retention.after_filesystem_delete_before_finalize",
        "telegram.before_send",
        "telegram.after_send_before_receipt",
        "publication.after_receipt_before_commit",
    }
)


def _validate_point(point: str) -> None:
    if point not in FAULT_POINTS:
        raise ValueError(f"unknown fault point: {point}")


class FaultInjector(Protocol):
    async def hit(self, point: str, context: Mapping[str, object]) -> None: ...


class NoopFaultInjector:
    async def hit(self, point: str, context: Mapping[str, object]) -> None:
        _validate_point(point)
