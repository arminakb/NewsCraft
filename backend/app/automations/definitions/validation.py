from __future__ import annotations

import re
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping
from typing import cast

from pydantic import ValidationError

from app.automations.definitions.artifacts import (
    ArtifactShape,
    CompatibilityStatus,
    legacy_artifact_shape,
    match_input_contract,
    shape_for_output_contract,
)
from app.automations.definitions.registry import NODE_REGISTRY, NodeDefinition
from app.automations.definitions.schemas import (
    GraphValidationResult,
    ValidationFinding,
    WorkflowEdge,
    WorkflowGraphV1,
    graph_sha256,
)

_FORBIDDEN_CONFIG_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "environment",
        "filesystem",
        "job_type",
        "password",
        "prompt_body",
        "roles",
        "scope",
        "scopes",
        "secret",
        "secret_ref",
        "system_template",
        "token",
        "user_template",
    }
)

_REQUIRED_RESOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "manual": ("story_revision_id",),
    "collection_article_added": ("collection_id",),
    "new_source_item": ("source_ids",),
    "research": ("provider_profile_id",),
    "generate_content_pack": ("editorial_profile_id", "provider_profile_id", "prompt_version_ids"),
    "telegram_publish": ("destination_id",),
}


def _finding(
    code: str,
    message: str,
    *,
    node_id: str | None = None,
    edge_index: int | None = None,
    field_path: str | None = None,
    recovery_action: str | None = None,
    severity: str = "error",
) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        message=message,
        node_id=node_id,
        edge_index=edge_index,
        field_path=field_path,
        recovery_action=recovery_action,
    )


