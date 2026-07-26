from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.generation.provider_results import (
    map_provider_failure,
    normalize_provider_usage,
    validate_provider_output,
)
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError


def test_validate_provider_output_maps_invalid_artifact_to_review() -> None:
    with pytest.raises(NeedsReviewJobError, match="failed validation") as caught:
        validate_provider_output({}, lambda _output: (_ for _ in ()).throw(ValueError("bad output")))

    assert caught.value.code == "generation_output_invalid"


def test_map_provider_failure_preserves_domain_error_and_classification() -> None:
    failure = PermanentJobError(code="provider_disabled", message="Provider disabled")

    mapped, classification = map_provider_failure(
        failure,
        provider_completed=False,
        workflow_attempt=1,
        workflow_job_id=UUID(int=1),
    )

    assert mapped is failure
    assert classification == "permanent"


def test_map_provider_failure_assigns_deterministic_retry_window() -> None:
    mapped, classification = map_provider_failure(
        RuntimeError("transport failed"),
        provider_completed=False,
        workflow_attempt=2,
        workflow_job_id=UUID(int=1),
    )

    assert isinstance(mapped, RetryableJobError)
    assert mapped.code == "generation_provider_failed"
    assert mapped.retry_at is not None
    assert classification == "retryable"


def test_normalize_provider_usage_uses_frozen_profile_pricing() -> None:
    resolved = SimpleNamespace(
        max_output_tokens=500,
        pricing_input_usd_per_million=Decimal("2"),
        pricing_output_usd_per_million=Decimal("4"),
    )

    usage, cost = normalize_provider_usage(
        {"input_tokens": 1_000_000, "output_tokens": 500, "cost_usd": 1},
        resolved,
    )

    assert cost == Decimal("2.002")
    assert usage == {
        "input_tokens": 1_000_000,
        "output_tokens": 500,
        "cost_usd": 2.002,
        "cost_basis": "provider_or_profile_max",
    }
