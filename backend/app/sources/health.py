from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.core.outbound_proxy import build_outbound_http_client
from app.core.redaction import redact_string
from app.db.models import Source
from app.sources.registry import parser_for_source

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
        request_url = _request_url(source)
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

        parsed = _parse_response(source, response.text, request_url)
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
    except Exception as exc:  # noqa: BLE001 - health result must classify transport and validation failures
        return _broken(
            checked_at,
            reason=redact_string(str(exc)) or exc.__class__.__name__,
        )
    finally:
        if owns_client:
            await client.aclose()


def _request_url(source: Source) -> str:
    if source.platform in {"rss", "atom"} and source.feed_url:
        return source.feed_url
    if source.platform == "telegram_public" and source.telegram_username:
        return f"https://t.me/s/{source.telegram_username}"
    raise ValueError("Source is missing connectivity information.")


def _parse_response(source: Source, raw_text: str, request_url: str):
    parser = parser_for_source(source)
    if source.platform in {"rss", "atom"}:
        return parser(
            raw_text,
            source_name=source.name,
            source_url=source.feed_url or request_url,
            default_timezone=source.default_timezone or "UTC",
        )
    if source.platform == "telegram_public":
        return parser(raw_text, channel=source.telegram_username)
    raise ValueError(f"Unsupported source platform: {source.platform}")


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
