from __future__ import annotations

import os
import socket
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.events import redact_event_data
from app.jobs.models import RuntimeHeartbeat


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
        values = {
            "component_id": component_id,
            "component_type": component_type,
            "capabilities": sorted(set(capabilities)),
            "observed_at": observed_at,
            "metadata": redact_event_data(metadata),
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

    async def list_recent(self, *, limit: int = 100) -> list[RuntimeHeartbeat]:
        rows = await self.session.scalars(
            select(RuntimeHeartbeat).order_by(RuntimeHeartbeat.observed_at.desc()).limit(limit)
        )
        return list(rows)
