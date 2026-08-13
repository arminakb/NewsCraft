from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.automations.definitions.registry import NODE_REGISTRY
from app.automations.definitions.schemas import WorkflowGraphV1, graph_sha256
from app.automations.definitions.validation import validate_graph

COMPILER_VERSION = "workflow-v1.0"
LEGACY_COMPILER_VERSION = "legacy-route-v1"
_LEGACY_PROJECTION_TYPE = "telegram_route"
_LEGACY_PLAN_KEYS = frozenset({"compiler_version", "projection_type", "route_id"})


class CompilationError(ValueError):
    def __init__(self, code: str, message: str, *, node_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.node_id = node_id


class CompiledStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int = Field(ge=0)
    node_id: str
    node_type: str
    owner: Literal["api", "scheduler", "source", "generation", "publishing", "compiler"]
    job_types: tuple[str, ...] = ()
    config: dict[str, object] = Field(default_factory=dict)


class CompiledWorkflowPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    compiler_version: str = COMPILER_VERSION
    schema_version: Literal[1] = 1
    graph_hash: str
    plan_hash: str
    entry_node_id: str
    trigger_kind: Literal["manual", "schedule", "collection_article_added", "new_source_item"]
    stages: tuple[CompiledStage, ...]
    output_node_ids: tuple[str, ...]
    required_job_types: tuple[str, ...]
    required_resources: tuple[str, ...]
    publishing_node_ids: tuple[str, ...]
    supports_dry_run: bool = True


_TRIGGER_KIND: dict[
    str, Literal["manual", "schedule", "collection_article_added", "new_source_item"]
] = {
    "manual": "manual",
    "schedule": "schedule",
    "collection_article_added": "collection_article_added",
    "new_source_item": "new_source_item",
}


def _ordered_node_ids(graph: WorkflowGraphV1) -> list[str]:
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree: Counter[str] = Counter()
    for edge in graph.edges:
        outgoing[edge.source_node_id].append(edge.target_node_id)
        indegree[edge.target_node_id] += 1
    if any(value > 1 for value in indegree.values()) or any(len(value) > 1 for value in outgoing.values()):
        raise CompilationError(
            "automation_graph_not_linear",
            "Workflow Graph v1 runtime supports one deterministic linear path.",
        )
    ordered: list[str] = []
    queue = deque([graph.entry_node_id])
    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        queue.extend(sorted(outgoing.get(node_id, ())))
    if len(ordered) != len(graph.nodes):
        raise CompilationError("automation_graph_not_linear", "Workflow contains an unsupported execution shape.")
    return ordered


def _resource_refs(graph: WorkflowGraphV1) -> tuple[str, ...]:
    refs: set[str] = set()
    for node in graph.nodes:
        for field, value in node.config.items():
            if field.endswith("_id") and value is not None:
                refs.add(f"{field}:{value}")
            elif field.endswith("_ids") and isinstance(value, list):
                refs.update(f"{field}:{item}" for item in value)
    return tuple(sorted(refs))


def _plan_hash(value: dict[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def compile_graph(graph: WorkflowGraphV1) -> CompiledWorkflowPlan:
    validation = validate_graph(graph)
    compile_errors = [
        item
        for item in validation.findings
        if item.severity == "error" and item.code != "automation_resource_unavailable"
    ]
    if compile_errors:
        first = compile_errors[0]
        raise CompilationError(first.code, first.message, node_id=first.node_id)
    nodes = {node.id: node for node in graph.nodes}
    ordered_ids = _ordered_node_ids(graph)
    entry = nodes[graph.entry_node_id]
    try:
        trigger_kind = _TRIGGER_KIND[entry.type]
    except KeyError:
        raise CompilationError(
            "automation_trigger_unsupported",
            "Workflow trigger cannot start a durable run.",
        ) from None

    stages: list[CompiledStage] = []
    required_jobs: set[str] = set()
    publishing_nodes: list[str] = []
    for ordinal, node_id in enumerate(ordered_ids):
        node = nodes[node_id]
        definition = NODE_REGISTRY[node.type]
        if definition.runtime_status == "unavailable":
            raise CompilationError(
                "automation_node_runtime_unavailable",
                "Workflow node has no safe runtime adapter.",
                node_id=node.id,
            )
        required_jobs.update(definition.runtime_job_types)
        if definition.runtime_owner == "publishing":
            publishing_nodes.append(node.id)
        stages.append(
            CompiledStage(
                ordinal=ordinal,
                node_id=node.id,
                node_type=node.type,
                owner=definition.runtime_owner,
                job_types=definition.runtime_job_types,
                config=dict(node.config),
            )
        )
    semantic = {
        "compiler_version": COMPILER_VERSION,
        "schema_version": 1,
        "graph_hash": graph_sha256(graph),
        "entry_node_id": graph.entry_node_id,
        "trigger_kind": trigger_kind,
        "stages": [item.model_dump(mode="json") for item in stages],
        "output_node_ids": sorted(graph.output_node_ids),
        "required_job_types": sorted(required_jobs),
        "required_resources": list(_resource_refs(graph)),
        "publishing_node_ids": sorted(publishing_nodes),
        "supports_dry_run": True,
    }
    return CompiledWorkflowPlan(
        compiler_version=COMPILER_VERSION,
        schema_version=1,
        graph_hash=graph_sha256(graph),
        plan_hash=_plan_hash(semantic),
        entry_node_id=graph.entry_node_id,
        trigger_kind=trigger_kind,
        stages=tuple(stages),
        output_node_ids=tuple(sorted(graph.output_node_ids)),
        required_job_types=tuple(sorted(required_jobs)),
        required_resources=_resource_refs(graph),
        publishing_node_ids=tuple(sorted(publishing_nodes)),
        supports_dry_run=True,
    )


def stage(plan: CompiledWorkflowPlan, node_type: str) -> CompiledStage | None:
    """Return the first compiled stage of ``node_type``, or ``None``."""

    return next((item for item in plan.stages if item.node_type == node_type), None)


def node_map(plan: CompiledWorkflowPlan) -> dict[str, list[str]]:
    """Group the plan's node ids by node type, preserving stage order."""

    grouped: dict[str, list[str]] = {}
    for item in plan.stages:
        grouped.setdefault(item.node_type, []).append(item.node_id)
    return grouped


def compiled_plan_data(graph: WorkflowGraphV1) -> dict[str, object]:
    return compile_graph(graph).model_dump(mode="json")


def verify_compiled_plan(graph: WorkflowGraphV1, raw_plan: dict[str, object]) -> CompiledWorkflowPlan:
    """Return the plan a run may execute, refusing one that has drifted from the graph.

    The stored ``compiled_plan`` is a drift assertion, not a cache: the graph is
    recompiled on every call and the stored plan is returned only while it still
    matches. Callers therefore pay one ``compile_graph`` per verification and must
    not compile again themselves.

    Versions backfilled by migration 0027 carry the ``legacy-route-v1``
    placeholder, which records no stages and so has nothing to compare against.
    Those are executed from a freshly compiled plan, but only when the row really
    is that placeholder — anything else claiming the legacy version is treated as
    stale rather than trusted unread.
    """

    if raw_plan.get("compiler_version") == LEGACY_COMPILER_VERSION:
        if set(raw_plan) != _LEGACY_PLAN_KEYS or raw_plan.get("projection_type") != _LEGACY_PROJECTION_TYPE:
            raise CompilationError(
                "automation_compiled_plan_stale",
                "Saved execution plan must be recompiled as a new version.",
            )
        return compile_graph(graph)
    saved = CompiledWorkflowPlan.model_validate(raw_plan)
    current = compile_graph(graph)
    if saved.compiler_version != current.compiler_version or saved.plan_hash != current.plan_hash:
        raise CompilationError(
            "automation_compiled_plan_stale",
            "Saved execution plan must be recompiled as a new version.",
        )
    return saved


__all__ = [
    "COMPILER_VERSION",
    "LEGACY_COMPILER_VERSION",
    "CompilationError",
    "CompiledStage",
    "CompiledWorkflowPlan",
    "compile_graph",
    "compiled_plan_data",
    "node_map",
    "stage",
    "verify_compiled_plan",
]
