from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.automations.telegram.handlers import sha256_canonical
from app.core.faults import FaultInjector, NoopFaultInjector
from app.core.redaction import redact_string
from app.generation.generation_helpers import (
    _prompt_snapshot,
    _redacted_dict,
    _redacted_list,
    render_prompt_messages,
    require_prompt_integrity,
)
from app.generation.models import (
    AIProviderProfile,
    GenerationAttempt,
    GenerationRun,
    PromptTemplateVersion,
)
from app.generation.provider_identity import provider_identity_for_profile
from app.generation.provider_results import (
    map_provider_failure,
    normalize_provider_usage,
    validate_provider_output,
)
from app.generation.providers.base import (
    GenerationProviderRequest,
    GenerationProviderResult,
    ProviderMessage,
)
from app.generation.providers.profiles import ProviderProfileConfigurationError, ResolvedProviderProfile
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext
from app.research.citations import CitationIntegrityError
from app.security.secret_store import SecretStoreUnavailable
from app.workflows.states import require_generation_run_transition


@dataclass(frozen=True, slots=True)
class ProviderInvocation:
    profile_resolver: Any
    prompt: PromptTemplateVersion
    purpose: str
    story_revision_id: UUID | None
    input_payload: dict[str, Any]
    stage_input_hash: str
    workflow_job_id: UUID
    workflow_attempt: int
    validate_output: Callable[[dict[str, Any]], Any]
    expected_configuration_revision: str | None
    expected_configuration_checksum: str | None
    pack_budget_started_at: datetime | None
    prior_pack_cost_usd: Decimal
    before_provider_call: Callable[[], Awaitable[None]] | None
    injector: FaultInjector


@dataclass(slots=True)
class ProviderCallState:
    result: GenerationProviderResult | None = None


async def _resolve_profile(
    context: JobContext,
    *,
    profile_resolver: Any,
    profile_id: UUID,
) -> tuple[AIProviderProfile, ResolvedProviderProfile]:
    profile = await context.session.get(AIProviderProfile, profile_id)
    if profile is None:
        raise PermanentJobError(
            code="generation_profile_missing",
            message="Generation provider profile was not found",
        )
    try:
        return profile, await _resolve_provider(profile_resolver, profile, context)
    except (ProviderProfileConfigurationError, ValueError) as exc:
        raise PermanentJobError(
            code="generation_profile_unavailable",
            message="Generation provider profile is unavailable",
        ) from exc
    except (DBAPIError, SecretStoreUnavailable) as exc:
        raise RetryableJobError(
            code="generation_profile_temporarily_unavailable",
            message="Generation provider profile is temporarily unavailable",
        ) from exc


async def _resolve_provider(
    profile_resolver: Any,
    profile: AIProviderProfile,
    context: JobContext,
) -> ResolvedProviderProfile:
    resolve_with_session = getattr(profile_resolver, "resolve_with_session", None)
    if resolve_with_session is not None:
        return await resolve_with_session(profile, None, session=context.session)
    return await profile_resolver.resolve(profile, None)


def _require_valid_prompt(prompt: PromptTemplateVersion) -> None:
    try:
        require_prompt_integrity(prompt)
    except ValueError:
        raise PermanentJobError(
            code="generation_prompt_integrity_failed",
            message="Generation prompt snapshot integrity failed",
        ) from None


def _stage_identity(command: ProviderInvocation, resolved: ResolvedProviderProfile) -> tuple[str, str]:
    input_hash = sha256_canonical(
        {
            "workflow_job_id": str(command.workflow_job_id),
            "stage_input_hash": command.stage_input_hash,
            "resolved_model": resolved.model,
            "purpose": command.purpose,
        }
    )
    return input_hash, f"{command.workflow_job_id}:{command.purpose}:{input_hash}"


async def _lock_stage(context: JobContext, stage_key: str) -> None:
    if context.session.get_bind().dialect.name != "postgresql":
        return
    lock_id = int.from_bytes(
        hashlib.sha256(stage_key.encode()).digest()[:8],
        byteorder="big",
        signed=True,
    )
    await context.session.execute(select(func.pg_advisory_xact_lock(lock_id)))


