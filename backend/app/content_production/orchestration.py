from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.content_production.events import WorkflowEventType
from app.db.models import WorkflowEvent

EventHandler = Callable[[WorkflowEvent], Awaitable[None]]


class UnknownWorkflowEventError(LookupError):
    pass


class OutboxStore(Protocol):
    async def claim_pending_events(self, *, limit: int) -> list[WorkflowEvent]: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...


class EventDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[WorkflowEventType, EventHandler] = {}

    @property
    def registered_event_types(self) -> frozenset[WorkflowEventType]:
        return frozenset(self._handlers)

    def register(self, event_type: WorkflowEventType | str, handler: EventHandler) -> None:
        typed_event = WorkflowEventType(event_type)
        if typed_event in self._handlers:
            raise ValueError(f"handler already registered for {typed_event.value}")
        self._handlers[typed_event] = handler

    async def dispatch(self, event: WorkflowEvent) -> None:
        try:
            event_type = WorkflowEventType(event.event_type)
        except ValueError as exc:
            raise UnknownWorkflowEventError(f"unknown workflow event type: {event.event_type}") from exc

        handler = self._handlers.get(event_type)
        if handler is None:
            raise UnknownWorkflowEventError(f"no handler registered for {event_type.value}")
        await handler(event)


class WorkflowEventWorker:
    def __init__(
        self,
        store: OutboxStore,
        dispatcher: EventDispatcher,
        *,
        max_attempts: int = 3,
        retry_delay: timedelta = timedelta(seconds=30),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_delay < timedelta(0):
            raise ValueError("retry_delay cannot be negative")
        self.store = store
        self.dispatcher = dispatcher
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay

    async def run_once(self, *, limit: int = 100) -> int:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        events = await self.store.claim_pending_events(limit=limit)
        for event in events:
            if event.status != "processing":
                continue
            await self._process(event)
        await self.store.flush()
        await self.store.commit()
        return len(events)

    async def poll(
        self,
        *,
        limit: int = 100,
        interval: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        if interval < 0:
            raise ValueError("interval cannot be negative")

        while stop_event is None or not stop_event.is_set():
            processed = await self.run_once(limit=limit)
            if processed:
                continue
            if stop_event is None:
                await asyncio.sleep(interval)
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                pass

    async def _process(self, event: WorkflowEvent) -> None:
        event.attempt_count = (event.attempt_count or 0) + 1
        try:
            await self.dispatcher.dispatch(event)
        except Exception as exc:
            event.last_error = str(exc)
            event.processed_at = None
            if event.attempt_count >= self.max_attempts:
                event.status = "failed"
            else:
                event.status = "pending"
                event.available_at = datetime.now(UTC) + self.retry_delay
        else:
            event.status = "processed"
            event.last_error = None
            event.processed_at = datetime.now(UTC)


def build_core_event_dispatcher(session, **handler_options) -> EventDispatcher:
    from app.content_production.handlers import build_core_event_dispatcher as build_dispatcher

    return build_dispatcher(session, **handler_options)


def next_event_types(event_type: WorkflowEventType | str, payload: dict) -> list[WorkflowEventType]:
    typed_event = WorkflowEventType(event_type)
    if typed_event in {WorkflowEventType.ARTICLE_EXTRACTED, WorkflowEventType.WEB_ENRICHED}:
        return [WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED]
    if typed_event != WorkflowEventType.CONTENT_SUFFICIENCY_CHECKED:
        return []

    status = payload.get("status")
    if status == "sufficient":
        return [WorkflowEventType.EDITORIAL_BRIEF_REQUESTED]
    if status in {"partial", "insufficient"}:
        if not payload.get("extraction_attempted"):
            return [WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED]
        if not payload.get("enrichment_attempted"):
            return [WorkflowEventType.WEB_ENRICHMENT_REQUESTED]
        return [WorkflowEventType.PRODUCTION_RUN_FAILED]
    return []
