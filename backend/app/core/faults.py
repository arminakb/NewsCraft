from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from app.core.redaction import redact_secrets

FAULT_POINTS = frozenset(
    {
        "worker.after_claim",
        "worker.before_heartbeat",
        "research.after_provider_before_persist",
        "generation.after_provider_before_persist",
        "export.after_manifest_before_commit",
        "telegram.before_send",
        "telegram.after_send_before_receipt",
        "publication.after_receipt_before_commit",
    }
)


def _validate_point(point: str) -> None:
    if point not in FAULT_POINTS:
        raise ValueError(f"unknown fault point: {point}")


def _redacted_context(context: Mapping[str, object]) -> Mapping[str, object]:
    sanitized = redact_secrets(context)
    if not isinstance(sanitized, dict):  # pragma: no cover - Mapping input contract
        sanitized = {"context": sanitized}
    return MappingProxyType(sanitized)


class FaultInjector(Protocol):
    async def hit(self, point: str, context: Mapping[str, object]) -> None: ...


class NoopFaultInjector:
    async def hit(self, point: str, context: Mapping[str, object]) -> None:
        _validate_point(point)


@dataclass(frozen=True, slots=True)
class FaultHit:
    point: str
    context: Mapping[str, object]


class InjectedFault(BaseException):
    """Test-only process-death signal that ordinary exception handlers cannot swallow."""

    def __init__(self, point: str, context: Mapping[str, object]) -> None:
        self.point = point
        self.context = _redacted_context(context)
        super().__init__(f"fault injected at {point}")


class ScriptedFaultInjector:
    """Deterministic test injector; production runtimes never construct this class."""

    def __init__(self, script: Mapping[str, int] | Iterable[str] = ()) -> None:
        counts = Counter(script)
        for point, count in counts.items():
            _validate_point(point)
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise ValueError("fault hit counts must be positive integers")
        self._remaining = counts
        self._hits: list[FaultHit] = []

    @property
    def hits(self) -> tuple[FaultHit, ...]:
        return tuple(self._hits)

    async def hit(self, point: str, context: Mapping[str, object]) -> None:
        _validate_point(point)
        safe_context = _redacted_context(context)
        self._hits.append(FaultHit(point=point, context=safe_context))
        if self._remaining[point] <= 0:
            return
        self._remaining[point] -= 1
        raise InjectedFault(point, safe_context)
