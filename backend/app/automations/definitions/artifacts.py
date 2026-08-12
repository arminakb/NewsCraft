from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.automations.definitions.schemas import (
    ArtifactCapability,
    ArtifactInputContract,
    ArtifactKind,
    ArtifactOutputContract,
    WorkflowArtifact,
    WorkflowArtifactContext,
    WorkflowArtifactTrigger,
)

CompatibilityStatus = Literal["compatible", "incomplete", "incompatible"]


@dataclass(frozen=True, slots=True)
class ArtifactShape:
    kind: ArtifactKind | None
    capabilities: frozenset[ArtifactCapability]
    known: bool = True


_LEGACY_ARTIFACTS: dict[str, tuple[ArtifactKind, tuple[ArtifactCapability, ...]]] = {
    "package": ("draft", ("textual", "structured", "draft", "reviewable")),
    "article_package": (
        "article",
        ("textual", "structured", "article", "reviewable", "generatable"),
    ),
    "research_package": (
        "research",
        ("textual", "structured", "research", "reviewable", "generatable"),
    ),
    "draft_package": ("draft", ("textual", "structured", "draft", "reviewable")),
    "content_package": ("draft", ("textual", "structured", "draft", "reviewable")),
    "story.revision_ref": (
        "article",
        ("textual", "structured", "article", "reviewable", "generatable"),
    ),
    "story.researched_revision_ref": (
        "research",
        ("textual", "structured", "research", "reviewable", "generatable"),
    ),
    "article.collection_added": (
        "article",
        ("textual", "structured", "article", "reviewable", "generatable", "collection-context"),
    ),
    "source_item.ref": (
        "article",
        ("textual", "structured", "article", "reviewable", "generatable", "source-context"),
    ),
    "content_item.ref": (
        "article",
        ("textual", "structured", "article", "reviewable", "generatable", "source-context"),
    ),
    "run.signal": ("schedule_event", ("structured", "schedule-context")),
    "story.revision_set_ref": (
        "article",
        ("textual", "structured", "article", "reviewable", "generatable"),
    ),
    "draft.revision_set_ref": (
        "draft",
        ("textual", "structured", "draft", "reviewable"),
    ),
    "draft.validated_revision_set_ref": (
        "draft",
        ("textual", "structured", "draft", "reviewable"),
    ),
    "draft.telegram_revision_ref": (
        "draft",
        ("textual", "structured", "draft", "reviewable"),
    ),
    "draft.approved_telegram_revision_ref": (
        "draft",
        ("textual", "structured", "draft", "reviewable", "approved", "publishable"),
    ),
    "export.manual_package_ref": (
        "draft",
        ("textual", "structured", "draft", "reviewable"),
    ),
    "publication.telegram_ref": (
        "publication",
        ("structured", "approved", "publishable"),
    ),
}

_NODE_DEFAULTS: dict[str, tuple[ArtifactKind, tuple[ArtifactCapability, ...]]] = {
    "manual": _LEGACY_ARTIFACTS["story.revision_ref"],
    "collection_article_added": _LEGACY_ARTIFACTS["article.collection_added"],
    "new_source_item": _LEGACY_ARTIFACTS["source_item.ref"],
    "schedule": _LEGACY_ARTIFACTS["run.signal"],
    "select_content": _LEGACY_ARTIFACTS["story.revision_set_ref"],
    "research": _LEGACY_ARTIFACTS["story.researched_revision_ref"],
    "generate_content_pack": _LEGACY_ARTIFACTS["draft.revision_set_ref"],
    "manual_package": _LEGACY_ARTIFACTS["export.manual_package_ref"],
    "telegram_publish": _LEGACY_ARTIFACTS["publication.telegram_ref"],
}


def _as_mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    return current if current.tzinfo is not None else current.replace(tzinfo=UTC)


def make_artifact(
    *,
    kind: ArtifactKind,
    capabilities: tuple[ArtifactCapability, ...] | list[ArtifactCapability],
    payload: object,
    source_node_id: str,
    workflow_id: str | None = None,
    workflow_version_id: str | None = None,
    run_id: str | None = None,
    trigger_type: str | None = None,
    occurred_at: datetime | None = None,
    metadata: Mapping[str, object] | None = None,
) -> WorkflowArtifact[object]:
    trigger = (
        WorkflowArtifactTrigger(type=trigger_type, occurred_at=_utc(occurred_at))
        if trigger_type is not None
        else None
    )
    context = WorkflowArtifactContext(
        source_node_id=source_node_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        run_id=run_id,
        trigger=trigger,
    )
    return WorkflowArtifact[object](
        kind=kind,
        capabilities=list(dict.fromkeys(capabilities)),
        payload=payload,
        context=context,
        metadata=dict(metadata) if metadata is not None else None,
    )


def legacy_artifact_shape(artifact_type: str) -> ArtifactShape:
    definition = _LEGACY_ARTIFACTS.get(artifact_type)
    if definition is None:
        return ArtifactShape(kind=None, capabilities=frozenset(), known=False)
    kind, capabilities = definition
    return ArtifactShape(kind=kind, capabilities=frozenset(capabilities))


def shape_for_output_contract(
    contract: ArtifactOutputContract | None,
    upstream: ArtifactShape | None = None,
) -> ArtifactShape:
    if contract is None:
        return ArtifactShape(kind=None, capabilities=frozenset(), known=False)
    if contract.preserves_input_artifact:
        base = upstream or ArtifactShape(kind=None, capabilities=frozenset(), known=False)
        return ArtifactShape(
            kind=contract.kind or base.kind,
            capabilities=base.capabilities
            | frozenset(contract.capabilities)
            | frozenset(contract.adds_capabilities),
            known=base.known and (contract.kind is not None or base.kind is not None),
        )
    return ArtifactShape(
        kind=contract.kind,
        capabilities=frozenset(contract.capabilities) | frozenset(contract.adds_capabilities),
        known=contract.kind is not None,
    )