async def _existing_run(
    context: JobContext,
    *,
    profile: AIProviderProfile,
    prompt: PromptTemplateVersion,
    input_hash: str,
) -> GenerationRun | None:
    return await context.session.scalar(
        select(GenerationRun)
        .where(
            GenerationRun.provider_profile_id == profile.id,
            GenerationRun.prompt_template_version_id == prompt.id,
            GenerationRun.input_hash == input_hash,
        )
        .with_for_update()
    )


async def _reuse_succeeded_run(
    context: JobContext,
    existing: GenerationRun | None,
    validate_output: Callable[[dict[str, Any]], Any],
) -> tuple[GenerationRun, GenerationAttempt, Any] | None:
    if existing is None or existing.status != "succeeded" or not existing.output_payload:
        return None
    completed = await context.session.scalar(
        select(GenerationAttempt)
        .where(
            GenerationAttempt.generation_run_id == existing.id,
            GenerationAttempt.status == "succeeded",
        )
        .order_by(GenerationAttempt.attempt_number.desc())
    )
    if completed is None:
        raise RetryableJobError(
            code="generation_attempt_missing",
            message="Durable generation attempt is missing",
        )
    output = {key: value for key, value in dict(existing.output_payload).items() if key != "_artifact"}
    return existing, completed, validate_provider_output(output, validate_output)


def _render_messages(
    prompt: PromptTemplateVersion,
    input_payload: dict[str, Any],
) -> tuple[ProviderMessage, ProviderMessage]:
    try:
        return render_prompt_messages(prompt, input_payload)
    except ValueError:
        raise PermanentJobError(
            code="generation_prompt_render_invalid",
            message="Generation prompt cannot be rendered",
        ) from None


async def _resume_run(
    context: JobContext,
    run: GenerationRun,
    *,
    workflow_attempt: int,
    now: datetime,
) -> list[GenerationAttempt]:
    if run.requested_model is not None:
        run.requested_model = redact_string(run.requested_model)
    execution = (run.request_payload or {}).get("execution") or {}
    if run.status == "running" and execution.get("workflow_attempt") == workflow_attempt:
        raise RetryableJobError(
            code="generation_stage_in_progress",
            message="Generation stage is already running",
        )
    attempts = list(
        await context.session.scalars(select(GenerationAttempt).where(GenerationAttempt.generation_run_id == run.id))
    )
    for stale in attempts:
        if stale.status != "running":
            continue
        stale.status = "failed"
        stale.error_class = "retryable"
        stale.error_code = "generation_attempt_interrupted"
        stale.error_message = "Prior generation attempt was interrupted"
        stale.finished_at = now
    run.status = require_generation_run_transition(run.status, "running")
    run.error_class = run.error_code = run.error_message = None
    run.finished_at = None
    return attempts


async def _start_attempt(
    context: JobContext,
    *,
    existing: GenerationRun | None,
    profile: AIProviderProfile,
    resolved: ResolvedProviderProfile,
    command: ProviderInvocation,
    input_hash: str,
    stage_key: str,
) -> tuple[GenerationRun, GenerationAttempt, tuple[ProviderMessage, ProviderMessage]]:
    now = datetime.now(UTC)
    messages = _render_messages(command.prompt, command.input_payload)
    if existing is None:
        run = GenerationRun(
            id=uuid4(),
            story_revision_id=command.story_revision_id,
            provider_profile_id=profile.id,
            prompt_template_version_id=command.prompt.id,
            requested_model=redact_string(resolved.model),
            status="running",
            input_hash=input_hash,
            request_payload={},
            output_payload={},
            started_at=now,
        )
        context.session.add(run)
        attempts: list[GenerationAttempt] = []
        await context.session.flush()
    else:
        run = existing
        attempts = await _resume_run(
            context,
            run,
            workflow_attempt=command.workflow_attempt,
            now=now,
        )
    attempt = GenerationAttempt(
        id=uuid4(),
        generation_run_id=run.id,
        attempt_number=max((item.attempt_number for item in attempts), default=0) + 1,
        provider=resolved.provider_type,
        requested_model=redact_string(resolved.model),
        resolved_model=redact_string(resolved.model),
        prompt_snapshot=_redacted_dict(_prompt_snapshot(command.prompt, messages)),
        response_payload={},
        usage={},
        validation_errors=[],
        status="running",
        started_at=now,
    )
    context.session.add(attempt)
    run.request_payload = _redacted_dict(
        {
            "stage_key": stage_key,
            "input": command.input_payload,
            "prompt": _prompt_snapshot(command.prompt, messages),
            "execution": {
                "workflow_job_id": str(command.workflow_job_id),
                "workflow_attempt": command.workflow_attempt,
                "active_attempt_id": str(attempt.id),
            },
        }
    )
    await context.session.flush()
    await context.session.commit()
    return run, attempt, messages