def _forbidden_paths(value: object, prefix: str = "config") -> Iterable[str]:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key).casefold()
            path = f"{prefix}.{raw_key}"
            if (
                key in _FORBIDDEN_CONFIG_KEYS
                or key.endswith("_secret")
                or key.endswith("_token")
                or key.endswith("_api_key")
            ):
                yield path
            yield from _forbidden_paths(item, path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _forbidden_paths(item, f"{prefix}.{index}")
    elif isinstance(value, str) and value.casefold().startswith("bearer "):
        yield prefix


def _display_config_path(field_path: str) -> str:
    return field_path.replace("config.", "configuration.", 1) if field_path.startswith("config.") else field_path


def _error_field_path(definition: NodeDefinition, error: Mapping[str, object]) -> str:
    location = error.get("loc")
    if isinstance(location, tuple) or isinstance(location, list):
        if location:
            return "config." + ".".join(str(part) for part in location)
    message = str(error.get("msg", ""))
    for field in definition.config_model.model_fields:
        if re.search(rf"\b{re.escape(field)}\b", message):
            return f"config.{field}"
    return "config"


def _schema_error_message(definition: NodeDefinition, field_path: str, error: Mapping[str, object]) -> str:
    error_type = str(error.get("type", ""))
    raw_context = error.get("ctx")
    context = cast(Mapping[str, object], raw_context) if isinstance(raw_context, Mapping) else {}
    if error_type == "missing":
        reason = "is required."
    elif error_type == "extra_forbidden":
        reason = "is not supported."
    elif error_type == "too_short":
        minimum = context.get("min_length", "the minimum number of")
        reason = f"must contain at least {minimum} item{'s' if minimum != 1 else ''}."
    elif error_type == "too_long":
        maximum = context.get("max_length", "the maximum number of")
        reason = f"must contain at most {maximum} item{'s' if maximum != 1 else ''}."
    else:
        reason = "is invalid."
    return f"{definition.display_name}: {_display_config_path(field_path)} {reason}"


def _validate_node_config(node_id: str, node_type: str, config: dict[str, object]) -> list[ValidationFinding]:
    definition = NODE_REGISTRY.get(node_type)
    if definition is None:
        return [
            _finding(
                "node_type_unsupported",
                "Saved workflow contains a node type that is not supported anymore.",
                node_id=node_id,
                field_path="type",
                recovery_action="Remove this step explicitly; replacement is not applied automatically.",
            )
        ]
    findings = [
        _finding(
            "node_config_invalid",
            f"{definition.display_name}: {_display_config_path(path)} is not supported.",
            node_id=node_id,
            field_path=path,
            recovery_action="Remove the field and select a saved resource by ID.",
        )
        for path in _forbidden_paths(config)
    ]
    try:
        parsed = definition.config_model.model_validate(config)
    except ValidationError as exc:
        findings.extend(
            _finding(
                "node_config_invalid",
                _schema_error_message(definition, field_path := _error_field_path(definition, error), error),
                node_id=node_id,
                field_path=field_path,
                recovery_action="Correct the highlighted field.",
            )
            for error in exc.errors(include_url=False)
        )
        return findings
    values = parsed.model_dump(mode="json")
    for field in _REQUIRED_RESOURCE_FIELDS.get(node_type, ()):
        value = values.get(field)
        if value is None or value == [] or value == "":
            findings.append(
                _finding(
                    "automation_resource_unavailable",
                    f"{definition.display_name}: configuration.{field} is required.",
                    node_id=node_id,
                    field_path=f"config.{field}",
                    recovery_action="Select a saved resource.",
                )
            )
    return findings


_SAVE_BLOCKING_CODES = frozenset(
    {
        "edge_cardinality_invalid",
        "edge_port_invalid",
        "graph_cycle",
        "graph_entry_invalid",
        "graph_output_invalid",
        "graph_unreachable_node",
        "node_config_invalid",
        "node_type_unsupported",
    }
)


def save_blocking_findings(result: GraphValidationResult) -> list[ValidationFinding]:
    """Return definition errors that cannot be retained as an editable draft."""
    return [finding for finding in result.findings if finding.code in _SAVE_BLOCKING_CODES]


def _output_shape(
    graph: WorkflowGraphV1,
    nodes_by_id: Mapping[str, object],
    node_id: str,
    port_name: str,
    cache: dict[tuple[str, str], ArtifactShape],
    visiting: set[tuple[str, str]],
) -> ArtifactShape:
    key = (node_id, port_name)
    if key in cache:
        return cache[key]
    if key in visiting:
        return ArtifactShape(kind=None, capabilities=frozenset(), known=False)
    node = nodes_by_id.get(node_id)
    definition = NODE_REGISTRY.get(node.type) if node is not None and hasattr(node, "type") else None
    port = definition.outputs.get(port_name) if definition is not None else None
    if definition is None or port is None:
        return ArtifactShape(kind=None, capabilities=frozenset(), known=False)
    visiting.add(key)
    upstream: ArtifactShape | None = None
    output_contract = port.output_contract or definition.output_contract
    if output_contract is None:
        # Boundary fallback for historical catalogs; current registry ports all declare contracts.
        legacy_shapes = [legacy_artifact_shape(item) for item in port.artifact_types]
        known_shapes = [item for item in legacy_shapes if item.known]
        if len(known_shapes) == 1:
            shape = known_shapes[0]
        else:
            shape = ArtifactShape(kind=None, capabilities=frozenset(), known=False)
    else:
        incoming = [edge for edge in graph.edges if edge.target_node_id == node_id]
        if len(incoming) == 1:
            edge = incoming[0]
            upstream = _output_shape(graph, nodes_by_id, edge.source_node_id, edge.source_port, cache, visiting)
        shape = shape_for_output_contract(output_contract, upstream)
    visiting.remove(key)
    cache[key] = shape
    return shape


def _edge_compatibility(
    graph: WorkflowGraphV1,
    nodes_by_id: Mapping[str, object],
    edge: WorkflowEdge,
    cache: dict[tuple[str, str], ArtifactShape],
) -> CompatibilityStatus:
    source_node = nodes_by_id.get(edge.source_node_id)
    target_node = nodes_by_id.get(edge.target_node_id)
    source_definition = (
        NODE_REGISTRY.get(source_node.type)
        if source_node is not None and hasattr(source_node, "type")
        else None
    )
    target_definition = (
        NODE_REGISTRY.get(target_node.type)
        if target_node is not None and hasattr(target_node, "type")
        else None
    )
    if source_definition is None or target_definition is None:
        return "incompatible"
    source_port = source_definition.outputs.get(edge.source_port)
    target_port = target_definition.inputs.get(edge.target_port)
    if source_port is None or target_port is None:
        return "incompatible"
    shape = _output_shape(graph, nodes_by_id, edge.source_node_id, edge.source_port, cache, set())
    return match_input_contract(shape, target_port.input_contract or target_definition.input_contract)


def _cycle_nodes(adjacency: dict[str, list[str]], node_ids: set[str]) -> set[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            cycles.add(node_id)
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in adjacency.get(node_id, []):
            visit(child)
            if child in cycles:
                cycles.add(node_id)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in node_ids:
        visit(node_id)
    return cycles


def _ancestors(node_id: str, reverse: dict[str, list[str]]) -> set[str]:
    found: set[str] = set()
    queue = deque(reverse.get(node_id, []))
    while queue:
        candidate = queue.popleft()
        if candidate in found:
            continue
        found.add(candidate)
        queue.extend(reverse.get(candidate, []))
    return found


def validate_graph(graph: WorkflowGraphV1) -> GraphValidationResult:
    findings: list[ValidationFinding] = []
    nodes_by_id = {node.id: node for node in graph.nodes}
    node_counts = Counter(node.id for node in graph.nodes)
    for node_id, count in node_counts.items():
        if count > 1:
            findings.append(
                _finding(
                    "node_config_invalid",
                    "Node IDs must be unique.",
                    node_id=node_id,
                    field_path="id",
                    recovery_action="Assign a unique stable node ID.",
                )
            )
    for node in graph.nodes:
        findings.extend(_validate_node_config(node.id, node.type, node.config))
    for layout_node_id in graph.metadata.layout:
        if layout_node_id not in nodes_by_id:
            findings.append(
                _finding(
                    "node_config_invalid",
                    "Layout references a node that does not exist.",
                    node_id=layout_node_id,
                    field_path=f"metadata.layout.{layout_node_id}",
                    recovery_action="Remove stale layout metadata.",
                )
            )

    entry = nodes_by_id.get(graph.entry_node_id)
    entry_definition = NODE_REGISTRY.get(entry.type) if entry else None
    if entry is None or entry_definition is None or not entry_definition.entry:
        findings.append(
            _finding(
                "graph_entry_invalid",
                "Graph entry must reference one supported trigger node.",
                node_id=graph.entry_node_id or None,
                field_path="entry_node_id",
                    recovery_action=(
                        "Select Manual, Collection article added, New Source Item, or Schedule as the entry."
                    ),
            )
        )
    declared_entries = [node for node in graph.nodes if (NODE_REGISTRY.get(node.type) or _UNKNOWN).entry]
    if len(declared_entries) != 1:
        findings.append(
            _finding(
                "graph_entry_invalid",
                "Graph must contain exactly one trigger node.",
                field_path="nodes",
                recovery_action="Keep one trigger and remove other trigger nodes.",
            )
        )

    adjacency: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)
    input_counts: Counter[tuple[str, str]] = Counter()
    output_counts: Counter[tuple[str, str]] = Counter()
    edge_keys: set[tuple[str, str, str, str]] = set()
    shape_cache: dict[tuple[str, str], ArtifactShape] = {}
    for index, edge in enumerate(graph.edges):
        key = (edge.source_node_id, edge.source_port, edge.target_node_id, edge.target_port)
        if key in edge_keys:
            findings.append(
                _finding(
                    "edge_cardinality_invalid",
                    "Duplicate edge is not allowed.",
                    edge_index=index,
                    recovery_action="Remove the duplicate connection.",
                )
            )
            continue
        edge_keys.add(key)
        source_node = nodes_by_id.get(edge.source_node_id)
        target_node = nodes_by_id.get(edge.target_node_id)
        if source_node is None or target_node is None:
            findings.append(
                _finding(
                    "edge_port_invalid",
                    "Edge references a node that does not exist.",
                    edge_index=index,
                    recovery_action="Reconnect the edge to existing nodes.",
                )
            )
            continue
        if source_node.id == target_node.id:
            findings.append(
                _finding(
                    "graph_cycle",
                    "Self-connections are not allowed.",
                    node_id=source_node.id,
                    edge_index=index,
                    recovery_action="Remove the self-connection.",
                )
            )
            continue
        source_definition = NODE_REGISTRY.get(source_node.type)
        target_definition = NODE_REGISTRY.get(target_node.type)
        if target_definition is not None and target_definition.entry:
            findings.append(
                _finding(
                    "edge_port_invalid",
                    "Trigger nodes cannot receive incoming connections.",
                    node_id=target_node.id,
                    edge_index=index,
                    recovery_action="Keep the trigger first and connect only from its output.",
                )
            )
            continue
        if (
            source_definition is None
            or target_definition is None
            or edge.source_port not in source_definition.outputs
            or edge.target_port not in target_definition.inputs
        ):
            findings.append(
                _finding(
                    "edge_port_invalid",
                    "Edge references an unsupported input or output port.",
                    edge_index=index,
                    recovery_action="Choose compatible ports from the node catalog.",
                )
            )
            continue
        compatibility = _edge_compatibility(graph, nodes_by_id, edge, shape_cache)
        if compatibility == "incompatible":
            findings.append(
                _finding(
                    "edge_port_invalid",
                    "Connected ports require incompatible artifact capabilities or kinds.",
                    edge_index=index,
                    recovery_action="Connect an output whose artifact contract satisfies the input contract.",
                )
            )
            continue
        if compatibility == "incomplete":
            findings.append(
                _finding(
                    "edge_artifact_contract_incomplete",
                    "Artifact compatibility is incomplete until an upstream artifact is available.",
                    edge_index=index,
                    severity="warning",
                    recovery_action="Configure and run the upstream step before activation.",
                )
            )
        adjacency[source_node.id].append(target_node.id)
        reverse[target_node.id].append(source_node.id)
        input_counts[(target_node.id, edge.target_port)] += 1
        output_counts[(source_node.id, edge.source_port)] += 1

    for node in graph.nodes:
        definition = NODE_REGISTRY.get(node.type)
        if definition is None:
            continue
        for name, port in definition.inputs.items():
            count = input_counts[(node.id, name)]
            if port.required and count == 0:
                findings.append(
                    _finding(
                        "edge_cardinality_invalid",
                        "Required input is not connected.",
                        node_id=node.id,
                        field_path=f"inputs.{name}",
                        recovery_action="Connect one compatible predecessor.",
                    )
                )
            if port.max_connections is not None and count > port.max_connections:
                findings.append(
                    _finding(
                        "edge_cardinality_invalid",
                        "Input has too many connections.",
                        node_id=node.id,
                        field_path=f"inputs.{name}",
                        recovery_action="Remove extra incoming connections.",
                    )
                )
        for name, port in definition.outputs.items():
            count = output_counts[(node.id, name)]
            if port.max_connections is not None and count > port.max_connections:
                findings.append(
                    _finding(
                        "edge_cardinality_invalid",
                        "Output has too many connections.",
                        node_id=node.id,
                        field_path=f"outputs.{name}",
                        recovery_action="Remove extra outgoing connections.",
                    )
                )

    cycles = _cycle_nodes(adjacency, set(nodes_by_id))
    if cycles:
        findings.append(
            _finding(
                "graph_cycle",
                "Workflow Graph v1 must be acyclic.",
                node_id=sorted(cycles)[0],
                recovery_action="Remove a connection from the cycle.",
            )
        )

    reachable: set[str] = set()
    queue = deque([graph.entry_node_id])
    while queue:
        candidate = queue.popleft()
        if candidate in reachable or candidate not in nodes_by_id:
            continue
        reachable.add(candidate)
        queue.extend(adjacency.get(candidate, []))
    for node_id in sorted(set(nodes_by_id) - reachable):
        findings.append(
            _finding(
                "graph_unreachable_node",
                "Node is not reachable from the graph entry.",
                node_id=node_id,
                recovery_action="Connect or remove the unreachable node.",
            )
        )

    for output_id in graph.output_node_ids:
        output = nodes_by_id.get(output_id)
        definition = NODE_REGISTRY.get(output.type) if output else None
        if output is None or definition is None or not definition.terminal or adjacency.get(output_id):
            findings.append(
                _finding(
                    "graph_output_invalid",
                    "Output must reference a terminal node with no successor.",
                    node_id=output_id,
                    field_path="output_node_ids",
                    recovery_action="Choose Save to Drafts, Manual package, or Telegram publish.",
                )
            )

    for node in graph.nodes:
        if node.type != "telegram_publish":
            continue
        ancestor_types = {nodes_by_id[item].type for item in _ancestors(node.id, reverse) if item in nodes_by_id}
        if "human_review" not in ancestor_types:
            findings.append(
                _finding(
                    "automation_activation_invalid",
                    "Telegram publication requires an exact Human Review boundary.",
                    node_id=node.id,
                    recovery_action="Add Human Review before Telegram publish.",
                )
            )

    return GraphValidationResult(
        valid=not any(item.severity == "error" for item in findings),
        graph_hash=graph_sha256(graph),
        findings=findings,
    )


_UNKNOWN = NodeDefinition("unknown", "unknown", "Unknown", "", NODE_REGISTRY["save_drafts"].config_model, {}, {})


__all__ = ["save_blocking_findings", "validate_graph"]
