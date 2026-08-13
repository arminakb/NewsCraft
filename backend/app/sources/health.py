from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.core.outbound_proxy import build_outbound_http_client
from app.core.redaction import redact_string
from app.db.models import Source
from app.sources.fetch_target import (
    MissingFetchTarget,
    parse_source_payload,
    source_request_url,
)

HEALTH_CHECK_HEADERS = {"User-Agent": "NewsCraftBot/1.0"}


@dataclass(frozen=True, slots=True)
class SourceHealthCheck:
    status: str
    checked_at: datetime
    http_status: int | None = None
    failure_reason: str | None = None


async def check_source_health(
    source: Source,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> SourceHealthCheck:
    checked_at = datetime.now(UTC)
    owns_client = http_client is None
    client = http_client or build_outbound_http_client(timeout=15.0)
    try:
        request_url = source_request_url(source)
        response = await client.get(
            request_url,
            headers=HEALTH_CHECK_HEADERS,
            follow_redirects=True,
        )
        if response.status_code >= 400:
            return _broken(
                checked_at,
                http_status=response.status_code,
                reason=f"Source returned HTTP {response.status_code}.",
            )
        if response.status_code == 304:
            return SourceHealthCheck(
                status="healthy",
                checked_at=checked_at,
                http_status=response.status_code,
            )

        parsed = parse_source_payload(source, response.text, request_url)
        malformed = next(
            (warning for warning in parsed.warnings if warning.startswith("bozo_feed:")),
            None,
        )
        if malformed:
            return _broken(
                checked_at,
                http_status=response.status_code,
                reason="Response is not a valid RSS or Atom feed.",
            )
        if not parsed.items:
            return _broken(
                checked_at,
                http_status=response.status_code,
                reason="Response contained no valid source items.",
            )
        return SourceHealthCheck(
            status="healthy",
            checked_at=checked_at,
            http_status=response.status_code,
        )
    except asyncio.CancelledError:
        raise
    except MissingFetchTarget:
        # Operator-facing wording: the source is unconfigured, not unreachable.
        return _broken(checked_at, reason="Source is missing connectivity information.")
    except Exception as exc:  # noqa: BLE001 - health result must classify transport and validation failures
        return _broken(
            checked_at,
            reason=redact_string(str(exc)) or exc.__class__.__name__,
        )
    finally:
        if owns_client:
            await client.aclose()


def _broken(
    checked_at: datetime,
    *,
    reason: str,
    http_status: int | None = None,
) -> SourceHealthCheck:
    return SourceHealthCheck(
        status="broken",
        checked_at=checked_at,
        http_status=http_status,
        failure_reason=redact_string(reason),
    )
