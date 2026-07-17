from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.session import async_session
from app.jobs.models import RuntimeHeartbeat
from app.jobs.runtime import build_component_id


async def check_component(component_type: str, max_age_seconds: float) -> int:
    component_id = build_component_id(component_type)
    try:
        async with async_session() as session:
            heartbeat = await session.get(RuntimeHeartbeat, component_id)
            if heartbeat is None or heartbeat.component_type != component_type:
                return 1
            observed_at = heartbeat.observed_at
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                return 1
            database_now = await session.scalar(select(func.clock_timestamp()))
            if not isinstance(database_now, datetime):
                return 1
            if database_now.tzinfo is None or database_now.utcoffset() is None:
                return 1
            age = (database_now.astimezone(UTC) - observed_at.astimezone(UTC)).total_seconds()
            return 0 if 0 <= age <= max_age_seconds else 1
    except Exception:  # noqa: BLE001 - health commands fail closed without error details
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check one persisted runtime heartbeat")
    parser.add_argument("--component-type", choices=("worker", "scheduler"), required=True)
    parser.add_argument("--max-age-seconds", type=float, required=True)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.max_age_seconds <= 0:
        raise SystemExit(2)
    raise SystemExit(asyncio.run(check_component(arguments.component_type, arguments.max_age_seconds)))


if __name__ == "__main__":
    main()
