from __future__ import annotations

from enum import StrEnum


class WorkflowState(StrEnum):
    CREATED = "created"
    SELECTING = "selecting"
    SHORTLIST_READY = "shortlist_ready"
    SHORTLIST_APPROVAL_PENDING = "shortlist_approval_pending"
    SHORTLIST_APPROVED = "shortlist_approved"
    SHORTLIST_REJECTED = "shortlist_rejected"
    SUFFICIENCY_CHECKING = "sufficiency_checking"
    SUFFICIENCY_SUFFICIENT = "sufficiency_sufficient"
    SUFFICIENCY_PARTIAL = "sufficiency_partial"
    SUFFICIENCY_INSUFFICIENT = "sufficiency_insufficient"
    ARTICLE_EXTRACTING = "article_extracting"
    ARTICLE_EXTRACTED = "article_extracted"
    ENRICHING = "enriching"
    ENRICHED = "enriched"
    BRIEFING = "briefing"
    BRIEF_READY = "brief_ready"
    DRAFTING = "drafting"
    DRAFT_READY = "draft_ready"
    QUALITY_CHECKING = "quality_checking"
    QUALITY_PASSED = "quality_passed"
    QUALITY_FAILED = "quality_failed"
    MEDIA_RESOLVING = "media_resolving"
    MEDIA_READY = "media_ready"
    IMAGE_GENERATION_PENDING = "image_generation_pending"
    IMAGE_GENERATING = "image_generating"
    IMAGE_READY = "image_ready"
    PACKAGING = "packaging"
    PACKAGE_READY = "package_ready"
    FINAL_APPROVAL_PENDING = "final_approval_pending"
    FINAL_APPROVED = "final_approved"
    FINAL_REJECTED = "final_rejected"
    REVISION_REQUESTED = "revision_requested"
    DISPATCH_PENDING = "dispatch_pending"
    DISPATCHING = "dispatching"
    PUBLISHED = "published"
    DISPATCH_FAILED = "dispatch_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = {
    WorkflowState.SHORTLIST_REJECTED,
    WorkflowState.FINAL_REJECTED,
    WorkflowState.PUBLISHED,
    WorkflowState.FAILED,
    WorkflowState.CANCELLED,
}