def _provider_request(
    *,
    run_id: UUID,
    profile: AIProviderProfile,
    resolved: ResolvedProviderProfile,
    command: ProviderInvocation,
    messages: tuple[ProviderMessage, ProviderMessage],
) -> GenerationProviderRequest:
    return GenerationProviderRequest(
        run_id=run_id,
        purpose=command.purpose,
        requested_model=resolved.model,
        messages=messages,
        response_schema=dict(command.prompt.output_schema or {}),
        metadata={
            "provider_profile_id": str(profile.id),
            "prompt_template_version_id": str(command.prompt.id),
            "input_payload": dict(command.input_payload),
            "max_output_tokens": getattr(resolved, "max_output_tokens", None),
        },
    )


async def _close_provider_client(resolved: ResolvedProviderProfile) -> None:
    client = getattr(resolved.provider, "http_client", None)
    if client is not None and hasattr(client, "aclose"):
        await client.aclose()


def _configuration_matches(
    command: ProviderInvocation,
    profile: AIProviderProfile,
    latest: ResolvedProviderProfile,
) -> bool:
    revision = latest.configuration_revision
    checksum = latest.configuration_checksum
    if not checksum:
        identity = provider_identity_for_profile(profile)
        revision = identity.revision
        checksum = identity.checksum
    return (
        command.expected_configuration_revision is None or revision == command.expected_configuration_revision
    ) and (command.expected_configuration_checksum is None or checksum == command.expected_configuration_checksum)


async def _refresh_provider_configuration(
    context: JobContext,
    *,
    profile: AIProviderProfile,
    resolved: ResolvedProviderProfile,
    command: ProviderInvocation,
) -> ResolvedProviderProfile:
    if command.expected_configuration_revision is None and command.expected_configuration_checksum is None:
        return resolved
    await context.session.refresh(profile)
    try:
        latest = await _resolve_provider(command.profile_resolver, profile, context)
    except Exception:
        await _close_provider_client(resolved)
        raise PermanentJobError(
            code="generation_provider_configuration_changed",
            message="Generation provider configuration changed after enqueue",
        ) from None
    if not _configuration_matches(command, profile, latest):
        await _close_provider_client(latest)
        await _close_provider_client(resolved)
        raise PermanentJobError(
            code="generation_provider_configuration_changed",
            message="Generation provider configuration changed after enqueue",
        )
    old_client = getattr(resolved.provider, "http_client", None)
    latest_client = getattr(latest.provider, "http_client", None)
    if old_client is not None and old_client is not latest_client:
        await old_client.aclose()
    await context.session.commit()
    return latest


def _remaining_pack_seconds(
    resolved: ResolvedProviderProfile,
    started_at: datetime | None,
) -> float | None:
    max_elapsed_seconds = getattr(resolved, "max_elapsed_seconds", None)
    if max_elapsed_seconds is None or started_at is None:
        return None
    remaining = max_elapsed_seconds - (datetime.now(UTC) - started_at).total_seconds()
    if remaining <= 0:
        raise NeedsReviewJobError(
            code="generation_pack_elapsed_budget_exhausted",
            message="Generation pack elapsed-time budget is exhausted",
        )
    return remaining


async def _call_provider(
    resolved: ResolvedProviderProfile,
    request: GenerationProviderRequest,
    remaining_seconds: float | None,
) -> GenerationProviderResult:
    if remaining_seconds is None:
        return await resolved.provider.generate(request)
    try:
        async with asyncio.timeout(remaining_seconds):
            return await resolved.provider.generate(request)
    except TimeoutError:
        raise NeedsReviewJobError(
            code="generation_pack_elapsed_budget_exhausted",
            message="Generation pack elapsed-time budget is exhausted",
        ) from None


