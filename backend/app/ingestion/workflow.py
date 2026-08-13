from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.source_events import enqueue_source_item_created
from app.core.config import settings
from app.core.outbound_proxy import build_outbound_http_client
from app.core.redaction import redact_secrets, redact_string
from app.db.models import IngestRun, Source
from app.ingestion.repository import IngestionRepository, build_item_identities
from app.source_collections.models import IngestRunSourceSnapshot
from app.sources.registry import parser_for_source

DEFAULT_HEADERS = {"User-Agent": "NewsCraftBot/1.0"}


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
    collection_snapshot: bool = False


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


def _snapshot_source_record(source: IngestRunSourceSnapshot) -> PreparedSource:
    if source.source_id is None:
        raise ValueError(f"Ingest snapshot source {source.id} no longer has a source id")
    return PreparedSource(
        id=source.source_id,
        name=source.source_name,
        platform=source.platform,
        feed_url=source.feed_url,
        telegram_username=source.telegram_username,
        default_timezone=source.default_timezone or "UTC",
        etag=source.etag,
        last_modified=source.last_modified,
    )


@asynccontextmanager
async def _transaction(session: AsyncSession, label: str):
    begin: Any = session.begin
    try:
        context = begin(label)
    except TypeError:
        context = begin()
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
        ingest_run_id: str | None = None,
    ) -> PreparedIngestionRun:
        if ingest_run_id is not None:
            try:
                run_id = UUID(str(ingest_run_id))
            except ValueError:
                raise ValueError("ingest_run_id must be a UUID") from None
            run = await session.get(IngestRun, run_id)
            if run is None or run.source_collection_id is None:
                raise ValueError("collection ingest run not found")
            snapshots = list(
                await session.scalars(
                    select(IngestRunSourceSnapshot)
                    .where(IngestRunSourceSnapshot.ingest_run_id == run.id)
                    .order_by(IngestRunSourceSnapshot.position)
                )
            )
            if not snapshots:
                raise ValueError("collection ingest run has no source snapshot")
            run.status = "running"
            if run.started_at is None:
                run.started_at = datetime.now(UTC)
            await session.flush()
            return PreparedIngestionRun(
                run_id=run.id,
                sources=tuple(_snapshot_source_record(snapshot) for snapshot in snapshots),
                collection_snapshot=True,
            )
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
                    source_item, created = await _upsert_source_item_with_created(
                        repository,
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
                    if created:
                        await enqueue_source_item_created(
                            session,
                            source_item_id=source_item.id,
                            source_id=source.id,
                            platform=source.platform,
                            content_item_id=content_item.id,
                            ingestion_run_id=run_id,
                            occurred_at=datetime.now(UTC),
                        )
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

    async def abort_run(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        stats: dict[str, Any],
        error: str,
    ) -> None:
        """Write the terminal `failed` state for a run that could not complete."""
        await IngestionRepository(session).finish_run(run_id, status="failed", stats=stats, error=error)

    async def _abort_run_quietly(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        stats: dict[str, Any],
        error: Exception,
    ) -> None:
        """Best-effort terminal write for a run whose loop raised.

        Without it the row stays `running` forever: the partial unique index
        `uq_ingest_runs_active_source_collection` then rejects every later
        snapshot for the same collection, so a single escaping exception wedges
        the collection permanently. The original exception must still surface,
        so every failure of this write is swallowed.
        """
        try:
            if _has_transaction(session):
                await session.rollback()
            async with _transaction(session, "abort"):
                await self.abort_run(
                    session,
                    run_id=run_id,
                    stats=_sanitized_stats(stats),
                    error=str(error),
                )
        except Exception:  # noqa: BLE001 - the original failure must surface unchanged
            with suppress(Exception):
                await session.rollback()

    async def _fetch_one(
        self,
        source: PreparedSource,
    ) -> tuple[PreparedSource, FetchedSourceBatch | None, Exception | None]:
        try:
            batch = await self.fetch_source(source)
            await self._after_fetch(source, batch)
            return source, batch, None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - source failures remain source-scoped
            return source, None, exc

    async def _record_collection_progress(
        self,
        session: AsyncSession,
        *,
        prepared: PreparedIngestionRun,
        source: PreparedSource,
        stats: dict[str, Any],
        failed: bool,
        skipped: bool,
        error: str | None,
        on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        if not prepared.collection_snapshot:
            return
        now = datetime.now(UTC)
        await session.execute(
            update(IngestRunSourceSnapshot)
            .where(
                IngestRunSourceSnapshot.ingest_run_id == prepared.run_id,
                IngestRunSourceSnapshot.source_id == source.id,
            )
            .values(
                status="failed" if failed else ("skipped" if skipped else "succeeded"),
                started_at=now,
                completed_at=now,
                error=redact_string(error) if error else None,
            )
        )
        await session.execute(
            update(IngestRun)
            .where(IngestRun.id == prepared.run_id)
            .values(
                processed_count=stats["checked"],
                success_count=max(0, stats["checked"] - stats["failed"]),
                failure_count=stats["failed"],
                stats=_sanitized_stats(stats),
            )
        )
        if on_progress is not None:
            try:
                await on_progress(
                    {
                        "processed_count": stats["checked"],
                        "source_count": len(prepared.sources),
                        "success_count": max(0, stats["checked"] - stats["failed"]),
                        "failure_count": stats["failed"],
                    }
                )
            except Exception:  # noqa: BLE001 - progress reporting cannot stop ingestion
                pass

    async def run(
        self,
        *,
        session: AsyncSession,
        platforms: list[str] | None,
        source_ids: list[str] | None,
        trigger: str,
        ingest_run_id: str | None = None,
        on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        prepare_kwargs: dict[str, Any] = {
            "platforms": platforms,
            "source_ids": source_ids,
            "trigger": trigger,
        }
        if ingest_run_id is not None:
            prepare_kwargs["ingest_run_id"] = ingest_run_id
        async with _transaction(session, "prepare"):
            prepared = await self.prepare_run(session, **prepare_kwargs)

        stats: dict[str, Any] = {
            "checked": 0,
            "fetched": 0,
            "skipped": 0,
            "failed": 0,
            "items": 0,
            "media_candidates": 0,
            "errors": [],
        }
        source_iterator = iter(prepared.sources)
        pending: set[asyncio.Task[tuple[PreparedSource, FetchedSourceBatch | None, Exception | None]]] = set()
        concurrency = min(max(1, settings.ingestion_source_concurrency), max(1, len(prepared.sources)))
        for _ in range(concurrency):
            try:
                source = next(source_iterator)
            except StopIteration:
                break
            pending.add(asyncio.create_task(self._fetch_one(source), name=f"ingest-fetch:{source.id}"))

        try:
            while pending:
                completed, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in completed:
                    source, batch, fetch_error = task.result()
                    if _has_transaction(session):
                        raise RuntimeError("Database transaction remained active before source persistence")
                    stats["checked"] += 1
                    persisted: SourcePersistResult
                    progress_error: str | None = None
                    if fetch_error is not None:
                        progress_error = str(fetch_error)
                        async with _transaction(session, f"failure:{source.name}"):
                            persisted = await self.record_source_failure(
                                session,
                                run_id=prepared.run_id,
                                source=source,
                                error=fetch_error,
                            )
                    else:
                        assert batch is not None
                        try:
                            async with _transaction(session, f"persist:{source.name}"):
                                persisted = await self.persist_source(session, run_id=prepared.run_id, batch=batch)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:  # noqa: BLE001 - persist failures remain source-scoped
                            progress_error = str(exc)
                            async with _transaction(session, f"failure:{source.name}"):
                                persisted = await self.record_source_failure(
                                    session,
                                    run_id=prepared.run_id,
                                    source=source,
                                    error=exc,
                                )
                    self._merge_result(stats, persisted)
                    if persisted.errors and progress_error is None:
                        progress_error = str(persisted.errors[0].get("error") or "source failed")
                    if persisted.processing_failure is not None:
                        failure = persisted.processing_failure
                        progress_error = failure.message
                        async with _transaction(session, f"failure:{source.name}"):
                            classified = await self.record_source_failure(
                                session,
                                run_id=prepared.run_id,
                                source=source,
                                error=RuntimeError(failure.message),
                            )
                        self._merge_result(stats, classified)

                    source_failed = bool(fetch_error or persisted.failed or persisted.processing_failure)
                    if prepared.collection_snapshot:
                        async with _transaction(session, f"progress:{source.name}"):
                            await self._record_collection_progress(
                                session,
                                prepared=prepared,
                                source=source,
                                stats=stats,
                                failed=source_failed,
                                skipped=bool(persisted.skipped),
                                error=progress_error,
                                on_progress=on_progress,
                            )

                    try:
                        next_source = next(source_iterator)
                    except StopIteration:
                        next_source = None
                    if next_source is not None:
                        pending.add(
                            asyncio.create_task(
                                self._fetch_one(next_source),
                                name=f"ingest-fetch:{next_source.id}",
                            )
                        )
        except Exception as exc:  # noqa: BLE001 - the run row must never stay `running`
            await self._abort_run_quietly(session, run_id=prepared.run_id, stats=stats, error=exc)
            raise
        finally:
            if pending:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

        try:
            async with _transaction(session, "finish"):
                safe_stats = _sanitized_stats(stats)
                await self.finish_run(
                    session,
                    run_id=prepared.run_id,
                    stats=safe_stats,
                )
        except Exception as exc:  # noqa: BLE001 - the run row must never stay `running`
            await self._abort_run_quietly(session, run_id=prepared.run_id, stats=stats, error=exc)
            raise
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


def _build_http_client() -> httpx.AsyncClient:
    return build_outbound_http_client(timeout=20.0)


async def _upsert_source_item_with_created(
    repository: IngestionRepository,
    **kwargs: Any,
) -> tuple[Any, bool]:
    method = getattr(repository, "upsert_source_item_with_created", None)
    if callable(method):
        return await method(**kwargs)
    # Small repository doubles used by ingestion unit tests predate the
    # insert/update signal. They still exercise persistence, but cannot emit
    # a source-item event without the real repository boundary.
    return await repository.upsert_source_item(**kwargs), False


def _source_request_url(source: Source) -> str:
    if source.platform in {"rss", "atom"} and source.feed_url:
        return source.feed_url
    if source.platform == "telegram_public" and source.telegram_username:
        return f"https://t.me/s/{source.telegram_username}"
    raise ValueError(f"Source {source.name} is missing fetch URL data")


def _request_headers(source: Source) -> dict[str, str]:
    headers = dict(DEFAULT_HEADERS)
    if source.etag:
        headers["If-None-Match"] = source.etag
    if source.last_modified:
        headers["If-Modified-Since"] = source.last_modified
    return headers


def _payload_kind(source: Source) -> str:
    if source.platform in {"rss", "atom"}:
        return "feed_xml"
    if source.platform == "telegram_public":
        return "telegram_html"
    return "raw"


def _parse_source_payload(source: Source, raw_text: str, request_url: str):
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


def _record_source_success(
    source: Source,
    response: httpx.Response,
    *,
    parse_count: int,
    suitable_count: int,
    media_count: int,
    parser_warnings: list[str],
) -> None:
    now = datetime.now(UTC)
    source.last_fetch_at = now
    source.last_http_status = response.status_code
    source.last_success_at = now
    source.last_parse_count = parse_count
    source.last_suitable_count = suitable_count
    source.last_media_count = media_count

    error_type, error_message = _source_quality_issue(parse_count, suitable_count, parser_warnings)
    if _source_is_disabled(source):
        source.health_status = "disabled"
        return
    if error_type:
        source.health_status = "degraded"
        source.last_failure_at = now
        source.failure_count = int(source.failure_count or 0) + 1
        source.last_error_type = redact_string(error_type)
        source.last_error_message = redact_string(error_message) if error_message is not None else None
        return

    source.health_status = "healthy"
    source.failure_count = 0
    source.last_error_type = None
    source.last_error_message = None


def _record_source_not_modified(source: Source, response: httpx.Response) -> None:
    now = datetime.now(UTC)
    source.last_fetch_at = now
    source.last_http_status = response.status_code
    source.last_success_at = now
    if _source_is_disabled(source):
        source.health_status = "disabled"


def _record_source_failure(
    source: Source,
    error: Exception,
    *,
    http_status: int | None = None,
    error_type: str | None = None,
) -> None:
    now = datetime.now(UTC)
    source.last_fetch_at = now
    source.last_failure_at = now
    source.failure_count = int(source.failure_count or 0) + 1
    source.last_http_status = http_status
    source.last_error_type = redact_string(error_type or error.__class__.__name__)
    source.last_error_message = redact_string(str(error))
    source.health_status = "disabled" if _source_is_disabled(source) else "broken"


def _source_quality_issue(
    parse_count: int,
    suitable_count: int,
    parser_warnings: list[str],
) -> tuple[str | None, str | None]:
    bozo_warnings = [warning for warning in parser_warnings if warning.startswith("bozo_feed:")]
    if bozo_warnings:
        return "malformed_feed", "; ".join(bozo_warnings)
    if parse_count == 0:
        return "zero_parsed_items", "Parser returned no items."
    if suitable_count == 0:
        return "zero_suitable_items", "Parser returned no items with usable text."
    return None, None


def _is_suitable_item(item) -> bool:
    return bool((item.content_text or "").strip() and (item.title or "").strip())


def _source_is_disabled(source: Source) -> bool:
    return not source.active or bool(source.disabled_reason)


def _sanitized_stats(stats: dict[str, Any]) -> dict[str, Any]:
    sanitized = redact_secrets(stats)
    return sanitized if isinstance(sanitized, dict) else {}
