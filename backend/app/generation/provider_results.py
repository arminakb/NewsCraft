from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.generation.generation_helpers import _safe_error_code
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.research.citations import CitationIntegrityError


def validate_provider_output(
    output: dict[str, Any],
    validate_output: Callable[[dict[str, Any]], Any],
) -> Any:
    try:
        return validate_output(output)
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


def map_provider_failure(
    exc: Exception,
    *,
    provider_completed: bool,
    workflow_attempt: int,
    workflow_job_id: UUID,
) -> tuple[RetryableJobError | NeedsReviewJobError | PermanentJobError, str]:
    error_class = getattr(exc, "classification", getattr(exc, "error_class", None))
    provider_code = _safe_error_code(getattr(exc, "code", ""), "generation_provider_failed")
    if isinstance(exc, PermanentJobError):
        return exc, "permanent"
    if isinstance(exc, NeedsReviewJobError):
        return exc, "needs_review"
    if isinstance(exc, RetryableJobError):
        return exc, "retryable"
    if provider_completed and isinstance(exc, CitationIntegrityError):
        return (
            NeedsReviewJobError(
                code="citation_integrity",
                message="Generation citations failed integrity validation",
            ),
            "needs_review",
        )
    if provider_completed and isinstance(exc, (ValidationError, ValueError)):
        return (
            NeedsReviewJobError(
                code="generation_output_invalid",
                message="Generation output failed validation",
            ),
            "needs_review",
        )
    if error_class == "permanent":
        return (
            PermanentJobError(
                code=provider_code,
                message="Generation provider rejected the request",
            ),
            "permanent",
        )
    if error_class == "needs_review":
        return (
            NeedsReviewJobError(
                code=provider_code,
                message="Generation requires operator review",
            ),
            "needs_review",
        )
    if isinstance(exc, ValueError):
        return (
            PermanentJobError(
                code="generation_provider_contract_invalid",
                message="Generation provider contract is invalid",
            ),
            "permanent",
        )
    retry_after_seconds = getattr(exc, "retry_after_seconds", None)
    if retry_after_seconds is None:
        base_delay = min(120, 5 * (2 ** max(0, workflow_attempt - 1)))
        jitter_seed = int.from_bytes(workflow_job_id.bytes[-2:], byteorder="big") / 65_535
        retry_after_seconds = base_delay + (base_delay * 0.2 * jitter_seed)
    return (
        RetryableJobError(
            code=provider_code,
            message="Generation provider call failed",
            retry_at=datetime.now(UTC) + timedelta(seconds=retry_after_seconds),
        ),
        "retryable",
    )


def normalize_provider_usage(usage: dict[str, Any], resolved: Any) -> tuple[dict[str, Any], Decimal]:
    """Normalize call cost and use frozen profile pricing when the provider omits it."""

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
