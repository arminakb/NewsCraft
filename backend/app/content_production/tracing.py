from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.content_production.idempotency import artifact_id
from app.content_production.repository import ContentProductionRepository
from app.db.models import (
    ArticleExtractionResult,
    CandidateShortlist,
    ContentProductionRequest,
    ContentProductionRun,
    ContentSufficiencyReport,
    DraftQualityReport,
    EditorialBrief,
    TelegramDispatchRequest,
    TelegramDraft,
    TelegramPostPackage,
    VisualBrief,
    WebEnrichmentResult,
    WorkflowEvent,
)

EventHandler = Callable[[WorkflowEvent], Awaitable[None]]

_SECRET_KEYS = {
    "apikey",
    "api_key",
    "auth",
    "authorization",
    "client_secret",
    "cookie",
    "credentials",
    "passwd",
    "password",
    "private_key",
    "provider_key",
    "proxy_authorization",
    "session",
    "session_id",
    "sessionid",
    "set_cookie",
    "x_api_key",
}
_SECRET_SUFFIXES = ("_credential", "_credentials", "_password", "_secret", "_token")
_LARGE_TEXT_KEYS = {"body", "content", "html", "prompt", "raw_text", "text"}
_SENSITIVE_VALUE_KEYS = {
    "configuration",
    "environment",
    "headers",
    "prompt",
    "provider_payload",
    "provider_request",
    "provider_response",
}
_ARTIFACT_SPECS = {
    "content_sufficiency": (ContentSufficiencyReport, "content_sufficiency_report", None),
    "article_extraction": (ArticleExtractionResult, "article_extraction_result", None),
    "web_enrichment": (WebEnrichmentResult, "web_enrichment_result", None),
    "editorial_brief_creation": (EditorialBrief, "editorial_brief", None),
    "telegram_draft_generation": (TelegramDraft, "telegram_draft", "brief_id"),
    "draft_quality_check": (DraftQualityReport, "draft_quality_report", "draft_id"),
    "media_resolution": (VisualBrief, "visual_brief", None),
    "telegram_package_creation": (TelegramPostPackage, "telegram_post_package", "draft_id"),
    "dispatch_handoff": (TelegramDispatchRequest, "telegram_dispatch_request", "package_id"),
}


