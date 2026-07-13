from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redaction import redact_string
from app.db.models import Source
from app.ingestion.repository import IngestionRepository, build_item_identities
from app.ingestion.service import (
    _build_http_client,
    _is_suitable_item,
    _parse_source_payload,
    _payload_kind,
    _record_source_failure,
    _record_source_not_modified,
    _record_source_success,
    _request_headers,
    _sanitized_stats,
    _source_request_url,
)


@dataclass(frozen=True, slots=True)
class PreparedSource:
    """Immutable snapshot of every source field used by network/parsing code."""

    id: UUID
    name: str
    platform: str
    feed_url: str | None
    telegram_username: str | None
    default_timezone: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class PreparedIngestionRun:
    run_id: UUID
    sources: tuple[PreparedSource, ...]


@dataclass(frozen=True, slots=True)
class FetchedSourceBatch:
    """Frozen fetch envelope with immutable collection shells.

    Existing parser item values are mutable domain objects and are treated as
    read-only after capture; this DTO does not claim to deep-freeze them.
    """

    source: PreparedSource
    request_url: str
    final_url: str
    http_status: int
    headers: Mapping[str, str]
    content_type: str | None
    raw_text: str
    parser_warnings: tuple[str, ...]
    parsed_items: tuple[Any, ...]
    processing_failure: SourceProcessingFailure | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(self, "parser_warnings", tuple(self.parser_warnings))
        object.__setattr__(self, "parsed_items", tuple(self.parsed_items))


@dataclass(frozen=True, slots=True)
class SourceProcessingFailure:
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class SourcePersistResult:
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    items: int = 0
    media_candidates: int = 0
    errors: tuple[dict[str, str], ...] = ()
    processing_failure: SourceProcessingFailure | None = None


def _snapshot_source(source: Source) -> PreparedSource:
    return PreparedSource(
        id=source.id,
        name=source.name,
        platform=source.platform,
        feed_url=source.feed_url,
        telegram_username=source.telegram_username,
        default_timezone=source.default_timezone or "UTC",
        etag=source.etag,
        last_modified=source.last_modified,
    )


@asynccontextmanager
async def _transaction(session: AsyncSession, label: str):
    try:
        context = session.begin(label)
    except TypeError:
        context = session.begin()
    async with context:
        yield


def _has_transaction(session: AsyncSession) -> bool:
    state = session.in_transaction()
    return bool(state)


