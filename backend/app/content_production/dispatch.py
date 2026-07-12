from __future__ import annotations

import uuid

from app.content_production.idempotency import artifact_id, create_or_get_artifact
from app.content_production.repository import ContentProductionRepository
from app.content_production.states import WorkflowState
from app.db.models import ContentProductionRun, TelegramDispatchRequest, TelegramPostPackage


class TelegramDispatchService:
    def __init__(self, session, *, bot_token: str | None = None, channel_id: str | None = None):
        self.session = session
        self.bot_token = bot_token
        self.channel_id = channel_id

    async def create_dispatch_request(
        self,
        *,
        run: ContentProductionRun,
        package: TelegramPostPackage,
        command_id: uuid.UUID | None = None,
    ) -> TelegramDispatchRequest:
        dispatch_id = artifact_id(command_id or package.id, "telegram_dispatch_request", str(package.id))

        async def create() -> TelegramDispatchRequest:
            if run.state not in {
                WorkflowState.FINAL_APPROVED.value,
                WorkflowState.DISPATCH_FAILED.value,
            } or package.approval_status != "approved":
                raise ValueError("final package approval is required before dispatch handoff")

            status = "pending" if self._configured else "blocked"
            blocked_reason = None if self._configured else "telegram_dispatch_not_configured"
            dispatch = TelegramDispatchRequest(
                id=dispatch_id,
                production_run_id=run.id,
                package_id=package.id,
                status=status,
                dispatch_payload_json={
                    "platform": "telegram",
                    "package_id": str(package.id),
                    "post_text": package.package_json.get("post_text"),
                    "source_links": package.package_json.get("source_links", []),
                    "media": package.package_json.get("media", {}),
                },
                blocked_reason=blocked_reason,
            )
            self.session.add(dispatch)
            await self.session.flush()

            repository = ContentProductionRepository(self.session)
            await repository.transition_run(run, WorkflowState.DISPATCH_PENDING, current_step="dispatch_handoff")
            if status == "blocked":
                await repository.transition_run(run, WorkflowState.DISPATCH_FAILED, current_step="dispatch_handoff")
                run.failure_reason = blocked_reason
            return dispatch

        return await create_or_get_artifact(self.session, TelegramDispatchRequest, dispatch_id, create)

    @property
    def _configured(self) -> bool:
        return bool(self.bot_token and self.channel_id)