class WorkflowTraceService:
    def __init__(self, session) -> None:
        self.session = session
        self.repository = ContentProductionRepository(session)

    def wrap(
        self,
        handler: EventHandler,
        *,
        step_name: str,
        service_name: str,
        additional_steps: tuple[str, ...] = (),
    ) -> EventHandler:
        async def traced_handler(event: WorkflowEvent) -> None:
            await self.execute(
                event,
                handler,
                step_name=step_name,
                service_name=service_name,
                additional_steps=additional_steps,
            )

        return traced_handler

    async def execute(
        self,
        event: WorkflowEvent,
        handler: EventHandler,
        *,
        step_name: str,
        service_name: str,
        additional_steps: tuple[str, ...] = (),
    ) -> None:
        production_run_id, request_id = await self._trace_owners(event)
        state_before = await self._aggregate_state(event)
        artifact_identity = self._artifact_identity(event, step_name)
        artifact_existed_before = bool(
            artifact_identity and await self.session.get(artifact_identity[0], artifact_identity[1]) is not None
        )
        trace = await self.repository.record_step_run(
            production_run_id=production_run_id,
            step_name=step_name,
            agent_name=service_name,
            input_snapshot_json=self._input_snapshot(event, request_id, production_run_id, state_before),
            status="running",
        )
        failure_phase = "domain_handler"
        try:
            async with self._handler_savepoint():
                await handler(event)
                failure_phase = "output_snapshot"
                output = await self._output_snapshot(
                    event,
                    step_name,
                    artifact_identity=artifact_identity,
                    artifact_reused=artifact_existed_before,
                )
                failure_phase = "trace_finalization"
                trace.status = "completed"
                trace.output_snapshot_json = output
                provider_metadata = output.get("provider_metadata") or {}
                trace.model_name = provider_metadata.get("model")
                trace.token_usage_json = {
                    key: provider_metadata[key]
                    for key in ("input_tokens", "output_tokens", "total_tokens")
                    if provider_metadata.get(key) is not None
                }
                trace.finished_at = datetime.now(UTC)
                await self.session.flush()
        except Exception as exc:
            trace.status = "failed"
            trace.error_message = _bounded_error(exc)
            trace.output_snapshot_json = {
                "state_after": await self._aggregate_state(event),
                "error_class": type(exc).__name__,
                "failure_phase": failure_phase,
            }
            trace.finished_at = datetime.now(UTC)
            await self.session.flush()
            raise

    @asynccontextmanager
    async def _handler_savepoint(self):
        begin_nested = getattr(self.session, "begin_nested", None)
        if begin_nested is None:
            yield
            return
        async with begin_nested():
            yield

    async def _trace_owners(self, event: WorkflowEvent) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        run_id = _event_uuid(event, "production_run_id", "content_production_run")
        request_id = _event_uuid(event, "request_id", "content_production_request")
        if run_id is not None:
            run = await self.session.get(ContentProductionRun, run_id)
            if run is not None:
                return run.id, run.request_id
        if request_id is not None:
            request = await self.session.get(ContentProductionRequest, request_id)
            if request is not None:
                return None, request.id
        return None, request_id

    def _input_snapshot(
        self,
        event: WorkflowEvent,
        request_id: uuid.UUID | None,
        production_run_id: uuid.UUID | None,
        state_before: str | None,
    ) -> dict:
        return {
            "event": {
                "event_id": str(event.event_id),
                "event_type": event.event_type,
                "correlation_id": str(event.correlation_id),
                "causation_id": str(event.causation_id) if event.causation_id else None,
                "attempt_count": event.attempt_count or 0,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": str(event.aggregate_id),
            },
            "request_id": str(request_id) if request_id else None,
            "production_run_id": str(production_run_id) if production_run_id else None,
            "state_before": state_before,
            "payload": sanitize_snapshot(event.payload),
        }

    async def _output_snapshot(
        self,
        event: WorkflowEvent,
        step_name: str,
        *,
        artifact_identity: tuple[type, uuid.UUID, str] | None = None,
        artifact_reused: bool = False,
    ) -> dict:
        emitted_rows = await self.session.scalars(
            select(WorkflowEvent).where(WorkflowEvent.causation_id == event.event_id)
        )
        emitted = [row for row in emitted_rows if row.causation_id == event.event_id]
        output: dict[str, Any] = {
            "state_after": await self._aggregate_state(event),
            "emitted_events": [
                {
                    "event_id": str(row.event_id),
                    "event_type": row.event_type,
                    "aggregate_id": str(row.aggregate_id),
                    "payload": sanitize_snapshot(row.payload),
                }
                for row in emitted[:20]
            ],
        }
        if artifact_identity is not None:
            artifact_model, canonical_id, discriminator = artifact_identity
            artifact = await self.session.get(artifact_model, canonical_id)
            if artifact is not None:
                output["artifact"] = {
                    "artifact_type": artifact_model.__name__,
                    "artifact_id": str(artifact.id),
                    "status": getattr(artifact, "status", None),
                    "reused": artifact_reused,
                    "version_discriminator": discriminator,
                }
                metadata = getattr(artifact, "generation_metadata_json", None) or getattr(
                    artifact, "evaluation_metadata_json", None
                )
                if metadata:
                    output["provider_metadata"] = sanitize_snapshot(metadata)
                if step_name == "content_sufficiency":
                    snapshot = artifact.input_snapshot_json or {}
                    output["sufficiency"] = {
                        "stage": snapshot.get("stage"),
                        "decision": artifact.status,
                        "extraction_result_id": snapshot.get("extraction_result_id"),
                        "enrichment_result_id": snapshot.get("enrichment_result_id"),
                        "reasons": artifact.reasons_json,
                    }
        if step_name == "candidate_selection":
            request_id = _event_uuid(event, "request_id", "content_production_request")
            if request_id is not None:
                candidates = await self.session.scalars(
                    select(CandidateShortlist).where(
                        CandidateShortlist.request_id == request_id,
                        CandidateShortlist.selection_execution_id == event.event_id,
                    )
                )
                selected = sorted(
                    (
                        candidate
                        for candidate in candidates
                        if candidate.request_id == request_id
                        and candidate.selection_execution_id == event.event_id
                    ),
                    key=lambda candidate: candidate.rank,
                )
                output["shortlist"] = {
                    "selection_execution_id": str(event.event_id),
                    "candidate_count": len(selected),
                    "candidate_ids": [str(candidate.id) for candidate in selected[:20]],
                    "content_item_ids": [str(candidate.content_item_id) for candidate in selected[:20]],
                    "ranks": [candidate.rank for candidate in selected[:20]],
                }
        return sanitize_snapshot(output)

    @staticmethod
    def _artifact_identity(event: WorkflowEvent, step_name: str) -> tuple[type, uuid.UUID, str] | None:
        spec = _ARTIFACT_SPECS.get(step_name)
        if spec is None:
            return None
        model, purpose, discriminator_key = spec
        discriminator = ""
        if discriminator_key is not None:
            value = event.payload.get(discriminator_key)
            if value is None:
                return None
            discriminator = str(value)
        return model, artifact_id(event.event_id, purpose, discriminator), discriminator

    async def _aggregate_state(self, event: WorkflowEvent) -> str | None:
        run_id = _event_uuid(event, "production_run_id", "content_production_run")
        if run_id is not None:
            run = await self.session.get(ContentProductionRun, run_id)
            return run.state if run is not None else None
        request_id = _event_uuid(event, "request_id", "content_production_request")
        if request_id is not None:
            request = await self.session.get(ContentProductionRequest, request_id)
            return request.status if request is not None else None
        return None


