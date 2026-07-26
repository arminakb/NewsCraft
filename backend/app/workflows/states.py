from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.workflows.errors import EditorialValidationError

ResearchRunState = Literal["queued", "running", "succeeded", "needs_review", "failed"]
GenerationRunState = Literal["running", "succeeded", "completed", "failed"]
ContentPackState = Literal["draft", "ready"]
VariantApprovalState = Literal["draft", "pending_review", "approved", "rejected"]

RESEARCH_RUN_STATES = frozenset({"queued", "running", "succeeded", "needs_review", "failed"})
GENERATION_RUN_STATES = frozenset({"running", "succeeded", "completed", "failed"})
CONTENT_PACK_STATES = frozenset({"draft", "ready"})
VARIANT_APPROVAL_STATES = frozenset({"draft", "pending_review", "approved", "rejected"})

_RESEARCH_RUN_TRANSITIONS = {
    "queued": frozenset({"running", "failed"}),
    "running": frozenset({"succeeded", "needs_review", "failed"}),
    "succeeded": frozenset(),
    "needs_review": frozenset({"running"}),
    "failed": frozenset({"running"}),
}
_GENERATION_RUN_TRANSITIONS = {
    "running": frozenset({"succeeded", "completed", "failed"}),
    "succeeded": frozenset(),
    "completed": frozenset(),
    "failed": frozenset({"running"}),
}
_CONTENT_PACK_TRANSITIONS = {
    "draft": frozenset({"ready"}),
    "ready": frozenset({"draft"}),
}
_VARIANT_APPROVAL_TRANSITIONS = {
    "draft": frozenset({"pending_review"}),
    "pending_review": frozenset({"approved", "rejected"}),
    "approved": frozenset(),
    "rejected": frozenset(),
}


@dataclass(frozen=True)
class StateTransition:
    current: str
    target: str
    allowed: bool
    changed: bool


def research_run_transition(current: str, target: ResearchRunState) -> StateTransition:
    return _transition(current, target, RESEARCH_RUN_STATES, _RESEARCH_RUN_TRANSITIONS)


def generation_run_transition(current: str, target: GenerationRunState) -> StateTransition:
    return _transition(current, target, GENERATION_RUN_STATES, _GENERATION_RUN_TRANSITIONS)


def content_pack_transition(current: str, target: ContentPackState) -> StateTransition:
    return _transition(current, target, CONTENT_PACK_STATES, _CONTENT_PACK_TRANSITIONS)


def variant_approval_transition(current: str, target: VariantApprovalState) -> StateTransition:
    return _transition(current, target, VARIANT_APPROVAL_STATES, _VARIANT_APPROVAL_TRANSITIONS)


def require_research_run_transition(current: str, target: ResearchRunState) -> ResearchRunState:
    _require(research_run_transition(current, target), "research run")
    return target


def require_generation_run_transition(current: str, target: GenerationRunState) -> GenerationRunState:
    _require(generation_run_transition(current, target), "generation run")
    return target


def require_content_pack_transition(current: str, target: ContentPackState) -> ContentPackState:
    _require(content_pack_transition(current, target), "content pack")
    return target


def require_variant_approval_transition(
    current: str,
    target: VariantApprovalState,
) -> VariantApprovalState:
    _require(variant_approval_transition(current, target), "variant approval")
    return target


def _require(decision: StateTransition, subject: str) -> None:
    if decision.allowed:
        return
    raise EditorialValidationError(
        f"{subject} cannot transition from {decision.current} to {decision.target}",
        code="state_transition_invalid",
    )


def _transition(
    current: str,
    target: str,
    states: frozenset[str],
    transitions: dict[str, frozenset[str]],
) -> StateTransition:
    if current not in states:
        return StateTransition(current=current, target=target, allowed=False, changed=False)
    if current == target:
        return StateTransition(current=current, target=target, allowed=True, changed=False)
    return StateTransition(
        current=current,
        target=target,
        allowed=target in transitions[current],
        changed=True,
    )
