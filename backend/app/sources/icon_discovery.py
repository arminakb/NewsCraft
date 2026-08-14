from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import UUID

import feedparser
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.outbound_proxy import OutboundProxyPolicy, ProxyConfigurationError
from app.core.safe_http import SafeHttpClient, SafeHttpError
from app.db.models import Source
from app.jobs.errors import PermanentJobError
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin
from app.media.atomic_files import atomic_write
from app.media.imagecodec import normalized_content_type, sniff_image
from app.media.svg_sanitizer import is_safe_svg
from app.normalization.url_safety import UnsafeUrlError, validate_public_http_url

ICON_JOB_TYPE = "source.icon.discover"
ICON_PLATFORMS = ("rss", "atom")
ICON_STATUS_PENDING = "pending"
ICON_STATUS_QUEUED = "queued"
ICON_STATUS_RESOLVED = "resolved"
ICON_STATUS_RETRYABLE = "retryable"
ICON_STATUS_UNAVAILABLE = "unavailable"

logger = logging.getLogger(__name__)

_ALLOWED_MIME_TYPES = {
    "image/gif": ".gif",
    "image/jpg": ".jpg",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/vnd.microsoft.icon": ".ico",
    "image/webp": ".webp",
    "image/x-icon": ".ico",
}
_ALLOWED_RESPONSE_MIME_TYPES = frozenset(
    {
        *(_ALLOWED_MIME_TYPES),
        "application/octet-stream",
        "application/ico",
        "application/x-icon",
    }
)
_MAX_ICON_DIMENSION = 4096
_MAX_CANDIDATES = 12


@dataclass(frozen=True, slots=True)
class IconCandidate:
    url: str
    source: str


@dataclass(frozen=True, slots=True)
class FeedIdentity:
    publisher_url: str | None
    candidates: tuple[IconCandidate, ...]


@dataclass(frozen=True, slots=True)
class SourceIconTarget:
    id: UUID
    platform: str
    feed_url: str | None
    homepage_url: str | None


@dataclass(frozen=True, slots=True)
class IconDiscoveryResult:
    status: str
    icon_source: str | None = None
    original_url: str | None = None
    publisher_url: str | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    body: bytes | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _ValidatedIcon:
    mime_type: str
    width: int | None
    height: int | None
    body: bytes


class IconCandidateError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    value = str(value).strip()
    return value or None


def _mapping_value(value: Any, *keys: str) -> str | None:
    if isinstance(value, Mapping):
        for key in keys:
            candidate = _text(value.get(key))
            if candidate:
                return candidate
    return _text(value)


def _absolute_http_url(value: str | None, base_url: str) -> str | None:
    if not value:
        return None
    resolved = urljoin(base_url, value.strip())
    parsed = urlsplit(resolved)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return resolved


def _origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))


def _safe_log_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "<invalid>"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def _dedupe_candidates(candidates: list[IconCandidate]) -> tuple[IconCandidate, ...]:
    seen: set[str] = set()
    unique: list[IconCandidate] = []
    for candidate in candidates:
        if candidate.url in seen:
            continue
        seen.add(candidate.url)
        unique.append(candidate)
        if len(unique) >= _MAX_CANDIDATES:
            break
    return tuple(unique)