VALID_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.CREATED: {
        WorkflowState.SELECTING,
        WorkflowState.CANCELLED,
        WorkflowState.FAILED,
    },
    WorkflowState.SELECTING: {
        WorkflowState.SHORTLIST_READY,
        WorkflowState.FAILED,
    },
    WorkflowState.SHORTLIST_READY: {
        WorkflowState.SHORTLIST_APPROVAL_PENDING,
        WorkflowState.FAILED,
    },
    WorkflowState.SHORTLIST_APPROVAL_PENDING: {
        WorkflowState.SHORTLIST_APPROVED,
        WorkflowState.SHORTLIST_REJECTED,
        WorkflowState.SELECTING,
        WorkflowState.CANCELLED,
        WorkflowState.FAILED,
    },
    WorkflowState.SHORTLIST_APPROVED: {
        WorkflowState.SUFFICIENCY_CHECKING,
        WorkflowState.FAILED,
    },
    WorkflowState.SUFFICIENCY_CHECKING: {
        WorkflowState.SUFFICIENCY_SUFFICIENT,
        WorkflowState.SUFFICIENCY_PARTIAL,
        WorkflowState.SUFFICIENCY_INSUFFICIENT,
        WorkflowState.FAILED,
    },
    WorkflowState.SUFFICIENCY_SUFFICIENT: {
        WorkflowState.BRIEFING,
        WorkflowState.FAILED,
    },
    WorkflowState.SUFFICIENCY_PARTIAL: {
        WorkflowState.ARTICLE_EXTRACTING,
        WorkflowState.ENRICHING,
        WorkflowState.FAILED,
    },
    WorkflowState.SUFFICIENCY_INSUFFICIENT: {
        WorkflowState.ARTICLE_EXTRACTING,
        WorkflowState.ENRICHING,
        WorkflowState.CANCELLED,
        WorkflowState.FAILED,
    },
    WorkflowState.ARTICLE_EXTRACTING: {
        WorkflowState.ARTICLE_EXTRACTED,
        WorkflowState.ENRICHING,
        WorkflowState.FAILED,
    },
    WorkflowState.ARTICLE_EXTRACTED: {
        WorkflowState.SUFFICIENCY_CHECKING,
        WorkflowState.ENRICHING,
        WorkflowState.FAILED,
    },
    WorkflowState.ENRICHING: {
        WorkflowState.ENRICHED,
        WorkflowState.FAILED,
    },
    WorkflowState.ENRICHED: {
        WorkflowState.SUFFICIENCY_CHECKING,
        WorkflowState.BRIEFING,
        WorkflowState.FAILED,
    },
    WorkflowState.BRIEFING: {
        WorkflowState.BRIEF_READY,
        WorkflowState.FAILED,
    },
    WorkflowState.BRIEF_READY: {
        WorkflowState.DRAFTING,
        WorkflowState.FAILED,
    },
    WorkflowState.DRAFTING: {
        WorkflowState.DRAFT_READY,
        WorkflowState.FAILED,
    },
    WorkflowState.DRAFT_READY: {
        WorkflowState.QUALITY_CHECKING,
        WorkflowState.FAILED,
    },
    WorkflowState.QUALITY_CHECKING: {
        WorkflowState.QUALITY_PASSED,
        WorkflowState.QUALITY_FAILED,
        WorkflowState.REVISION_REQUESTED,
        WorkflowState.FAILED,
    },
    WorkflowState.QUALITY_FAILED: {
        WorkflowState.REVISION_REQUESTED,
        WorkflowState.FAILED,
    },
    WorkflowState.REVISION_REQUESTED: {
        WorkflowState.BRIEFING,
        WorkflowState.DRAFTING,
        WorkflowState.QUALITY_CHECKING,
        WorkflowState.FINAL_APPROVAL_PENDING,
        WorkflowState.CANCELLED,
        WorkflowState.FAILED,
    },
    WorkflowState.QUALITY_PASSED: {
        WorkflowState.MEDIA_RESOLVING,
        WorkflowState.FAILED,
    },
    WorkflowState.MEDIA_RESOLVING: {
        WorkflowState.MEDIA_READY,
        WorkflowState.IMAGE_GENERATION_PENDING,
        WorkflowState.FAILED,
    },
    WorkflowState.IMAGE_GENERATION_PENDING: {
        WorkflowState.IMAGE_GENERATING,
        WorkflowState.PACKAGING,
        WorkflowState.FAILED,
    },
    WorkflowState.IMAGE_GENERATING: {
        WorkflowState.IMAGE_READY,
        WorkflowState.IMAGE_GENERATION_PENDING,
        WorkflowState.FAILED,
    },
    WorkflowState.IMAGE_READY: {
        WorkflowState.PACKAGING,
        WorkflowState.FAILED,
    },
    WorkflowState.MEDIA_READY: {
        WorkflowState.PACKAGING,
        WorkflowState.FAILED,
    },
    WorkflowState.PACKAGING: {
        WorkflowState.PACKAGE_READY,
        WorkflowState.FAILED,
    },
    WorkflowState.PACKAGE_READY: {
        WorkflowState.FINAL_APPROVAL_PENDING,
        WorkflowState.FAILED,
    },
    WorkflowState.FINAL_APPROVAL_PENDING: {
        WorkflowState.FINAL_APPROVED,
        WorkflowState.FINAL_REJECTED,
        WorkflowState.REVISION_REQUESTED,
        WorkflowState.FAILED,
    },
    WorkflowState.FINAL_APPROVED: {
        WorkflowState.DISPATCH_PENDING,
        WorkflowState.FAILED,
    },
    WorkflowState.DISPATCH_PENDING: {
        WorkflowState.DISPATCHING,
        WorkflowState.DISPATCH_FAILED,
        WorkflowState.FAILED,
    },
    WorkflowState.DISPATCHING: {
        WorkflowState.PUBLISHED,
        WorkflowState.DISPATCH_FAILED,
        WorkflowState.FAILED,
    },
    WorkflowState.DISPATCH_FAILED: {
        WorkflowState.DISPATCH_PENDING,
        WorkflowState.FAILED,
    },
}


class InvalidWorkflowTransition(ValueError):
    pass


def coerce_state(value: WorkflowState | str) -> WorkflowState:
    return value if isinstance(value, WorkflowState) else WorkflowState(value)


def is_valid_transition(from_state: WorkflowState | str, to_state: WorkflowState | str) -> bool:
    source = coerce_state(from_state)
    target = coerce_state(to_state)
    return target in VALID_TRANSITIONS.get(source, set())


def require_valid_transition(from_state: WorkflowState | str, to_state: WorkflowState | str) -> None:
    source = coerce_state(from_state)
    target = coerce_state(to_state)
    if not is_valid_transition(source, target):
        raise InvalidWorkflowTransition(f"invalid workflow transition: {source.value} -> {target.value}")