async def _execute_provider_call(
    context: JobContext,
    *,
    profile: AIProviderProfile,
    resolved: ResolvedProviderProfile,
    attempt: GenerationAttempt,
    request: GenerationProviderRequest,
    command: ProviderInvocation,
    state: ProviderCallState,
) -> tuple[ResolvedProviderProfile, GenerationProviderResult, Any]:
    if command.before_provider_call is not None:
        await command.before_provider_call()
        await context.session.commit()
    resolved = await _refresh_provider_configuration(
        context,
        profile=profile,
        resolved=resolved,
        command=command,
    )
    max_attempts = getattr(resolved, "max_attempts", None)
    if max_attempts is not None and attempt.attempt_number > max_attempts:
        raise NeedsReviewJobError(
            code="generation_provider_attempt_budget_exhausted",
            message="Generation provider attempt budget is exhausted",
        )
    state.result = await _call_provider(
        resolved,
        request,
        _remaining_pack_seconds(resolved, command.pack_budget_started_at),
    )
    normalized_usage, call_cost = normalize_provider_usage(state.result.usage, resolved)
    state.result = replace(state.result, usage=normalized_usage)
    max_pack_cost_usd = getattr(resolved, "max_pack_cost_usd", None)
    if max_pack_cost_usd is not None and command.prior_pack_cost_usd + call_cost > max_pack_cost_usd:
        raise NeedsReviewJobError(
            code="generation_pack_cost_budget_exhausted",
            message="Generation pack cost budget is exhausted",
        )
    await command.injector.hit(
        "generation.after_provider_before_persist",
        {
            "workflow_job_id": str(command.workflow_job_id),
            "generation_run_id": str(attempt.generation_run_id),
            "generation_attempt_id": str(attempt.id),
            "purpose": command.purpose,
        },
    )
    return resolved, state.result, command.validate_output(state.result.output)


