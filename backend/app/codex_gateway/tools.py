from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.telegram_schemas import TelegramDestinationOut
from app.automations.models import AutomationRoute
from app.codex_gateway.models import CodexConnection
from app.codex_gateway.schemas import CodexConnectionOut
from app.codex_gateway.service import connection_out
from app.core.config import Settings, settings
from app.generation.models import BrandProfile, PromptTemplate, PromptTemplateVersion
from app.jobs.models import WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobOut
from app.jobs.types import JobStatus
from app.llm_providers.schemas import LLMProviderOut
from app.llm_providers.service import LLMProviderService, provider_out
from app.operations.health import ReadinessService, ReadinessSnapshot
from app.publishing.telegram.lifecycle import (
    TelegramLifecycleService,
    destination_out,
)
from app.security.auth import SecurityPrincipal


class ToolResourceNotFound(RuntimeError):
    pass


class EditorialProfilesSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    default_configured: bool


class PromptGovernanceSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purposes: int
    active_versions: int


class LLMProvidersSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    enabled: int
    healthy: int
    generation_ready: int
    research_ready: int


class TelegramDestinationsSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    enabled: int
    healthy: int
    administrator: int


class AutomationsSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    enabled: int
    paused: int


class JobsSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: int
    attention: int


class ContentSettingsSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    editorial_profiles: EditorialProfilesSummaryOut
    llm_providers: LLMProvidersSummaryOut
    codex_connection: CodexConnectionOut
    telegram_destinations: TelegramDestinationsSummaryOut
    prompt_governance: PromptGovernanceSummaryOut
    automations: AutomationsSummaryOut
    jobs: JobsSummaryOut


class AutomationSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    name: str
    source_id: UUID
    destination_id: UUID
    enabled: bool
    paused_at: datetime | None
    publishing_policy: str
    research_mode: str
    last_polled_at: datetime | None
    next_poll_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CodexToolService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        principal: SecurityPrincipal,
        config: Settings = settings,
    ) -> None:
        self.session = session
        self.principal = principal
        self.config = config

    async def get_status(self) -> ReadinessSnapshot:
        return await ReadinessService(self.session, config=self.config).snapshot()

    async def get_content_settings_summary(
        self,
        connection: CodexConnection,
    ) -> ContentSettingsSummaryOut:
        providers = await self.list_llm_providers()
        destinations = await self.list_telegram_destinations()
        automations = await self.list_automations()
        profile_total = await self._count(BrandProfile)
        default_profiles = await self._count(BrandProfile, BrandProfile.is_default.is_(True))
        prompt_total = await self._count(PromptTemplate)
        active_prompt_versions = await self._count(
            PromptTemplateVersion,
            PromptTemplateVersion.is_active.is_(True),
        )
        active_jobs = await self._count(
            WorkflowJob,
            WorkflowJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
        )
        attention_jobs = await self._count(
            WorkflowJob,
            WorkflowJob.status.in_((JobStatus.FAILED, JobStatus.NEEDS_REVIEW)),
        )
        return ContentSettingsSummaryOut(
            generated_at=datetime.now(UTC),
            editorial_profiles=EditorialProfilesSummaryOut(
                total=profile_total,
                default_configured=default_profiles > 0,
            ),
            llm_providers=LLMProvidersSummaryOut(
                total=len(providers),
                enabled=sum(item.enabled for item in providers),
                healthy=sum(item.health_status == "healthy" for item in providers),
                generation_ready=sum(item.generation_ready for item in providers),
                research_ready=sum(item.research_ready for item in providers),
            ),
            codex_connection=connection_out(
                connection,
                now=datetime.now(UTC),
                config=self.config,
            ),
            telegram_destinations=TelegramDestinationsSummaryOut(
                total=len(destinations),
                enabled=sum(item.enabled for item in destinations),
                healthy=sum(item.health_status == "healthy" for item in destinations),
                administrator=sum(
                    item.administrator_status == "administrator"
                    for item in destinations
                ),
            ),
            prompt_governance=PromptGovernanceSummaryOut(
                purposes=prompt_total,
                active_versions=active_prompt_versions,
            ),
            automations=AutomationsSummaryOut(
                total=len(automations),
                enabled=sum(item.enabled for item in automations),
                paused=sum(item.paused_at is not None for item in automations),
            ),
            jobs=JobsSummaryOut(active=active_jobs, attention=attention_jobs),
        )

    async def list_llm_providers(self) -> list[LLMProviderOut]:
        service = LLMProviderService(
            self.session,
            principal=self.principal,
            config=self.config,
        )
        return [provider_out(provider) for provider in await service.list()]

    async def get_llm_provider_status(self, provider_id: UUID) -> LLMProviderOut:
        service = LLMProviderService(
            self.session,
            principal=self.principal,
            config=self.config,
        )
        provider = await service.get(provider_id)
        if provider is None:
            raise ToolResourceNotFound("llm_provider_not_found")
        return provider_out(provider)

    async def list_telegram_destinations(self) -> list[TelegramDestinationOut]:
        service = TelegramLifecycleService(self.session, principal=self.principal)
        return [
            await destination_out(self.session, destination)
            for destination in await service.list_destinations()
        ]

    async def get_telegram_destination_status(
        self,
        destination_id: UUID,
    ) -> TelegramDestinationOut:
        service = TelegramLifecycleService(self.session, principal=self.principal)
        destination = await service.get_destination(destination_id)
        if destination is None:
            raise ToolResourceNotFound("telegram_destination_not_found")
        return await destination_out(self.session, destination)

    async def list_automations(self) -> list[AutomationSummaryOut]:
        routes = list(
            await self.session.scalars(
                select(AutomationRoute).order_by(AutomationRoute.name)
            )
        )
        return [AutomationSummaryOut.model_validate(route) for route in routes]

    async def get_job_status(self, job_id: UUID) -> JobOut:
        job = await JobRepository(self.session).get_job(job_id)
        if job is None:
            raise ToolResourceNotFound("job_not_found")
        return JobOut.model_validate(job)

    async def _count(self, model, *criteria) -> int:
        statement = select(func.count()).select_from(model)
        for criterion in criteria:
            statement = statement.where(criterion)
        return int(await self.session.scalar(statement) or 0)


__all__ = [
    "AutomationSummaryOut",
    "CodexToolService",
    "ContentSettingsSummaryOut",
    "ToolResourceNotFound",
]
