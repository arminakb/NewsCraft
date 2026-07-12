from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.content_production.events import WorkflowEventType
from app.content_production.idempotency import artifact_id, create_or_get_artifact
from app.content_production.states import WorkflowState, require_valid_transition
from app.db.models import (
    AgentStepRun,
    CandidateShortlist,
    ContentProductionRequest,
    ContentProductionRun,
    WorkflowEvent,
)


class WorkflowEventConsistencyError(ValueError):
    """Raised when one deterministic event ID describes different logical events."""


class ContentProductionRepository:
    def __init__(self, session):
        self.session = session

    async def create_request(
        self,
        *,
        topic: str | None = None,
        platform: str = "telegram",
        language: str = "fa",
        tone: str | None = None,
        audience: str | None = None,
        max_candidates: int = 10,
        require_rewrite_ready: bool = True,
        require_media: bool = False,
        constraints_json: dict | None = None,
        created_by: str | None = None,
    ) -> ContentProductionRequest:
        request = ContentProductionRequest(
            id=uuid.uuid4(),
            topic=topic,
            platform=platform,
            language=language,
            tone=tone,
            audience=audience,
            max_candidates=max_candidates,
            require_rewrite_ready=require_rewrite_ready,
            require_media=require_media,
            status=WorkflowState.CREATED.value,
            constraints_json=constraints_json or {},
            created_by=created_by,
        )
        self.session.add(request)
        await self.session.flush()
        return request

    async def add_shortlist_candidate(
        self,
        *,
        request_id: uuid.UUID,
        selection_execution_id: uuid.UUID,
        content_item_id: uuid.UUID,
        rank: int,
        score: Decimal | int = 0,
        selection_reason_json: dict | None = None,
        risk_flags_json: list | None = None,
        source_snapshot_json: dict | None = None,
        command_id: uuid.UUID | None = None,
    ) -> CandidateShortlist:
        candidate_id = artifact_id(
            command_id or request_id,
            "candidate_shortlist",
            str(content_item_id),
        )

        async def create() -> CandidateShortlist:
            candidate = CandidateShortlist(
                id=candidate_id,
                request_id=request_id,
                selection_execution_id=selection_execution_id,
                content_item_id=content_item_id,
                rank=rank,
                score=Decimal(score),
                selection_reason_json=selection_reason_json or {},
                risk_flags_json=risk_flags_json or [],
                source_snapshot_json=source_snapshot_json or {},
                approval_status="pending",
            )
            self.session.add(candidate)
            await self.session.flush()
            return candidate

        return await create_or_get_artifact(self.session, CandidateShortlist, candidate_id, create)

    async def create_run(
        self,
        *,
        request_id: uuid.UUID,
        content_item_id: uuid.UUID,
        platform: str = "telegram",
        initial_state: WorkflowState | str = WorkflowState.CREATED,
        command_id: uuid.UUID | None = None,
    ) -> ContentProductionRun:
        run_id = artifact_id(command_id or request_id, "content_production_run", str(content_item_id))

        async def create() -> ContentProductionRun:
            run = ContentProductionRun(
                id=run_id,
                request_id=request_id,
                content_item_id=content_item_id,
                platform=platform,
                state=WorkflowState(initial_state).value,
            )
            self.session.add(run)
            await self.session.flush()
            return run

        return await create_or_get_artifact(self.session, ContentProductionRun, run_id, create)

    async def list_requests(self, *, limit: int = 100) -> list[ContentProductionRequest]:
        rows = await self.session.scalars(
            select(ContentProductionRequest).order_by(ContentProductionRequest.created_at.desc()).limit(limit)
        )
        return list(rows)

    async def list_shortlist(self, request_id: uuid.UUID) -> list[CandidateShortlist]:
        rows = await self.session.scalars(
            select(CandidateShortlist)
            .where(CandidateShortlist.request_id == request_id)
            .order_by(CandidateShortlist.rank)
        )
        return list(rows)

    async def list_shortlist_execution(
        self,
        request_id: uuid.UUID,
        selection_execution_id: uuid.UUID,
    ) -> list[CandidateShortlist]:
        rows = await self.session.scalars(
            select(CandidateShortlist)
            .where(
                CandidateShortlist.request_id == request_id,
                CandidateShortlist.selection_execution_id == selection_execution_id,
            )
            .order_by(CandidateShortlist.rank)
        )
        return [
            row
            for row in rows
            if row.request_id == request_id and row.selection_execution_id == selection_execution_id
        ]

    async def transition_run(
        self,
        run: ContentProductionRun,
        to_state: WorkflowState | str,
        *,
        current_step: str | None = None,
        failure_reason: str | None = None,
    ) -> ContentProductionRun:
        target = WorkflowState(to_state)
        require_valid_transition(run.state, target)
        run.state = target.value
        run.current_step = current_step
        if failure_reason is not None:
            run.failure_reason = failure_reason
        await self.session.flush()
        return run

    async def record_step_run(
        self,
        *,
        production_run_id: uuid.UUID | None,
        step_name: str,
        agent_name: str,
        input_snapshot_json: dict | None = None,
        output_snapshot_json: dict | None = None,
        status: str = "running",
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        model_name: str | None = None,
        token_usage_json: dict | None = None,
    ) -> AgentStepRun:
        step = AgentStepRun(
            id=uuid.uuid4(),
            production_run_id=production_run_id,
            step_name=step_name,
            agent_name=agent_name,
            input_snapshot_json=input_snapshot_json or {},
            output_snapshot_json=output_snapshot_json or {},
            status=status,
            error_message=error_message,
            started_at=started_at or datetime.now(UTC),
            finished_at=finished_at,
            model_name=model_name,
            token_usage_json=token_usage_json or {},
        )
        self.session.add(step)
        await self.session.flush()
        return step

    async def enqueue_event_once(
        self,
        *,
        event_id: uuid.UUID,
        event_type: WorkflowEventType | str,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        correlation_id: uuid.UUID,
        payload: dict | None = None,
        causation_id: uuid.UUID | None = None,
        available_at: datetime | None = None,
    ) -> tuple[WorkflowEvent, bool]:
        existing = await self.session.get(WorkflowEvent, event_id)
        if existing is not None:
            expected = {
                "event_type": WorkflowEventType(event_type).value,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "correlation_id": correlation_id,
                "causation_id": causation_id,
                "payload": payload or {},
            }
            actual = {key: getattr(existing, key) for key in expected}
            if actual != expected:
                raise WorkflowEventConsistencyError(
                    f"workflow event {event_id} already exists with conflicting identity or payload"
                )
            return existing, False

        event = WorkflowEvent(
            event_id=event_id,
            event_type=WorkflowEventType(event_type).value,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload or {},
            status="pending",
            attempt_count=0,
            available_at=available_at or datetime.now(UTC),
        )
        self.session.add(event)
        await self.session.flush()
        return event, True

    async def get_pending_events(self, *, limit: int = 100) -> list[WorkflowEvent]:
        rows = await self.session.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.status == "pending", WorkflowEvent.available_at <= datetime.now(UTC))
            .order_by(WorkflowEvent.occurred_at)
            .limit(limit)
        )
        return list(rows)

    async def claim_pending_events(self, *, limit: int = 100) -> list[WorkflowEvent]:
        rows = await self.session.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.status == "pending", WorkflowEvent.available_at <= datetime.now(UTC))
            .order_by(WorkflowEvent.occurred_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = list(rows)
        for event in events:
            event.status = "processing"
        await self.session.flush()
        return events

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()