async def _locked_stage_rows(
    context: JobContext,
    *,
    run_id: UUID,
    attempt_id: UUID,
) -> tuple[GenerationRun | None, GenerationAttempt | None]:
    run = await context.session.scalar(
        select(GenerationRun)
        .where(GenerationRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    attempt = await context.session.scalar(
        select(GenerationAttempt)
        .where(GenerationAttempt.id == attempt_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return run, attempt


def _validation_errors(exc: Exception) -> list[Any]:
    if isinstance(exc, ValidationError):
        return [
            {
                "type": item["type"],
                "loc": [str(part) for part in item["loc"]],
                "message": item["msg"],
            }
            for item in exc.errors(include_input=False, include_url=False)
        ]
    diagnostic = getattr(exc, "diagnostic", None)
    if isinstance(diagnostic, dict):
        return [diagnostic]
    if isinstance(exc, CitationIntegrityError):
        return [
            {
                "code": "citation_integrity",
                "message": "Generation citations failed integrity validation",
            }
        ]
    return []


async def _persist_failure(
    context: JobContext,
    *,
    run_id: UUID,
    attempt_id: UUID,
    command: ProviderInvocation,
    exc: Exception,
    provider_result: GenerationProviderResult | None,
) -> Exception:
    await context.session.rollback()
    mapped, error_class = map_provider_failure(
        exc,
        provider_completed=provider_result is not None,
        workflow_attempt=command.workflow_attempt,
        workflow_job_id=command.workflow_job_id,
    )
    async with context.session.begin():
        run, attempt = await _locked_stage_rows(
            context,
            run_id=run_id,
            attempt_id=attempt_id,
        )
        if run is None or attempt is None:
            return mapped
        active_attempt_id = ((run.request_payload or {}).get("execution") or {}).get("active_attempt_id")
        if active_attempt_id != str(attempt_id):
            return mapped
        error_code = redact_string(mapped.code)
        error_message = redact_string(mapped.message)
        attempt.status = "failed"
        if provider_result is not None:
            attempt.usage = _redacted_dict(provider_result.usage)
        attempt.error_class = error_class
        attempt.error_code = error_code
        attempt.error_message = error_message
        attempt.finished_at = datetime.now(UTC)
        attempt.validation_errors = _redacted_list(_validation_errors(exc))
        run.status = require_generation_run_transition(run.status, "failed")
        run.error_class = error_class
        run.error_code = error_code
        run.error_message = error_message
        run.finished_at = datetime.now(UTC)
    return mapped


async def _persist_success(
    context: JobContext,
    *,
    run_id: UUID,
    attempt_id: UUID,
    result: GenerationProviderResult,
) -> tuple[GenerationRun, GenerationAttempt]:
    async with context.session.begin():
        run, attempt = await _locked_stage_rows(
            context,
            run_id=run_id,
            attempt_id=attempt_id,
        )
        if run is None or attempt is None:
            raise RetryableJobError(
                code="generation_stage_missing",
                message="Generation stage disappeared before persistence",
            )
        active = ((run.request_payload or {}).get("execution") or {}).get("active_attempt_id")
        if active != str(attempt_id) or attempt.status != "running":
            raise RetryableJobError(
                code="generation_stage_superseded",
                message="Generation stage was superseded by another lease",
            )
        output = _redacted_dict(result.output)
        attempt.response_payload = output
        attempt.resolved_model = redact_string(result.resolved_model)
        attempt.usage = _redacted_dict(result.usage)
        attempt.status = "succeeded"
        attempt.finished_at = datetime.now(UTC)
        run.output_payload = output
        run.status = require_generation_run_transition(run.status, "succeeded")
        run.finished_at = datetime.now(UTC)
        run.error_class = run.error_code = run.error_message = None
    return run, attempt


async def invoke(
    context: JobContext,
    *,
    profile_resolver: Any,
    profile_id: UUID,
    prompt: PromptTemplateVersion,
    purpose: str,
    story_revision_id: UUID | None,
    input_payload: dict[str, Any],
    input_hash: str,
    workflow_job_id: UUID,
    workflow_attempt: int,
    validate_output: Callable[[dict[str, Any]], Any],
    expected_provider_configuration_revision: str | None = None,
    expected_provider_configuration_checksum: str | None = None,
    pack_budget_started_at: datetime | None = None,
    prior_pack_cost_usd: Decimal = Decimal("0"),
    before_provider_call: Callable[[], Awaitable[None]] | None = None,
    fault_injector: FaultInjector | None = None,
) -> tuple[GenerationRun, GenerationAttempt, Any]:
    command = ProviderInvocation(
        profile_resolver=profile_resolver,
        prompt=prompt,
        purpose=purpose,
        story_revision_id=story_revision_id,
        input_payload=input_payload,
        stage_input_hash=input_hash,
        workflow_job_id=workflow_job_id,
        workflow_attempt=workflow_attempt,
        validate_output=validate_output,
        expected_configuration_revision=expected_provider_configuration_revision,
        expected_configuration_checksum=expected_provider_configuration_checksum,
        pack_budget_started_at=pack_budget_started_at,
        prior_pack_cost_usd=prior_pack_cost_usd,
        before_provider_call=before_provider_call,
        injector=fault_injector if fault_injector is not None else NoopFaultInjector(),
    )
    profile, resolved = await _resolve_profile(
        context,
        profile_resolver=profile_resolver,
        profile_id=profile_id,
    )
    _require_valid_prompt(prompt)
    durable_hash, stage_key = _stage_identity(command, resolved)
    await _lock_stage(context, stage_key)
    existing = await _existing_run(
        context,
        profile=profile,
        prompt=prompt,
        input_hash=durable_hash,
    )
    reused = await _reuse_succeeded_run(context, existing, validate_output)
    if reused is not None:
        return reused
    run, attempt, messages = await _start_attempt(
        context,
        existing=existing,
        profile=profile,
        resolved=resolved,
        command=command,
        input_hash=durable_hash,
        stage_key=stage_key,
    )
    request = _provider_request(
        run_id=run.id,
        profile=profile,
        resolved=resolved,
        command=command,
        messages=messages,
    )
    call_state = ProviderCallState()
    try:
        _resolved, result, validated = await _execute_provider_call(
            context,
            profile=profile,
            resolved=resolved,
            attempt=attempt,
            request=request,
            command=command,
            state=call_state,
        )
    except Exception as exc:
        mapped = await _persist_failure(
            context,
            run_id=run.id,
            attempt_id=attempt.id,
            command=command,
            exc=exc,
            provider_result=call_state.result,
        )
        raise mapped from None
    durable_run, durable_attempt = await _persist_success(
        context,
        run_id=run.id,
        attempt_id=attempt.id,
        result=result,
    )
    return durable_run, durable_attempt, validated