def match_input_contract(
    shape: ArtifactShape,
    contract: ArtifactInputContract | None,
) -> CompatibilityStatus:
    if contract is None:
        return "incompatible"
    if not shape.known:
        return "incomplete"
    if contract.accepted_kinds and shape.kind not in contract.accepted_kinds:
        return "incompatible"
    if not set(contract.all_of).issubset(shape.capabilities):
        return "incompatible"
    if contract.any_of and not (set(contract.any_of) & shape.capabilities):
        return "incompatible"
    return "compatible"


def normalize_artifact(
    value: object,
    *,
    source_node_id: str,
    workflow_id: str | None = None,
    workflow_version_id: str | None = None,
    run_id: str | None = None,
    trigger_type: str | None = None,
) -> WorkflowArtifact[object] | None:
    if isinstance(value, WorkflowArtifact):
        return value
    mapping = _as_mapping(value)
    if mapping is None:
        return None
    nested = mapping.get("artifact")
    if nested is not None:
        normalized_nested = normalize_artifact(
            nested,
            source_node_id=source_node_id,
            workflow_id=workflow_id,
            workflow_version_id=workflow_version_id,
            run_id=run_id,
            trigger_type=trigger_type,
        )
        if normalized_nested is not None:
            return normalized_nested
    if "kind" in mapping and "capabilities" in mapping and "payload" in mapping and "context" in mapping:
        try:
            return WorkflowArtifact[object].model_validate(mapping)
        except ValueError:
            return None
    legacy_type = mapping.get("artifact_type") or mapping.get("artifactType")
    if not isinstance(legacy_type, str):
        return None
    definition = _LEGACY_ARTIFACTS.get(legacy_type)
    if definition is None:
        return None
    kind, capabilities = definition
    return make_artifact(
        kind=kind,
        capabilities=capabilities,
        payload=dict(mapping),
        source_node_id=source_node_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        run_id=run_id,
        trigger_type=trigger_type,
    )


def artifact_for_result(
    result: Mapping[str, object],
    *,
    node_type: str,
    source_node_id: str,
    workflow_id: str | None = None,
    workflow_version_id: str | None = None,
    run_id: str | None = None,
    trigger_type: str | None = None,
) -> WorkflowArtifact[object] | None:
    existing = normalize_artifact(
        result,
        source_node_id=source_node_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        run_id=run_id,
        trigger_type=trigger_type,
    )
    if existing is not None:
        return existing
    definition = _NODE_DEFAULTS.get(node_type)
    if definition is None:
        return None
    kind, capabilities = definition
    payload = result.get("output", result)
    trigger_value = _as_mapping(result.get("trigger"))
    if trigger_value is None and isinstance(payload, Mapping):
        trigger_value = _as_mapping(payload.get("trigger"))
    resolved_trigger_type = trigger_type
    resolved_occurred_at = None
    if trigger_value is not None:
        raw_type = trigger_value.get("type")
        if isinstance(raw_type, str):
            resolved_trigger_type = resolved_trigger_type or raw_type
        raw_occurred_at = trigger_value.get("occurred_at") or trigger_value.get("occurredAt")
        if isinstance(raw_occurred_at, str):
            try:
                resolved_occurred_at = datetime.fromisoformat(raw_occurred_at.replace("Z", "+00:00"))
            except ValueError:
                resolved_occurred_at = None
    return make_artifact(
        kind=kind,
        capabilities=capabilities,
        payload=payload,
        source_node_id=source_node_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        run_id=run_id,
        trigger_type=resolved_trigger_type,
        occurred_at=resolved_occurred_at,
    )


def summary_with_artifact(
    summary: Mapping[str, object] | None,
    artifact: WorkflowArtifact[object],
) -> dict[str, object]:
    result = dict(summary or {})
    result["artifact"] = artifact.model_dump(mode="json")
    return result


def review_artifact(
    artifact: WorkflowArtifact[object],
    *,
    approved: bool,
    eligible_for_publication: bool = False,
    metadata: Mapping[str, object] | None = None,
) -> WorkflowArtifact[object]:
    capabilities = list(artifact.capabilities)
    if approved and "approved" not in capabilities:
        capabilities.append("approved")
    if approved and eligible_for_publication and "publishable" not in capabilities:
        capabilities.append("publishable")
    merged_metadata = dict(artifact.metadata or {})
    if metadata:
        merged_metadata.update(metadata)
    merged_metadata["review"] = {"approved": approved}
    return artifact.model_copy(update={"capabilities": capabilities, "metadata": merged_metadata})


def normalize_summary(
    summary: Mapping[str, object] | None,
    *,
    node_type: str,
    source_node_id: str,
    workflow_id: str | None = None,
    workflow_version_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    result = dict(summary or {})
    artifact = artifact_for_result(
        result,
        node_type=node_type,
        source_node_id=source_node_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        run_id=run_id,
    )
    return summary_with_artifact(result, artifact) if artifact is not None else result


__all__ = [
    "ArtifactShape",
    "CompatibilityStatus",
    "artifact_for_result",
    "legacy_artifact_shape",
    "make_artifact",
    "match_input_contract",
    "normalize_artifact",
    "normalize_summary",
    "review_artifact",
    "shape_for_output_contract",
    "summary_with_artifact",
]
