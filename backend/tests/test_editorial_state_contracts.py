import pytest

from app.workflows.errors import EditorialValidationError
from app.workflows.states import (
    content_pack_transition,
    generation_run_transition,
    research_run_transition,
    variant_approval_transition,
)


def test_research_run_transitions_are_explicit_and_allow_operator_retry() -> None:
    assert research_run_transition("queued", "running").allowed
    assert research_run_transition("running", "succeeded").allowed
    assert research_run_transition("running", "needs_review").allowed
    assert research_run_transition("running", "failed").allowed
    assert not research_run_transition("succeeded", "running").allowed
    assert research_run_transition("failed", "running").allowed
    assert research_run_transition("needs_review", "running").allowed
    assert research_run_transition("failed", "failed").allowed
    assert not research_run_transition("unknown", "failed").allowed


def test_generation_run_supports_both_current_success_names_during_transition() -> None:
    assert generation_run_transition("running", "succeeded").allowed
    assert generation_run_transition("running", "completed").allowed
    assert generation_run_transition("running", "failed").allowed
    assert not generation_run_transition("completed", "running").allowed


def test_pack_and_revision_transitions_protect_review_truth() -> None:
    assert content_pack_transition("draft", "ready").allowed
    assert content_pack_transition("ready", "draft").allowed
    assert variant_approval_transition("draft", "pending_review").allowed
    assert variant_approval_transition("pending_review", "approved").allowed
    assert variant_approval_transition("pending_review", "rejected").allowed
    assert not variant_approval_transition("approved", "rejected").allowed


def test_required_transition_raises_the_shared_validation_error() -> None:
    from app.workflows.states import require_variant_approval_transition

    with pytest.raises(EditorialValidationError) as caught:
        require_variant_approval_transition("approved", "rejected")

    assert caught.value.category == "validation_failed"
    assert caught.value.code == "state_transition_invalid"