def extract_feed_identity(feed_body: str | bytes, source_url: str) -> FeedIdentity:
    """Extract publisher and feed-declared icon candidates without network access."""

    parsed = feedparser.parse(feed_body)
    feed = parsed.feed if getattr(parsed, "feed", None) else {}
    candidates: list[IconCandidate] = []

    for field_name, source_name in (
        ("image", "feed_image"),
        ("logo", "feed_logo"),
        ("icon", "feed_icon"),
        ("itunes_image", "feed_image"),
    ):
        value = _mapping_value(feed.get(field_name), "href", "url", "src", "value")
        resolved = _absolute_http_url(value, source_url)
        if resolved:
            candidates.append(IconCandidate(resolved, source_name))

    publisher_candidates: list[str] = []
    for link in feed.get("links", []) or []:
        rels = link.get("rel", []) if isinstance(link, Mapping) else []
        if isinstance(rels, str):
            rels = rels.split()
        rel_set = {str(rel).casefold() for rel in rels}
        href = _mapping_value(link, "href", "url")
        if "icon" in rel_set or "logo" in rel_set:
            resolved = _absolute_http_url(href, source_url)
            if resolved:
                candidates.append(IconCandidate(resolved, "feed_link_icon"))
        if "alternate" in rel_set or "canonical" in rel_set:
            resolved = _absolute_http_url(href, source_url)
            if resolved:
                publisher_candidates.append(resolved)

    for value in (
        feed.get("link"),
        _mapping_value(feed.get("source"), "href", "url", "link"),
    ):
        resolved = _absolute_http_url(_text(value), source_url)
        if resolved:
            publisher_candidates.append(resolved)

    for entry in (getattr(parsed, "entries", []) or [])[:5]:
        source = entry.get("source") if isinstance(entry, Mapping) else None
        resolved = _absolute_http_url(_mapping_value(source, "href", "url", "link"), source_url)
        if resolved:
            publisher_candidates.append(resolved)

    publisher_url = next(
        (
            candidate
            for candidate in publisher_candidates
            if candidate.rstrip("/") != source_url.rstrip("/")
        ),
        None,
    )
    return FeedIdentity(publisher_url=publisher_url, candidates=_dedupe_candidates(candidates))


def extract_website_icon_candidates(html: str | bytes, base_url: str) -> tuple[IconCandidate, ...]:
    soup = BeautifulSoup(html, "html.parser")
    grouped: dict[str, list[IconCandidate]] = {
        "website_icon": [],
        "website_shortcut_icon": [],
        "website_apple_touch_icon": [],
    }
    for link in soup.find_all("link"):
        href = _absolute_http_url(_text(link.get("href")), base_url)
        if not href:
            continue
        raw_rel = link.get("rel")
        if raw_rel is None:
            rel: list[str] = []
        elif isinstance(raw_rel, str):
            rel = raw_rel.split()
        else:
            rel = [str(value) for value in raw_rel]
        rel_set = {value.casefold() for value in rel}
        if "apple-touch-icon" in rel_set:
            grouped["website_apple_touch_icon"].append(IconCandidate(href, "website_apple_touch_icon"))
        elif "shortcut" in rel_set and "icon" in rel_set:
            grouped["website_shortcut_icon"].append(IconCandidate(href, "website_shortcut_icon"))
        elif "icon" in rel_set:
            grouped["website_icon"].append(IconCandidate(href, "website_icon"))
    return _dedupe_candidates(
        grouped["website_icon"]
        + grouped["website_shortcut_icon"]
        + grouped["website_apple_touch_icon"]
    )


def validate_icon_url(value: str) -> str:
    """Reject local, private, metadata, credentialed, and unsupported icon URLs."""

    try:
        return validate_public_http_url(value)
    except UnsafeUrlError:
        raise IconCandidateError("unsafe_url", retryable=False) from None


def _validate_icon_bytes(body: bytes, claimed_type: str | None, max_bytes: int) -> _ValidatedIcon:
    if not body:
        raise IconCandidateError("icon_empty", retryable=False)
    if len(body) > max_bytes:
        raise IconCandidateError("icon_too_large", retryable=False)

    detected = sniff_image(body)
    if detected is None:
        raise IconCandidateError("unsupported_image", retryable=False)
    if detected.mime_type == "image/svg+xml" and not is_safe_svg(body):
        raise IconCandidateError("unsafe_svg", retryable=False)
    if claimed_type and claimed_type not in _ALLOWED_RESPONSE_MIME_TYPES:
        raise IconCandidateError("unsupported_mime", retryable=False)
    if (
        detected.width < 1
        or detected.height < 1
        or detected.width > _MAX_ICON_DIMENSION
        or detected.height > _MAX_ICON_DIMENSION
    ):
        raise IconCandidateError("icon_dimensions_invalid", retryable=False)
    return _ValidatedIcon(
        detected.mime_type,
        detected.width,
        detected.height,
        body,
    )