class HumanDecisionTraceService:
    def __init__(self, session) -> None:
        self.session = session
        self.repository = ContentProductionRepository(session)

    async def execute(
        self,
        operation: Callable[[], Awaitable[Any]],
        *,
        step_name: str,
        service_name: str,
        production_run_id: uuid.UUID | None,
        request_id: uuid.UUID | None,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        decision: str,
        input_snapshot: dict,
        output_snapshot: Callable[[Any], dict],
    ) -> Any:
        command_context = {
            "request_id": str(request_id) if request_id else None,
            "production_run_id": str(production_run_id) if production_run_id else None,
            "aggregate_type": aggregate_type,
            "aggregate_id": str(aggregate_id),
            "decision": decision,
            **input_snapshot,
        }
        trace = await self.repository.record_step_run(
            production_run_id=production_run_id,
            step_name=step_name,
            agent_name=service_name,
            input_snapshot_json=sanitize_snapshot(command_context),
            status="running",
        )
        failure_phase = "human_decision"
        try:
            async with self._savepoint():
                result = await operation()
                failure_phase = "trace_finalization"
                trace.status = "completed"
                trace.input_snapshot_json = sanitize_snapshot(command_context)
                trace.output_snapshot_json = sanitize_snapshot(output_snapshot(result))
                trace.finished_at = datetime.now(UTC)
                await self.session.flush()
        except Exception as exc:
            trace.status = "failed"
            trace.error_message = _bounded_error(exc)
            trace.output_snapshot_json = {
                "decision": decision,
                "error_class": type(exc).__name__,
                "failure_phase": failure_phase,
            }
            trace.finished_at = datetime.now(UTC)
            await self.session.flush()
            raise
        return result

    @asynccontextmanager
    async def _savepoint(self):
        begin_nested = getattr(self.session, "begin_nested", None)
        if begin_nested is None:
            yield
            return
        async with begin_nested():
            yield


def sanitize_snapshot(value: Any, *, key: str = "", depth: int = 0) -> Any:
    normalized_key = _normalize_key(key)
    if _is_secret_key(normalized_key):
        return "[REDACTED]"
    if normalized_key in _SENSITIVE_VALUE_KEYS:
        return _redacted_summary(value)
    if depth >= 5:
        return "[MAX_DEPTH]"
    if isinstance(value, dict):
        return {
            str(item_key)[:80]: sanitize_snapshot(item_value, key=str(item_key), depth=depth + 1)
            for item_key, item_value in list(value.items())[:30]
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_snapshot(item, key=key, depth=depth + 1) for item in list(value)[:20]]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        if _is_large_text_key(normalized_key) or len(value) > 512:
            return {
                "length": len(value),
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                "excerpt": value[:80],
            }
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:256]


def _event_uuid(event: WorkflowEvent, payload_key: str, aggregate_type: str) -> uuid.UUID | None:
    value = event.payload.get(payload_key)
    if value is None and event.aggregate_type == aggregate_type:
        return event.aggregate_id
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _bounded_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:400]}"


def _is_large_text_key(key: str) -> bool:
    return key in _LARGE_TEXT_KEYS or key.endswith(("_body", "_content", "_html", "_prompt", "_text"))


def _normalize_key(key: str) -> str:
    return re.sub(r"[\s_-]+", "_", key.casefold()).strip("_")


def _is_secret_key(key: str) -> bool:
    return key in _SECRET_KEYS or key.endswith(_SECRET_SUFFIXES)


def _redacted_summary(value: Any) -> dict:
    try:
        serialized = json.dumps(value, sort_keys=True, default=str, ensure_ascii=True)
    except (TypeError, ValueError):
        serialized = str(value)
    return {
        "redacted": True,
        "length": len(serialized),
        "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }
