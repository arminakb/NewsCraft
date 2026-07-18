from __future__ import annotations

import os
import socket
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.events import redact_event_data
from app.jobs.models import RuntimeHeartbeat

RESTART_HISTORY_LIMIT = 32


def build_component_id(component_type: str) -> str:
    explicit = os.getenv("NEWSCRAFT_COMPONENT_ID")
    if explicit and explicit.strip():
        return explicit.strip()
    return f"{component_type}:{socket.gethostname()}:{os.getpid()}"


class RuntimeHeartbeatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        component_id: str,
        component_type: str,
        capabilities: tuple[str, ...],
        observed_at: datetime,
        metadata: dict[str, Any],
    ) -> None:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        safe_metadata = redact_event_data(metadata)
        safe_metadata = await self._with_restart_history(
            component_id=component_id,
            observed_at=observed_at,
            metadata=safe_metadata,
        )
        values = {
            "component_id": component_id,
            "component_type": component_type,
            "capabilities": sorted(set(capabilities)),
            "observed_at": observed_at,
            "metadata": safe_metadata,
        }
        statement = insert(RuntimeHeartbeat.__table__).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["component_id"],
            set_={
                "component_type": statement.excluded.component_type,
                "capabilities": statement.excluded.capabilities,
                "observed_at": statement.excluded.observed_at,
                "metadata": statement.excluded.metadata,
            },
        )
        await self.session.execute(statement)

    async def _with_restart_history(
        self,
        *,
        component_id: str,
        observed_at: datetime,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        instance_id = metadata.get("process_instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            return metadata
        existing = await self.session.get(
            RuntimeHeartbeat,
            component_id,
            populate_existing=True,
            with_for_update=True,
        )
        previous_metadata = (
            existing.runtime_metadata if existing is not None and isinstance(existing.runtime_metadata, Mapping) else {}
        )
        history = _restart_history(previous_metadata.get("restart_observed_at"))
        previous_instance = previous_metadata.get("process_instance_id")
        if isinstance(previous_instance, str) and previous_instance != instance_id:
            restarted_at = observed_at.astimezone(UTC)
            if not history or history[-1] != restarted_at:
                history.append(restarted_at)
        metadata["restart_observed_at"] = [value.isoformat() for value in history[-RESTART_HISTORY_LIMIT:]]
        return metadata

    async def list_recent(self, *, limit: int = 100) -> list[RuntimeHeartbeat]:
        rows = await self.session.scalars(
            select(RuntimeHeartbeat).order_by(RuntimeHeartbeat.observed_at.desc()).limit(limit)
        )
        return list(rows)


def _restart_history(value: object) -> list[datetime]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    parsed: list[datetime] = []
    for item in value[-RESTART_HISTORY_LIMIT:]:
        if not isinstance(item, str) or len(item) > 64:
            continue
        try:
            observed_at = datetime.fromisoformat(item.replace("Z", "+00:00"))
        except ValueError:
            continue
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            continue
        parsed.append(observed_at.astimezone(UTC))
    return sorted(set(parsed))