async def _get_response(
    client: SafeHttpClient,
    url: str,
    *,
    max_bytes: int,
    source_id: UUID | None = None,
) -> httpx.Response:
    validate_icon_url(url)
    logger.debug(
        "source_icon_request source_id=%s url=%s",
        source_id,
        _safe_log_url(url),
    )
    try:
        response = await client.get(
            url,
            follow_redirects=True,
            headers={
                "accept": "text/html, application/xhtml+xml, image/*, application/xml;q=0.8, */*;q=0.1",
                "accept-encoding": "identity",
                "user-agent": "NewsCraftBot/1.0",
            },
        )
    except SafeHttpError as exc:
        message = str(exc)
        raise IconCandidateError(
            "unsafe_url" if "rejected" in message.casefold() else "network_error",
            retryable="rejected" not in message.casefold(),
        ) from exc
    except httpx.ProxyError as exc:
        raise IconCandidateError("proxy_error", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise IconCandidateError("network_error", retryable=True) from exc
    final_url = str(response.url)
    validate_icon_url(final_url)
    logger.debug(
        "source_icon_response source_id=%s requested_url=%s final_url=%s status=%s content_type=%s bytes=%s",
        source_id,
        _safe_log_url(url),
        _safe_log_url(final_url),
        response.status_code,
        normalized_content_type(response.headers.get("content-type")),
        len(response.content),
    )
    if response.status_code < 200 or response.status_code >= 300:
        raise IconCandidateError(
            f"http_{response.status_code}",
            retryable=response.status_code >= 500,
        )
    if len(response.content) > max_bytes:
        raise IconCandidateError("response_too_large", retryable=False)
    return response


class SourceIconDiscoveryService:
    def __init__(
        self,
        *,
        config: Settings = settings,
        http_client_factory: Callable[[], SafeHttpClient] | None = None,
        proxy_policy: OutboundProxyPolicy | None = None,
    ) -> None:
        self.config = config
        self.proxy_policy = proxy_policy
        self.http_client_factory = http_client_factory or (
            lambda: SafeHttpClient(
                timeout=config.source_icon_discovery_timeout_seconds,
                max_redirects=config.source_icon_discovery_max_redirects,
                max_response_bytes=config.source_icon_discovery_max_bytes,
                proxy_policy=self.proxy_policy,
            )
        )

    async def discover(self, target: SourceIconTarget) -> IconDiscoveryResult:
        request_url = target.feed_url or target.homepage_url
        if target.platform not in ICON_PLATFORMS or not request_url:
            return IconDiscoveryResult(status=ICON_STATUS_UNAVAILABLE, error="source_not_discoverable")

        try:
            client = self.http_client_factory()
        except ProxyConfigurationError:
            logger.exception(
                "source_icon_client_initialization_failed source_id=%s reason=proxy_configuration_error",
                target.id,
            )
            return IconDiscoveryResult(status=ICON_STATUS_RETRYABLE, error="proxy_configuration_error")
        except Exception:
            logger.exception(
                "source_icon_client_initialization_failed source_id=%s reason=client_initialization_error",
                target.id,
            )
            return IconDiscoveryResult(status=ICON_STATUS_RETRYABLE, error="client_initialization_error")
        async with client:
            try:
                feed_response = await _get_response(
                    client,
                    request_url,
                    max_bytes=self.config.source_icon_discovery_max_bytes,
                    source_id=target.id,
                )
            except IconCandidateError as exc:
                logger.info(
                    "source_icon_feed_failed source_id=%s url=%s reason=%s retryable=%s",
                    target.id,
                    _safe_log_url(request_url),
                    exc.code,
                    exc.retryable,
                )
                return IconDiscoveryResult(
                    status=ICON_STATUS_RETRYABLE if exc.retryable else ICON_STATUS_UNAVAILABLE,
                    error=exc.code,
                )

            feed_url = str(feed_response.url)
            identity = extract_feed_identity(feed_response.content, feed_url)
            publisher_url = identity.publisher_url or target.homepage_url or _origin(feed_url)
            logger.info(
                "source_icon_feed_identity source_id=%s publisher_url=%s candidates=%s",
                target.id,
                _safe_log_url(publisher_url) if publisher_url else None,
                [(candidate.source, _safe_log_url(candidate.url)) for candidate in identity.candidates],
            )
            saw_retryable = False
            first_failure_code: str | None = None
            for candidate in identity.candidates:
                result, candidate_retryable, candidate_error = await self._try_icon_candidate(
                    client,
                    candidate,
                    publisher_url,
                    source_id=target.id,
                )
                if result is not None:
                    return result
                saw_retryable = saw_retryable or candidate_retryable
                first_failure_code = first_failure_code or candidate_error

            website_url = publisher_url or target.homepage_url or _origin(feed_url)
            if website_url:
                website_base = website_url
                try:
                    website_response = await _get_response(
                        client,
                        website_url,
                        max_bytes=self.config.source_icon_discovery_max_bytes,
                        source_id=target.id,
                    )
                    website_base = str(website_response.url)
                    content_type = normalized_content_type(website_response.headers.get("content-type"))
                    if content_type in {None, "text/html", "application/xhtml+xml"}:
                        website_candidates = extract_website_icon_candidates(
                            website_response.content,
                            website_base,
                        )
                        for candidate in website_candidates:
                            result, candidate_retryable, candidate_error = await self._try_icon_candidate(
                                client,
                                candidate,
                                website_base,
                                source_id=target.id,
                            )
                            if result is not None:
                                return result
                            saw_retryable = saw_retryable or candidate_retryable
                            first_failure_code = first_failure_code or candidate_error
                except IconCandidateError as exc:
                    saw_retryable = saw_retryable or exc.retryable
                    first_failure_code = first_failure_code or exc.code
                conventional = IconCandidate(
                    url=urljoin(website_base, "/favicon.ico"),
                    source="conventional_favicon",
                )
                result, candidate_retryable, candidate_error = await self._try_icon_candidate(
                    client,
                    conventional,
                    website_base,
                    source_id=target.id,
                )
                if result is not None:
                    return result
                saw_retryable = saw_retryable or candidate_retryable
                first_failure_code = first_failure_code or candidate_error

            return IconDiscoveryResult(
                status=ICON_STATUS_RETRYABLE if saw_retryable else ICON_STATUS_UNAVAILABLE,
                publisher_url=publisher_url,
                error=first_failure_code or ("icon_fetch_failed" if saw_retryable else "icon_not_found"),
            )

    async def _try_icon_candidate(
        self,
        client: SafeHttpClient,
        candidate: IconCandidate,
        publisher_url: str | None,
        *,
        source_id: UUID,
    ) -> tuple[IconDiscoveryResult | None, bool, str | None]:
        try:
            response = await _get_response(
                client,
                candidate.url,
                max_bytes=self.config.source_icon_discovery_max_bytes,
                source_id=source_id,
            )
            validated = _validate_icon_bytes(
                response.content,
                normalized_content_type(response.headers.get("content-type")),
                self.config.source_icon_discovery_max_bytes,
            )
        except IconCandidateError as exc:
            logger.info(
                "source_icon_candidate_failed source_id=%s source=%s url=%s reason=%s retryable=%s",
                source_id,
                candidate.source,
                _safe_log_url(candidate.url),
                exc.code,
                exc.retryable,
            )
            return None, exc.retryable, exc.code
        logger.info(
            "source_icon_candidate_validated source_id=%s source=%s url=%s final_url=%s "
            "mime_type=%s dimensions=%sx%s bytes=%s",
            source_id,
            candidate.source,
            _safe_log_url(candidate.url),
            _safe_log_url(str(response.url)),
            validated.mime_type,
            validated.width,
            validated.height,
            len(validated.body),
        )
        return (
            IconDiscoveryResult(
                status=ICON_STATUS_RESOLVED,
                icon_source=candidate.source,
                original_url=str(response.url),
                publisher_url=publisher_url,
                mime_type=validated.mime_type,
                width=validated.width,
                height=validated.height,
                body=validated.body,
            ),
            False,
            None,
        )


def persist_icon_bytes(media_root: Path | str, body: bytes, mime_type: str) -> str:
    digest = hashlib.sha256(body).hexdigest()
    suffix = _ALLOWED_MIME_TYPES.get(mime_type, ".bin")
    root = Path(media_root) / "source-icons" / digest[:2]
    target = root / f"{digest}{suffix}"
    if target.exists():
        return str(target)
    atomic_write(target, body)
    return str(target)


def _retry_at(now: datetime, failure_count: int, result: IconDiscoveryResult, config: Settings) -> datetime:
    if result.status == ICON_STATUS_UNAVAILABLE:
        delay = config.source_icon_discovery_retry_max_seconds
    else:
        delay = min(
            config.source_icon_discovery_retry_max_seconds,
            config.source_icon_discovery_retry_base_seconds * (2 ** max(0, failure_count - 1)),
        )
    return now + timedelta(seconds=delay)


def source_icon_target(source: Source) -> SourceIconTarget:
    return SourceIconTarget(
        id=source.id,
        platform=str(source.platform),
        feed_url=source.feed_url,
        homepage_url=source.homepage_url,
    )


def build_source_icon_discovery_handler(
    service: SourceIconDiscoveryService,
    *,
    config: Settings = settings,
):
    async def handle_source_icon_discovery(job: JobExecution, context: JobContext) -> dict[str, Any]:
        payload = dict(job.payload)
        try:
            source_id = UUID(str(payload.get("source_id")))
            raw_attempt = payload.get("attempt")
            if not isinstance(raw_attempt, int | float | str):
                raise TypeError("attempt must be numeric")
            attempt = int(raw_attempt)
        except (TypeError, ValueError):
            raise PermanentJobError(
                code="source_icon_payload_invalid",
                message="Source icon discovery payload is invalid.",
            ) from None
        source = await context.session.scalar(
            select(Source).where(Source.id == source_id).with_for_update()
        )
        if source is None:
            return {"status": "orphaned", "source_id": str(source_id)}
        if source.platform not in ICON_PLATFORMS:
            source.icon_status = ICON_STATUS_UNAVAILABLE
            source.icon_enqueued_at = None
            return {"status": "skipped", "reason": "unsupported_platform"}
        if source.icon_attempt != attempt or source.icon_status != ICON_STATUS_QUEUED:
            return {"status": "stale", "source_id": str(source_id), "attempt": attempt}

        target = source_icon_target(source)
        source.icon_enqueued_at = datetime.now(UTC)
        await context.session.commit()
        try:
            result = await service.discover(target)
        except Exception as exc:  # noqa: BLE001 - discovery is isolated from the worker boundary
            if isinstance(exc, ProxyConfigurationError):
                error_code = "proxy_configuration_error"
            elif isinstance(exc, httpx.ProxyError):
                error_code = "proxy_error"
            elif isinstance(exc, (SafeHttpError, httpx.HTTPError)):
                error_code = "network_error"
            else:
                error_code = "discovery_failed"
            logger.exception(
                "source_icon_job_failed source_id=%s attempt=%s reason=%s error_type=%s",
                source_id,
                attempt,
                error_code,
                type(exc).__name__,
            )
            result = IconDiscoveryResult(status=ICON_STATUS_RETRYABLE, error=error_code)

        source = await context.session.scalar(
            select(Source).where(Source.id == source_id).with_for_update()
        )
        if source is None or source.icon_attempt != attempt:
            return {"status": "stale", "source_id": str(source_id), "attempt": attempt}
        observed_at = datetime.now(UTC)
        if not source.homepage_url and result.publisher_url:
            source.homepage_url = result.publisher_url
        if result.status == ICON_STATUS_RESOLVED and result.body and result.mime_type:
            try:
                storage_path = persist_icon_bytes(config.media_root, result.body, result.mime_type)
            except OSError:
                result = IconDiscoveryResult(
                    status=ICON_STATUS_RETRYABLE,
                    publisher_url=result.publisher_url,
                    error="icon_storage_failed",
                )
            else:
                source.icon_url = f"/sources/{source.id}/icon"
                source.icon_source = result.icon_source
                source.icon_updated_at = observed_at
                source.icon_status = ICON_STATUS_RESOLVED
                source.icon_storage_path = storage_path
                source.icon_original_url = result.original_url
                source.icon_mime_type = result.mime_type
                source.icon_width = result.width
                source.icon_height = result.height
                source.icon_failure_count = 0
                source.icon_next_retry_at = None
                source.icon_last_error = None
                source.icon_enqueued_at = None
                logger.info(
                    "source_icon_job_result source_id=%s attempt=%s status=%s icon_source=%s "
                    "mime_type=%s storage_path=%s",
                    source.id,
                    attempt,
                    ICON_STATUS_RESOLVED,
                    result.icon_source,
                    result.mime_type,
                    storage_path,
                )
                return {
                    "status": ICON_STATUS_RESOLVED,
                    "source_id": str(source.id),
                    "icon_source": result.icon_source,
                }

        failure_count = int(source.icon_failure_count or 0) + 1
        source.icon_failure_count = failure_count
        source.icon_status = (
            result.status
            if result.status in {ICON_STATUS_RETRYABLE, ICON_STATUS_UNAVAILABLE}
            else ICON_STATUS_RETRYABLE
        )
        source.icon_next_retry_at = _retry_at(observed_at, failure_count, result, config)
        source.icon_last_error = result.error or "icon_discovery_failed"
        source.icon_enqueued_at = None
        logger.info(
            "source_icon_job_result source_id=%s attempt=%s status=%s error=%s failure_count=%s "
            "next_retry_at=%s",
            source.id,
            attempt,
            source.icon_status,
            source.icon_last_error,
            source.icon_failure_count,
            source.icon_next_retry_at,
        )
        return {
            "status": source.icon_status,
            "source_id": str(source.id),
            "error": source.icon_last_error,
        }

    return handle_source_icon_discovery


async def enqueue_source_icon_discovery(
    session: AsyncSession,
    source_id: UUID,
    *,
    origin: JobOrigin,
    config: Settings = settings,
    now: datetime | None = None,
) -> bool:
    """Claim one source icon attempt and enqueue it. Scheduler remains the repair path."""

    observed_at = now or datetime.now(UTC)
    source = await session.scalar(select(Source).where(Source.id == source_id).with_for_update())
    if source is None or not source.active or source.deleted_at is not None or source.platform not in ICON_PLATFORMS:
        return False
    if source.icon_status == ICON_STATUS_QUEUED and source.icon_enqueued_at is not None:
        return False
    if source.icon_status == ICON_STATUS_RESOLVED and source.icon_updated_at is not None:
        fresh_until = source.icon_updated_at + timedelta(days=config.source_icon_discovery_ttl_days)
        if fresh_until > observed_at:
            return False
    if source.icon_status in {ICON_STATUS_RETRYABLE, ICON_STATUS_UNAVAILABLE} and source.icon_next_retry_at:
        if source.icon_next_retry_at > observed_at:
            return False

    source.icon_status = ICON_STATUS_QUEUED
    source.icon_enqueued_at = observed_at
    source.icon_attempt = int(source.icon_attempt or 0) + 1
    await session.flush()
    await JobRepository(session).enqueue_job(
        job_type=ICON_JOB_TYPE,
        payload={"source_id": str(source.id), "attempt": source.icon_attempt},
        idempotency_key=f"source-icon:{source.id}:{source.icon_attempt}",
        origin=origin,
        priority=-1,
        max_attempts=1,
        pause_sensitive=False,
    )
    return True


__all__ = [
    "ICON_JOB_TYPE",
    "ICON_PLATFORMS",
    "ICON_STATUS_PENDING",
    "ICON_STATUS_QUEUED",
    "ICON_STATUS_RESOLVED",
    "ICON_STATUS_RETRYABLE",
    "ICON_STATUS_UNAVAILABLE",
    "FeedIdentity",
    "IconCandidate",
    "IconDiscoveryResult",
    "SourceIconDiscoveryService",
    "SourceIconTarget",
    "build_source_icon_discovery_handler",
    "enqueue_source_icon_discovery",
    "extract_feed_identity",
    "extract_website_icon_candidates",
    "persist_icon_bytes",
    "validate_icon_url",
]
