from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select

from app.automations.telegram.handlers import sha256_canonical
from app.core.faults import FaultInjector, NoopFaultInjector
from app.core.redaction import redact_string
from app.generation.generation_helpers import (
    _prompt_snapshot,
    _redacted_dict,
    _redacted_list,
    _safe_error_code,
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
from app.generation.providers.base import GenerationProviderRequest
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext
from app.research.citations import CitationIntegrityError
from app.workflows.states import require_generation_run_transition


async def _invoke(
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
    injector = fault_injector if fault_injector is not None else NoopFaultInjector()
    profile = await context.session.get(AIProviderProfile, profile_id)
    if profile is None:
        raise PermanentJobError(
            code="generation_profile_missing",
            message="Generation provider profile was not found",
        )
    try:
        resolve_with_session = getattr(profile_resolver, "resolve_with_session", None)
        resolved = (
            await resolve_with_session(profile, None, session=context.session)
            if resolve_with_session is not None
            else await profile_resolver.resolve(profile, None)
        )
    except Exception:
        raise PermanentJobError(
            code="generation_profile_unavailable",
            message="Generation provider profile is unavailable",
        ) from None
    try:
        require_prompt_integrity(prompt)
    except ValueError:
        raise PermanentJobError(
            code="generation_prompt_integrity_failed",
            message="Generation prompt snapshot integrity failed",
        ) from None
    input_hash = sha256_canonical(
        {
            "workflow_job_id": str(workflow_job_id),
            "stage_input_hash": input_hash,
            "resolved_model": resolved.model,
            "purpose": purpose,
        }
    )
    stage_key = f"{workflow_job_id}:{purpose}:{input_hash}"
    bind = context.session.get_bind()
    if bind.dialect.name == "postgresql":
        lock_id = int.from_bytes(
            __import__("hashlib").sha256(stage_key.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        await context.session.execute(select(func.pg_advisory_xact_lock(lock_id)))
    existing = await context.session.scalar(
        select(GenerationRun)
        .where(
            GenerationRun.provider_profile_id == profile.id,
            GenerationRun.prompt_template_version_id == prompt.id,
            GenerationRun.input_hash == input_hash,
        )
        .with_for_update()
    )
    if existing is not None and existing.status == "succeeded" and existing.output_payload:
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
        durable_output = {key: value for key, value in dict(existing.output_payload).items() if key != "_artifact"}
        try:
            validated = validate_output(durable_output)
        except CitationIntegrityError:
            raise NeedsReviewJobError(
                code="citation_integrity",
                message="Generation citations failed integrity validation",
            ) from None
        except ValidationError, ValueError:
            raise NeedsReviewJobError(
                code="generation_output_invalid",
                message="Generation output failed validation",
            ) from None
        return existing, completed, validated
    now = datetime.now(UTC)
    try:
        messages = render_prompt_messages(prompt, input_payload)
    except ValueError:
        raise PermanentJobError(
            code="generation_prompt_render_invalid",
            message="Generation prompt cannot be rendered",
        ) from None
    if existing is None:
        run = GenerationRun(
            id=uuid4(),
            story_revision_id=story_revision_id,
            provider_profile_id=profile.id,
            prompt_template_version_id=prompt.id,
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
        if run.requested_model is not None:
            run.requested_model = redact_string(run.requested_model)
        execution = (run.request_payload or {}).get("execution") or {}
        if run.status == "running" and execution.get("workflow_attempt") == workflow_attempt:
            raise RetryableJobError(
                code="generation_stage_in_progress",
                message="Generation stage is already running",
            )
        attempts = list(
            await context.session.scalars(
                select(GenerationAttempt).where(GenerationAttempt.generation_run_id == run.id)
            )
        )
        for stale in attempts:
            if stale.status == "running":
                stale.status = "failed"
                stale.error_class = "retryable"
                stale.error_code = "generation_attempt_interrupted"
                stale.error_message = "Prior generation attempt was interrupted"
                stale.finished_at = now
        run.status = require_generation_run_transition(run.status, "running")
        run.error_class = run.error_code = run.error_message = None
        run.finished_at = None
    attempt = GenerationAttempt(
        id=uuid4(),
        generation_run_id=run.id,
        attempt_number=max((item.attempt_number for item in attempts), default=0) + 1,
        provider=resolved.provider_type,
        requested_model=redact_string(resolved.model),
        resolved_model=redact_string(resolved.model),
        prompt_snapshot=_redacted_dict(_prompt_snapshot(prompt, messages)),
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
            "input": input_payload,
            "prompt": _prompt_snapshot(prompt, messages),
            "execution": {
                "workflow_job_id": str(workflow_job_id),
                "workflow_attempt": workflow_attempt,
                "active_attempt_id": str(attempt.id),
            },
        }
    )
    await context.session.flush()
    run_id = run.id
    attempt_id = attempt.id
    await context.session.commit()

    request = GenerationProviderRequest(
        run_id=run_id,
        purpose=purpose,
        requested_model=resolved.model,
        messages=messages,
        response_schema=dict(prompt.output_schema or {}),
        metadata={
            "provider_profile_id": str(profile.id),
            "prompt_template_version_id": str(prompt.id),
            "input_payload": dict(input_payload),
            "max_output_tokens": getattr(resolved, "max_output_tokens", None),
        },
    )
    provider_completed = False
    try:
        if before_provider_call is not None:
            await before_provider_call()
            # The callback may use SELECT ... FOR UPDATE. Release that read
            # transaction before crossing the provider/network boundary.
            await context.session.commit()
        if expected_provider_configuration_revision is not None or expected_provider_configuration_checksum is not None:
            await context.session.refresh(profile)
            try:
                latest = (
                    await resolve_with_session(profile, None, session=context.session)
                    if resolve_with_session is not None
                    else await profile_resolver.resolve(profile, None)
                )
            except Exception:
                old_client = getattr(resolved.provider, "http_client", None)
                if old_client is not None and hasattr(old_client, "aclose"):
                    await old_client.aclose()
                raise PermanentJobError(
                    code="generation_provider_configuration_changed",
                    message="Generation provider configuration changed after enqueue",
                ) from None
            latest_revision = latest.configuration_revision
            latest_checksum = latest.configuration_checksum
            if not latest_checksum:
                fallback_identity = provider_identity_for_profile(profile)
                latest_revision = fallback_identity.revision
                latest_checksum = fallback_identity.checksum
            if (
                expected_provider_configuration_revision is not None
                and latest_revision != expected_provider_configuration_revision
            ) or (
                expected_provider_configuration_checksum is not None
                and latest_checksum != expected_provider_configuration_checksum
            ):
                latest_client = getattr(latest.provider, "http_client", None)
                if latest_client is not None and hasattr(latest_client, "aclose"):
                    await latest_client.aclose()
                old_client = getattr(resolved.provider, "http_client", None)
                if old_client is not None and hasattr(old_client, "aclose"):
                    await old_client.aclose()
                raise PermanentJobError(
                    code="generation_provider_configuration_changed",
                    message="Generation provider configuration changed after enqueue",
                )
            old_client = getattr(resolved.provider, "http_client", None)
            if old_client is not None and old_client is not getattr(latest.provider, "http_client", None):
                await old_client.aclose()
            resolved = latest
            await context.session.commit()
        max_attempts = getattr(resolved, "max_attempts", None)
        if max_attempts is not None and attempt.attempt_number > max_attempts:
            raise NeedsReviewJobError(
                code="generation_provider_attempt_budget_exhausted",
                message="Generation provider attempt budget is exhausted",
            )
        remaining_seconds: float | None = None
        max_elapsed_seconds = getattr(resolved, "max_elapsed_seconds", None)
        if max_elapsed_seconds is not None and pack_budget_started_at is not None:
            remaining_seconds = max_elapsed_seconds - (datetime.now(UTC) - pack_budget_started_at).total_seconds()
            if remaining_seconds <= 0:
                raise NeedsReviewJobError(
                    code="generation_pack_elapsed_budget_exhausted",
                    message="Generation pack elapsed-time budget is exhausted",
                )
        if remaining_seconds is None:
            result = await resolved.provider.generate(request)
        else:
            try:
                async with asyncio.timeout(remaining_seconds):
                    result = await resolved.provider.generate(request)
            except TimeoutError:
                raise NeedsReviewJobError(
                    code="generation_pack_elapsed_budget_exhausted",
                    message="Generation pack elapsed-time budget is exhausted",
                ) from None
        provider_completed = True
        normalized_usage, call_cost = _usage_with_qualified_pricing(result.usage, resolved)
        result = replace(result, usage=normalized_usage)
        max_pack_cost_usd = getattr(resolved, "max_pack_cost_usd", None)
        if max_pack_cost_usd is not None and prior_pack_cost_usd + call_cost > max_pack_cost_usd:
            raise NeedsReviewJobError(
                code="generation_pack_cost_budget_exhausted",
                message="Generation pack cost budget is exhausted",
            )
        await injector.hit(
            "generation.after_provider_before_persist",
            {
                "workflow_job_id": str(workflow_job_id),
                "generation_run_id": str(run_id),
                "generation_attempt_id": str(attempt_id),
                "purpose": purpose,
            },
        )
        validated = validate_output(result.output)
    except Exception as exc:
        await context.session.rollback()
        error_class = getattr(exc, "classification", getattr(exc, "error_class", None))
        provider_code = _safe_error_code(getattr(exc, "code", ""), "generation_provider_failed")
        mapped: RetryableJobError | NeedsReviewJobError | PermanentJobError
        if isinstance(exc, PermanentJobError):
            mapped = exc
            error_class = "permanent"
        elif isinstance(exc, NeedsReviewJobError):
            mapped = exc
            error_class = "needs_review"
        elif isinstance(exc, RetryableJobError):
            mapped = exc
            error_class = "retryable"
        elif provider_completed and isinstance(exc, CitationIntegrityError):
            mapped = NeedsReviewJobError(
                code="citation_integrity",
                message="Generation citations failed integrity validation",
            )
            error_class = "needs_review"
        elif provider_completed and isinstance(exc, (ValidationError, ValueError)):
            mapped = NeedsReviewJobError(
                code="generation_output_invalid",
                message="Generation output failed validation",
            )
            error_class = "needs_review"
        elif error_class == "permanent":
            mapped = PermanentJobError(
                code=provider_code,
                message="Generation provider rejected the request",
            )
        elif error_class == "needs_review":
            mapped = NeedsReviewJobError(
                code=provider_code,
                message="Generation requires operator review",
            )
        elif isinstance(exc, ValueError):
            mapped = PermanentJobError(
                code="generation_provider_contract_invalid",
                message="Generation provider contract is invalid",
            )
            error_class = "permanent"
        else:
            retry_after_seconds = getattr(exc, "retry_after_seconds", None)
            if retry_after_seconds is None:
                base_delay = min(120, 5 * (2 ** max(0, workflow_attempt - 1)))
                jitter_seed = int.from_bytes(workflow_job_id.bytes[-2:], byteorder="big") / 65_535
                retry_after_seconds = base_delay + (base_delay * 0.2 * jitter_seed)
            mapped = RetryableJobError(
                code=provider_code,
                message="Generation provider call failed",
                retry_at=datetime.now(UTC) + timedelta(seconds=retry_after_seconds),
            )
            error_class = "retryable"
        async with context.session.begin():
            current_run = await context.session.scalar(
                select(GenerationRun)
                .where(GenerationRun.id == run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            current_attempt = await context.session.scalar(
                select(GenerationAttempt)
                .where(GenerationAttempt.id == attempt_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if current_run is not None and current_attempt is not None:
                active = ((current_run.request_payload or {}).get("execution") or {}).get("active_attempt_id")
                if active == str(attempt_id):
                    durable_error_code = redact_string(mapped.code)
                    durable_error_message = redact_string(mapped.message)
                    current_attempt.status = "failed"
                    if provider_completed:
                        current_attempt.usage = _redacted_dict(result.usage)
                    current_attempt.error_class = error_class
                    current_attempt.error_code = durable_error_code
                    current_attempt.error_message = durable_error_message
                    current_attempt.finished_at = datetime.now(UTC)
                    if isinstance(exc, ValidationError):
                        current_attempt.validation_errors = _redacted_list(
                            [
                                {
                                    "type": item["type"],
                                    "loc": [str(part) for part in item["loc"]],
                                    "message": item["msg"],
                                }
                                for item in exc.errors(
                                    include_input=False,
                                    include_url=False,
                                )
                            ]
                        )
                    elif isinstance(getattr(exc, "diagnostic", None), dict):
                        current_attempt.validation_errors = _redacted_list([exc.diagnostic])
                    elif isinstance(exc, CitationIntegrityError):
                        current_attempt.validation_errors = _redacted_list(
                            [
                                {
                                    "code": "citation_integrity",
                                    "message": "Generation citations failed integrity validation",
                                }
                            ]
                        )
                    current_run.status = require_generation_run_transition(current_run.status, "failed")
                    current_run.error_class = error_class
                    current_run.error_code = durable_error_code
                    current_run.error_message = durable_error_message
                    current_run.finished_at = datetime.now(UTC)
        raise mapped from None

    async with context.session.begin():
        current_run = await context.session.scalar(
            select(GenerationRun)
            .where(GenerationRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current_attempt = await context.session.scalar(
            select(GenerationAttempt)
            .where(GenerationAttempt.id == attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current_run is None or current_attempt is None:
            raise RetryableJobError(
                code="generation_stage_missing",
                message="Generation stage disappeared before persistence",
            )
        active = ((current_run.request_payload or {}).get("execution") or {}).get("active_attempt_id")
        if active != str(attempt_id) or current_attempt.status != "running":
            raise RetryableJobError(
                code="generation_stage_superseded",
                message="Generation stage was superseded by another lease",
            )
        durable_output = _redacted_dict(result.output)
        current_attempt.response_payload = durable_output
        current_attempt.resolved_model = redact_string(result.resolved_model)
        current_attempt.usage = _redacted_dict(result.usage)
        current_attempt.status = "succeeded"
        current_attempt.finished_at = datetime.now(UTC)
        current_run.output_payload = durable_output
        current_run.status = require_generation_run_transition(current_run.status, "succeeded")
        current_run.finished_at = datetime.now(UTC)
        current_run.error_class = current_run.error_code = current_run.error_message = None
    return current_run, current_attempt, validated


def _usage_with_qualified_pricing(usage: dict[str, Any], resolved: Any) -> tuple[dict[str, Any], Decimal]:
    """Normalize a call cost and use frozen profile pricing when the provider omits it."""

    normalized = dict(usage)
    try:
        supplied = Decimal(str(normalized.get("cost_usd", 0)))
        input_tokens = Decimal(str(normalized.get("input_tokens", 0)))
        output_tokens = Decimal(str(normalized.get("output_tokens", 0)))
    except InvalidOperation, TypeError, ValueError:
        raise NeedsReviewJobError(
            code="generation_provider_usage_invalid",
            message="Generation provider usage metadata is invalid",
        ) from None
    if (
        not supplied.is_finite()
        or not input_tokens.is_finite()
        or not output_tokens.is_finite()
        or supplied < 0
        or input_tokens < 0
        or output_tokens < 0
    ):
        raise NeedsReviewJobError(
            code="generation_provider_usage_invalid",
            message="Generation provider usage metadata is invalid",
        )
    max_output_tokens = getattr(resolved, "max_output_tokens", None)
    if max_output_tokens is not None and output_tokens > max_output_tokens:
        raise NeedsReviewJobError(
            code="generation_provider_output_budget_exhausted",
            message="Generation provider output-token budget is exhausted",
        )
    priced = Decimal("0")
    if (
        getattr(resolved, "pricing_input_usd_per_million", None) is not None
        and getattr(resolved, "pricing_output_usd_per_million", None) is not None
    ):
        priced = (
            input_tokens * resolved.pricing_input_usd_per_million
            + output_tokens * resolved.pricing_output_usd_per_million
        ) / Decimal(1_000_000)
    effective = max(supplied, priced)
    normalized["cost_usd"] = float(effective)
    normalized["cost_basis"] = "provider_or_profile_max" if priced else "provider"
    return normalized, effective
