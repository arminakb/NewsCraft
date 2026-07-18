from __future__ import annotations

import argparse
import asyncio
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.session import async_session
from app.jobs.models import RuntimeHeartbeat
from app.jobs.runtime import build_component_id

COMPONENT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
JOB_TYPE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
SUPPORTED_CAPABILITIES = frozenset({"generation", "ingestion", "publishing", "scheduling", "source"})


async def check_component(
    component_type: str,
    max_age_seconds: float,
    *,
    component_id: str | None = None,
    expected_capabilities: tuple[str, ...] = (),
    expected_job_types: tuple[str, ...] = (),
) -> int:
    expected_component_id = component_id or build_component_id(component_type)
    try:
        async with async_session() as session:
            heartbeat = await session.get(RuntimeHeartbeat, expected_component_id)
            if heartbeat is None:
                return 1
            if heartbeat.component_id != expected_component_id:
                return 1
            if heartbeat.component_type != component_type:
                return 1
            capabilities = _string_tuple(heartbeat.capabilities)
            if capabilities != expected_capabilities:
                return 1
            metadata = heartbeat.runtime_metadata
            if not isinstance(metadata, Mapping):
                return 1
            job_types = _string_tuple(metadata.get("job_types"))
            if job_types != expected_job_types:
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
    parser.add_argument("--component-id")
    parser.add_argument("--component-type", choices=("worker", "scheduler"), required=True)
    parser.add_argument("--expected-capabilities", required=True)
    parser.add_argument("--expected-job-types", required=True)
    parser.add_argument("--max-age-seconds", type=float, required=True)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.max_age_seconds <= 0:
        raise SystemExit(2)
    component_id = arguments.component_id or build_component_id(arguments.component_type)
    expected_capabilities = _parse_capabilities(arguments.expected_capabilities)
    expected_job_types = _parse_job_types(arguments.expected_job_types)
    if not COMPONENT_ID.fullmatch(component_id):
        raise SystemExit(2)
    if arguments.component_type == "worker" and not expected_job_types:
        raise SystemExit(2)
    if arguments.component_type == "scheduler" and expected_job_types:
        raise SystemExit(2)
    raise SystemExit(
        asyncio.run(
            check_component(
                arguments.component_type,
                arguments.max_age_seconds,
                component_id=component_id,
                expected_capabilities=expected_capabilities,
                expected_job_types=expected_job_types,
            )
        )
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    if not all(isinstance(item, str) for item in value):
        return ()
    return tuple(sorted(set(value)))


def _parse_capabilities(value: str) -> tuple[str, ...]:
    parsed = tuple(sorted({item.strip() for item in value.split(",") if item.strip()}))
    if not parsed or set(parsed) - SUPPORTED_CAPABILITIES:
        raise SystemExit(2)
    return parsed


def _parse_job_types(value: str) -> tuple[str, ...]:
    parsed = tuple(sorted({item.strip() for item in value.split(",") if item.strip()}))
    if any(not JOB_TYPE.fullmatch(item) for item in parsed):
        raise SystemExit(2)
    return parsed


if __name__ == "__main__":
    main()