class IngestionWorkflow:
    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self.http_client = http_client

    async def prepare_run(
        self,
        session: AsyncSession,
        *,
        platforms: list[str] | None,
        source_ids: list[str] | None,
        trigger: str,
    ) -> PreparedIngestionRun:
        repository = IngestionRepository(session)
        run = await repository.create_run(trigger=trigger, parser_version=settings.parser_version)
        sources = await repository.get_active_sources(platforms=platforms)
        if source_ids:
            wanted = set(source_ids)
            sources = [source for source in sources if str(source.id) in wanted]
        return PreparedIngestionRun(run_id=run.id, sources=tuple(_snapshot_source(source) for source in sources))

    async def fetch_source(self, source: PreparedSource) -> FetchedSourceBatch:
        request_url = _source_request_url(source)  # type: ignore[arg-type]
        owns_client = self.http_client is None
        client = self.http_client or _build_http_client()
        try:
            response = await client.get(
                request_url,
                headers=_request_headers(source),  # type: ignore[arg-type]
                follow_redirects=True,
            )
            warnings: tuple[str, ...] = ()
            items: tuple[Any, ...] = ()
            processing_failure = None
            if response.status_code < 400 and response.status_code != 304:
                try:
                    parsed = _parse_source_payload(source, response.text, request_url)  # type: ignore[arg-type]
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - retain fetched evidence for classified failure
                    processing_failure = SourceProcessingFailure(
                        error_type=redact_string(exc.__class__.__name__),
                        message=redact_string(str(exc)),
                    )
                else:
                    warnings = tuple(parsed.warnings)
                    items = tuple(parsed.items)
            return FetchedSourceBatch(
                source=source,
                request_url=request_url,
                final_url=str(response.url),
                http_status=response.status_code,
                headers=dict(response.headers),
                content_type=response.headers.get("content-type"),
                raw_text=response.text,
                parser_warnings=warnings,
                parsed_items=items,
                processing_failure=processing_failure,
            )
        finally:
            if owns_client:
                await client.aclose()

    async def persist_source(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        batch: FetchedSourceBatch,
    ) -> SourcePersistResult:
        repository = IngestionRepository(session)
        source = await session.get(Source, batch.source.id)
        if source is None:
            raise RuntimeError("Prepared ingestion source no longer exists")
        payload = await repository.save_raw_payload(
            run_id=run_id,
            source_id=source.id,
            payload_kind=_payload_kind(source),
            request_url=batch.request_url,
            final_url=batch.final_url,
            http_status=batch.http_status,
            headers=dict(batch.headers),
            content_type=batch.content_type,
            raw_text=batch.raw_text,
            parser_warnings=list(batch.parser_warnings),
        )
        source.etag = batch.headers.get("etag") or source.etag
        source.last_modified = batch.headers.get("last-modified") or source.last_modified
        source.last_fetch_at = datetime.now(UTC)
        source.last_http_status = batch.http_status

        response = _PersistedResponse(batch)
        if batch.http_status == 304:
            _record_source_not_modified(source, response)  # type: ignore[arg-type]
            return SourcePersistResult(skipped=1)
        if batch.http_status >= 400:
            error = RuntimeError(f"HTTP {batch.http_status} for {batch.request_url}")
            _record_source_failure(
                source,
                error,
                http_status=batch.http_status,
                error_type=f"http_{batch.http_status}",
            )
            return SourcePersistResult(
                failed=1,
                errors=(
                    {
                        "source": redact_string(source.name),
                        "error": redact_string(str(error)),
                    },
                ),
            )
        if batch.processing_failure is not None:
            return SourcePersistResult(fetched=1, processing_failure=batch.processing_failure)

        item_count = 0
        media_count = 0
        try:
            async with session.begin_nested():
                for parsed_item in batch.parsed_items:
                    source_item = await repository.upsert_source_item(
                        run_id=run_id,
                        source_id=source.id,
                        raw_payload_id=payload.id,
                        parsed_item=parsed_item,
                    )
                    identities = build_item_identities(source, parsed_item)
                    content_item = await repository.upsert_content_item(
                        source=source,
                        source_item=source_item,
                        parsed_item=parsed_item,
                        identities=identities,
                    )
                    await repository.attach_identities(
                        content_item_id=content_item.id,
                        source_item_id=source_item.id,
                        source_id=source.id,
                        identities=identities,
                    )
                    media_assets = await repository.upsert_media_assets(parsed_item)
                    await repository.attach_item_media(
                        content_item_id=content_item.id,
                        media_assets=media_assets,
                        parsed_item=parsed_item,
                    )
                    item_count += 1
                    media_count += len(parsed_item.media_candidates)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - raw response remains durable outside the savepoint
            return SourcePersistResult(
                fetched=1,
                processing_failure=SourceProcessingFailure(
                    error_type=redact_string(exc.__class__.__name__),
                    message=redact_string(str(exc)),
                ),
            )

        parse_count = len(batch.parsed_items)
        suitable_count = sum(1 for item in batch.parsed_items if _is_suitable_item(item))
        _record_source_success(
            source,
            response,  # type: ignore[arg-type]
            parse_count=parse_count,
            suitable_count=suitable_count,
            media_count=media_count,
            parser_warnings=list(batch.parser_warnings),
        )
        return SourcePersistResult(fetched=1, items=item_count, media_candidates=media_count)

    async def record_source_failure(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        source: PreparedSource,
        error: Exception,
    ) -> SourcePersistResult:
        del run_id
        stored = await session.get(Source, source.id)
        if stored is not None:
            _record_source_failure(stored, error)
        return SourcePersistResult(
            failed=1,
            errors=(
                {
                    "source": redact_string(source.name),
                    "error": redact_string(str(error)),
                },
            ),
        )

    async def finish_run(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        stats: dict[str, Any],
    ) -> None:
        status = "partial" if stats["failed"] else "succeeded"
        await IngestionRepository(session).finish_run(run_id, status=status, stats=stats)

    async def run(
        self,
        *,
        session: AsyncSession,
        platforms: list[str] | None,
        source_ids: list[str] | None,
        trigger: str,
    ) -> dict[str, Any]:
        async with _transaction(session, "prepare"):
            prepared = await self.prepare_run(
                session,
                platforms=platforms,
                source_ids=source_ids,
                trigger=trigger,
            )

        stats: dict[str, Any] = {
            "checked": 0,
            "fetched": 0,
            "skipped": 0,
            "failed": 0,
            "items": 0,
            "media_candidates": 0,
            "errors": [],
        }
        for source in prepared.sources:
            stats["checked"] += 1
            if _has_transaction(session):
                raise RuntimeError("Database transaction remained active before source fetch")
            try:
                batch = await self.fetch_source(source)
                await self._after_fetch(source, batch)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - source failures do not abort the run
                async with _transaction(session, f"failure:{source.name}"):
                    persisted = await self.record_source_failure(
                        session,
                        run_id=prepared.run_id,
                        source=source,
                        error=exc,
                    )
            else:
                try:
                    async with _transaction(session, f"persist:{source.name}"):
                        persisted = await self.persist_source(session, run_id=prepared.run_id, batch=batch)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - persist failures remain source-scoped
                    async with _transaction(session, f"failure:{source.name}"):
                        persisted = await self.record_source_failure(
                            session,
                            run_id=prepared.run_id,
                            source=source,
                            error=exc,
                        )
            self._merge_result(stats, persisted)
            if persisted.processing_failure is not None:
                failure = persisted.processing_failure
                async with _transaction(session, f"failure:{source.name}"):
                    classified = await self.record_source_failure(
                        session,
                        run_id=prepared.run_id,
                        source=source,
                        error=RuntimeError(failure.message),
                    )
                self._merge_result(stats, classified)

        async with _transaction(session, "finish"):
            safe_stats = _sanitized_stats(stats)
            await self.finish_run(
                session,
                run_id=prepared.run_id,
                stats=safe_stats,
            )
        return safe_stats

    async def _after_fetch(self, source: PreparedSource, batch: FetchedSourceBatch) -> None:
        del source, batch
        await asyncio.sleep(0)

    @staticmethod
    def _merge_result(stats: dict[str, Any], result: SourcePersistResult) -> None:
        stats["fetched"] += result.fetched
        stats["skipped"] += result.skipped
        stats["failed"] += result.failed
        stats["items"] += result.items
        stats["media_candidates"] += result.media_candidates
        stats["errors"].extend(result.errors)


class _PersistedResponse:
    def __init__(self, batch: FetchedSourceBatch) -> None:
        self.status_code = batch.http_status
        self.headers = batch.headers
