from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

NodeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
EntryNodeId = Annotated[str, StringConstraints(pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9_-]{0,127})?$")]
Lifecycle = Literal["inactive", "active", "paused", "archived"]
FindingSeverity = Literal["error", "warning"]
ResourceKind = Literal[
    "source",
    "provider",
    "prompt_version",
    "editorial_profile",
    "destination",
    "collection",
]
ResourceState = Literal["ready", "disabled", "stale", "unavailable", "not_configured"]
PreviewPlatform = Literal["telegram", "instagram", "x", "blog", "draft", "multi", "unknown"]
PreviewCategory = Literal["trigger", "content", "ai", "validation", "review", "draft", "publish", "unknown"]


class WorkflowLayoutPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(ge=-100_000, le=100_000)
    y: float = Field(ge=-100_000, le=100_000)


class WorkflowMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    layout: dict[NodeId, WorkflowLayoutPoint] = Field(default_factory=dict)


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NodeId
    type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    config: dict[str, object] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_node_id: NodeId
    source_port: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    target_node_id: NodeId
    target_port: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")


class WorkflowGraphV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    entry_node_id: EntryNodeId
    nodes: list[WorkflowNode] = Field(max_length=30)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=60)
    output_node_ids: list[NodeId] = Field(max_length=30)
    metadata: WorkflowMetadata = Field(default_factory=WorkflowMetadata)

    @field_validator("output_node_ids")
    @classmethod
    def unique_output_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("output_node_ids must be unique")
        return value

    @model_validator(mode="after")
    def empty_graph_has_no_runtime_state(self) -> WorkflowGraphV1:
        if self.nodes:
            return self
        if self.entry_node_id or self.edges or self.output_node_ids or self.metadata.layout:
            raise ValueError("An empty workflow graph must not contain nodes, edges, outputs, or layout.")
        return self


def canonical_graph_data(graph: WorkflowGraphV1) -> dict[str, object]:
    value = graph.model_dump(mode="json", exclude_none=True)
    value["nodes"] = sorted(value["nodes"], key=lambda item: item["id"])  # type: ignore[index,return-value]
    value["edges"] = sorted(  # type: ignore[assignment]
        value["edges"],  # type: ignore[arg-type]
        key=lambda item: (
            item["source_node_id"],
            item["source_port"],
            item["target_node_id"],
            item["target_port"],
        ),
    )
    value["output_node_ids"] = sorted(value["output_node_ids"])  # type: ignore[arg-type,assignment]
    metadata = value.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("layout"), dict):
        metadata["layout"] = dict(sorted(metadata["layout"].items()))
    return value


def canonical_graph_json(graph: WorkflowGraphV1) -> str:
    return json.dumps(canonical_graph_data(graph), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def graph_sha256(graph: WorkflowGraphV1) -> str:
    return hashlib.sha256(canonical_graph_json(graph).encode("utf-8")).hexdigest()


class ValidationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: FindingSeverity
    message: str
    node_id: NodeId | None = None
    edge_index: int | None = None
    field_path: str | None = None
    recovery_action: str | None = None


class GraphValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    graph_hash: str
    findings: list[ValidationFinding]


class AutomationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    graph: WorkflowGraphV1
    creation_reason: str = Field(default="automation created", min_length=1, max_length=240)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class AutomationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class AutomationVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    graph: WorkflowGraphV1
    creation_reason: str = Field(default="draft saved", min_length=1, max_length=240)


class AutomationVersionRestore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    creation_reason: str = Field(default="version restored as draft", min_length=1, max_length=240)


class AutomationLifecycleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class AutomationRunStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_number: int | None = Field(default=None, ge=1)
    dry_run: bool = True
    source_message_id: int | None = Field(default=None, ge=1)
    story_id: UUID | None = None
    story_revision_id: UUID | None = None

    @model_validator(mode="after")
    def one_story_input(self) -> AutomationRunStart:
        if self.story_id is not None and self.story_revision_id is not None:
            raise ValueError("story_id and story_revision_id are mutually exclusive")
        return self


class AutomationNodeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    automation_run_id: UUID
    node_id: str
    attempt: int
    status: str
    workflow_job_id: UUID | None
    automation_dispatch_id: UUID | None
    research_run_id: UUID | None
    generation_run_id: UUID | None
    platform_variant_revision_id: UUID | None
    publish_job_id: UUID | None
    publication_id: UUID | None
    input_summary: dict[str, object]
    output_summary: dict[str, object]
    usage: dict[str, object]
    retry_metadata: dict[str, object]
    safe_error_code: str | None
    safe_error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class AutomationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    automation_id: UUID
    automation_version_id: UUID
    root_workflow_job_id: UUID | None
    trigger_kind: str
    trigger_metadata: dict[str, object]
    dry_run: bool
    status: str
    current_node_id: str | None
    resource_snapshot: dict[str, object]
    safe_error_code: str | None
    safe_error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    nodes: list[AutomationNodeRunOut] = Field(default_factory=list)


class AutomationRunPageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AutomationRunOut]
    next_cursor: str | None


class AutomationVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    automation_id: UUID
    version: int
    schema_version: int
    graph: WorkflowGraphV1
    graph_hash: str
    compiler_version: str | None
    compiled_plan: dict[str, object]
    validation_summary: dict[str, object]
    creation_actor_type: str
    creation_actor_id: str
    creation_reason: str
    created_at: datetime


class AutomationPreviewStageOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: NodeId
    node_type: str
    label: str
    category: PreviewCategory
    platforms: list[PreviewPlatform] = Field(max_length=4)
    needs_attention: bool


class AutomationPreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    version_state: Literal["active", "draft"]
    stages: list[AutomationPreviewStageOut] = Field(max_length=30)
    output_platforms: list[PreviewPlatform] = Field(min_length=1, max_length=4)
    valid: bool | None
    run_count: int = Field(ge=0)
    success_rate: int | None = Field(ge=0, le=100)
    last_run_at: datetime | None
    last_outcome: str | None


class AutomationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    name: str
    description: str | None
    lifecycle: Lifecycle
    owner_type: str
    revision: int
    active_version_id: UUID | None
    draft_version_id: UUID | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    preview: AutomationPreviewOut | None = None


class AutomationDetailOut(AutomationOut):
    draft_version: AutomationVersionOut | None = None
    active_version: AutomationVersionOut | None = None
    legacy_route_id: UUID | None = None


class AutomationPageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AutomationOut]
    next_cursor: str | None


class AutomationVersionPageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AutomationVersionOut]
    next_cursor: str | None


class PortCatalogOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    artifact_types: list[str]
    required: bool = True
    max_connections: int | None = None


class NodeCatalogItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    family: str
    display_name: str
    description: str
    entry: bool
    terminal: bool
    runtime_status: Literal["existing", "extension", "unavailable"]
    runtime_owner: Literal["api", "scheduler", "source", "generation", "publishing", "compiler"]
    runtime_job_types: list[str]
    inputs: list[PortCatalogOut]
    outputs: list[PortCatalogOut]
    config_schema: dict[str, object]
    ui_hints: dict[str, object]


class AutomationNodeCatalogOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    max_nodes: int = 30
    max_edges: int = 60
    nodes: list[NodeCatalogItemOut]


class ResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ResourceKind
    id: UUID


class AutomationResourceCatalogIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resources: list[ResourceRequest] = Field(default_factory=list, max_length=100)
    automation_id: UUID | None = None


class AutomationResourceOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    kind: ResourceKind
    display_name: str
    state: ResourceState
    reason_code: str | None
    capabilities: list[str]
    referenced_by_active_version: bool
    manage_href: str


class AutomationResourceCatalogOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resources: list[AutomationResourceOut]


class AutomationTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    seed_key: str
    seed_version: int
    ownership: str
    name: str
    description: str
    complexity: str
    graph_seed: WorkflowGraphV1
    capability_requirements: list[str]
    created_at: datetime
    updated_at: datetime


class TemplateCreateAutomationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


__all__ = [
    "AutomationCreate",
    "AutomationDetailOut",
    "AutomationLifecycleInput",
    "AutomationNodeRunOut",
    "AutomationNodeCatalogOut",
    "AutomationOut",
    "AutomationPageOut",
    "AutomationPreviewOut",
    "AutomationPreviewStageOut",
    "AutomationPatch",
    "AutomationResourceCatalogIn",
    "AutomationResourceCatalogOut",
    "AutomationResourceOut",
    "AutomationRunOut",
    "AutomationRunPageOut",
    "AutomationRunStart",
    "AutomationTemplateOut",
    "AutomationVersionCreate",
    "AutomationVersionOut",
    "AutomationVersionPageOut",
    "AutomationVersionRestore",
    "GraphValidationResult",
    "NodeCatalogItemOut",
    "PortCatalogOut",
    "ResourceKind",
    "ResourceRequest",
    "TemplateCreateAutomationIn",
    "ValidationFinding",
    "WorkflowEdge",
    "WorkflowGraphV1",
    "WorkflowLayoutPoint",
    "WorkflowMetadata",
    "WorkflowNode",
    "canonical_graph_data",
    "canonical_graph_json",
    "graph_sha256",
]
