from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import InjectedSession, scoped_principal_dependency
from app.automations.definitions.execution import AutomationExecutionService
from app.automations.definitions.models import AutomationRun, AutomationTemplate
from app.automations.definitions.registry import node_catalog
from app.automations.definitions.resources import summarize_resources
from app.automations.definitions.schemas import (
    AutomationCreate,
    AutomationDetailOut,
    AutomationLifecycleInput,
    AutomationNodeCatalogOut,
    AutomationOut,
    AutomationPageOut,
    AutomationPatch,
    AutomationResourceCatalogIn,
    AutomationResourceCatalogOut,
    AutomationRunOut,
    AutomationRunPageOut,
    AutomationRunStart,
    AutomationTemplateOut,
    AutomationVersionCreate,
    AutomationVersionOut,
    AutomationVersionPageOut,
    AutomationVersionRestore,
    GraphValidationResult,
    TemplateCreateAutomationIn,
)
from app.automations.definitions.service import AutomationDefinitionService
from app.core.config import settings
from app.jobs.credential_capabilities import CapabilityStatusService
from app.security.auth import SecurityPrincipal

router = APIRouter(tags=["automations"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


# The automation surface publishes `insufficient_permission` rather than the
# repo-wide `scope_denied` (see the policy note in app.security.middleware), so
# the code is bound once here instead of repeated at every denial site.
AUTOMATION_DENIAL_CODE = "insufficient_permission"

_read_principal = scoped_principal_dependency(
    "automations:read",
    mutation=False,
    denial_code=AUTOMATION_DENIAL_CODE,
)
_write_principal = scoped_principal_dependency(
    "automations:write",
    mutation=True,
    denial_code=AUTOMATION_DENIAL_CODE,
)

ReadPrincipal = Annotated[SecurityPrincipal, Depends(_read_principal)]
WritePrincipal = Annotated[SecurityPrincipal, Depends(_write_principal)]


def _require_resource_scopes(principal: SecurityPrincipal, kinds: set[str]) -> None:
    required = {
        "provider": "providers:read",
        "destination": "destinations:read",
        "prompt_version": "prompts:read",
        "editorial_profile": "settings:read",
    }
    for kind in kinds:
        scope = required.get(kind)
        if scope is not None and not principal.permits(scope):
            raise HTTPException(403, detail={"code": AUTOMATION_DENIAL_CODE})


def _capability_status(session: AsyncSession) -> CapabilityStatusService:
    return CapabilityStatusService(session, config=settings)


@router.get("/automation-node-catalog", response_model=AutomationNodeCatalogOut)
async def get_automation_node_catalog(_principal: ReadPrincipal):
    return node_catalog()


@router.post("/automation-resource-catalog", response_model=AutomationResourceCatalogOut)
async def get_automation_resource_catalog(
    body: AutomationResourceCatalogIn,
    session: InjectedSession,
    principal: ReadPrincipal,
):
    _require_resource_scopes(principal, {resource.kind for resource in body.resources})
    resources = await summarize_resources(
        session,
        body.resources,
        automation_id=body.automation_id,
        capability_status=_capability_status(session),
    )
    _require_resource_scopes(principal, {resource.kind for resource in resources})
    return AutomationResourceCatalogOut(resources=resources)


@router.get("/automation-templates", response_model=list[AutomationTemplateOut])
async def list_automation_templates(session: InjectedSession, _principal: ReadPrincipal):
    rows = list(
        await session.scalars(
            select(AutomationTemplate)
            .where(AutomationTemplate.archived_at.is_(None))
            .order_by(AutomationTemplate.name, AutomationTemplate.seed_version.desc())
        )
    )
    latest: dict[str, AutomationTemplate] = {}
    for row in rows:
        latest.setdefault(row.seed_key, row)
    return [AutomationTemplateOut.model_validate(row) for row in latest.values()]


@router.post(
    "/automation-templates/{template_key}/create",
    response_model=AutomationDetailOut,
    status_code=201,
)
async def create_automation_from_template(
    template_key: str,
    body: TemplateCreateAutomationIn,
    session: InjectedSession,
    principal: WritePrincipal,
    idempotency_key: IdempotencyKey,
):
    result = await AutomationDefinitionService(session).create_from_template(
        template_key,
        name=body.name,
        description=body.description,
        principal=principal,
        idempotency_key=idempotency_key,
    )
    await session.commit()
    return result


@router.get("/automations", response_model=AutomationPageOut)
async def list_automations(
    session: InjectedSession,
    _principal: ReadPrincipal,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: UUID | None = None,
    include_archived: bool = False,
):
    return await AutomationDefinitionService(session).list_automations(
        limit=limit,
        cursor=cursor,
        include_archived=include_archived,
    )


@router.post("/automations", response_model=AutomationDetailOut, status_code=201)
async def create_automation(
    body: AutomationCreate,
    session: InjectedSession,
    principal: WritePrincipal,
    idempotency_key: IdempotencyKey,
):
    result = await AutomationDefinitionService(session).create_automation(
        body,
        principal=principal,
        idempotency_key=idempotency_key,
    )
    await session.commit()
    return result


@router.get("/automations/{automation_id}", response_model=AutomationDetailOut)
async def get_automation(automation_id: UUID, session: InjectedSession, _principal: ReadPrincipal):
    return await AutomationDefinitionService(session).get_automation(automation_id)


@router.patch("/automations/{automation_id}", response_model=AutomationOut)
async def patch_automation(
    automation_id: UUID,
    body: AutomationPatch,
    session: InjectedSession,
    principal: WritePrincipal,
):
    result = await AutomationDefinitionService(session).patch_automation(
        automation_id,
        body,
        principal=principal,
    )
    await session.commit()
    return result


@router.post("/automations/{automation_id}/duplicate", response_model=AutomationDetailOut, status_code=201)
async def duplicate_automation(
    automation_id: UUID,
    body: TemplateCreateAutomationIn,
    session: InjectedSession,
    principal: WritePrincipal,
    idempotency_key: IdempotencyKey,
):
    result = await AutomationDefinitionService(session).duplicate(
        automation_id,
        name=body.name,
        description=body.description,
        principal=principal,
        idempotency_key=idempotency_key,
    )
    await session.commit()
    return result


@router.post("/automations/{automation_id}/archive", response_model=AutomationOut)
async def archive_automation(
    automation_id: UUID,
    body: AutomationLifecycleInput,
    session: InjectedSession,
    principal: WritePrincipal,
):
    result = await AutomationDefinitionService(session).archive(
        automation_id,
        expected_revision=body.expected_revision,
        principal=principal,
    )
    await session.commit()
    return result


@router.post("/automations/{automation_id}/pause", response_model=AutomationOut)
async def pause_automation(
    automation_id: UUID,
    body: AutomationLifecycleInput,
    session: InjectedSession,
    principal: WritePrincipal,
):
    result = await AutomationDefinitionService(session).pause(
        automation_id,
        expected_revision=body.expected_revision,
        principal=principal,
    )
    await session.commit()
    return result


@router.post("/automations/{automation_id}/resume", response_model=AutomationOut)
async def resume_automation(
    automation_id: UUID,
    body: AutomationLifecycleInput,
    session: InjectedSession,
    principal: WritePrincipal,
):
    result = await AutomationDefinitionService(session).resume(
        automation_id,
        expected_revision=body.expected_revision,
        principal=principal,
        capability_status=_capability_status(session),
    )
    await session.commit()
    return result


@router.post("/automations/{automation_id}/activate", response_model=AutomationOut)
async def activate_automation(
    automation_id: UUID,
    body: AutomationLifecycleInput,
    session: InjectedSession,
    principal: WritePrincipal,
    idempotency_key: IdempotencyKey,
):
    result = await AutomationDefinitionService(session).activate(
        automation_id,
        expected_revision=body.expected_revision,
        principal=principal,
        capability_status=_capability_status(session),
        idempotency_key=idempotency_key,
    )
    await session.commit()
    return result


@router.get("/automations/{automation_id}/versions", response_model=AutomationVersionPageOut)
async def list_automation_versions(
    automation_id: UUID,
    session: InjectedSession,
    _principal: ReadPrincipal,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[int | None, Query(ge=1)] = None,
):
    return await AutomationDefinitionService(session).list_versions(
        automation_id,
        limit=limit,
        cursor=cursor,
    )


@router.post("/automations/{automation_id}/versions", response_model=AutomationVersionOut, status_code=201)
async def create_automation_version(
    automation_id: UUID,
    body: AutomationVersionCreate,
    session: InjectedSession,
    principal: WritePrincipal,
    idempotency_key: IdempotencyKey,
):
    result = await AutomationDefinitionService(session).create_version(
        automation_id,
        body,
        principal=principal,
        idempotency_key=idempotency_key,
    )
    await session.commit()
    return result


@router.get("/automations/{automation_id}/versions/{version_number}", response_model=AutomationVersionOut)
async def get_automation_version(
    automation_id: UUID,
    version_number: int,
    session: InjectedSession,
    _principal: ReadPrincipal,
):
    return await AutomationDefinitionService(session).get_version(automation_id, version_number)


@router.post(
    "/automations/{automation_id}/versions/{version_number}/restore-as-draft",
    response_model=AutomationVersionOut,
    status_code=201,
)
async def restore_automation_version(
    automation_id: UUID,
    version_number: int,
    body: AutomationVersionRestore,
    session: InjectedSession,
    principal: WritePrincipal,
    idempotency_key: IdempotencyKey,
):
    result = await AutomationDefinitionService(session).restore_version(
        automation_id,
        version_number,
        body,
        principal=principal,
        idempotency_key=idempotency_key,
    )
    await session.commit()
    return result


@router.post(
    "/automations/{automation_id}/versions/{version_number}/validate",
    response_model=GraphValidationResult,
)
async def validate_automation_version(
    automation_id: UUID,
    version_number: int,
    session: InjectedSession,
    principal: WritePrincipal,
):
    result = await AutomationDefinitionService(session).validate_version(
        automation_id,
        version_number,
        capability_status=_capability_status(session),
        principal=principal,
    )
    await session.commit()
    return result


@router.post("/automations/{automation_id}/runs", response_model=AutomationRunOut, status_code=202)
async def start_automation_run(
    automation_id: UUID,
    body: AutomationRunStart,
    session: InjectedSession,
    principal: WritePrincipal,
    idempotency_key: IdempotencyKey,
):
    result = await AutomationExecutionService(session).start(
        automation_id,
        body,
        principal=principal,
        capability_status=_capability_status(session),
        idempotency_key=idempotency_key,
    )
    await session.commit()
    return result


@router.get("/automations/{automation_id}/runs", response_model=AutomationRunPageOut)
async def list_automation_runs(
    automation_id: UUID,
    session: InjectedSession,
    _principal: ReadPrincipal,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: UUID | None = None,
    status: Literal[
        "pending",
        "queued",
        "running",
        "waiting_for_review",
        "succeeded",
        "warning",
        "failed",
        "cancelled",
    ] | None = None,
    dry_run: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    failed_only: bool = False,
):
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(422, detail={"code": "automation_run_date_range_invalid"})
    return await AutomationExecutionService(session).list(
        automation_id,
        limit=limit,
        cursor=cursor,
        status=status,
        dry_run=dry_run,
        date_from=date_from,
        date_to=date_to,
        failed_only=failed_only,
    )


@router.get("/automation-runs/{run_id}", response_model=AutomationRunOut)
async def get_automation_run(run_id: UUID, session: InjectedSession, _principal: ReadPrincipal):
    return await AutomationExecutionService(session).get(run_id)


@router.post("/automation-runs/{run_id}/review/approve", response_model=AutomationRunOut)
async def approve_automation_artifact_review(
    run_id: UUID,
    session: InjectedSession,
    _principal: WritePrincipal,
):
    run = await session.get(AutomationRun, run_id)
    if run is None:
        raise HTTPException(404, detail={"code": "automation_run_not_found"})
    from app.automations.definitions.runtime_state import continue_automation_artifact_review

    await continue_automation_artifact_review(session, run_id=run_id, observed_at=datetime.now(UTC))
    await session.commit()
    return await AutomationExecutionService(session).get(run_id)


__all__ = ["router"]
