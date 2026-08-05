import type {
  AutomationNodeCatalog,
  AutomationNodeDefinition,
  AutomationResourceRequest,
  GraphValidation,
  ValidationFinding,
  WorkflowEdge,
  WorkflowGraph,
  WorkflowNode,
} from "./automation-types"

export type GraphEditResult =
  | { graph: WorkflowGraph; error?: never; nodeId?: string }
  | { graph?: never; error: string; nodeId?: never }

export type WorkflowNodeActionState = {
  canDuplicate: boolean
  duplicateReason?: string
  canDelete: boolean
  deleteReason?: string
}

const DUPLICATE_OFFSET = { x: 48, y: 48 }
const TRANSIENT_DUPLICATE_KEYS = new Set([
  "data",
  "dragging",
  "execution",
  "executionresult",
  "executionresults",
  "execution_result",
  "execution_results",
  "handles",
  "handlebounds",
  "handleboundschange",
  "hidden",
  "measured",
  "position",
  "positionabsolute",
  "position_absolute",
  "resizing",
  "runtime",
  "runtimestate",
  "runtime_state",
  "selected",
  "temporary",
  "temporary_state",
  "temporaryuistate",
  "temporary_ui_state",
  "temp_ui_state",
  "temp_uistate",
  "uistate",
  "ui_state",
  "validation",
  "validationerror",
  "validation_error",
  "validationerrors",
  "validation_errors",
])
const INSTANCE_IDENTIFIER_KEYS = new Set(["instanceid", "instance_id"])
const HANDLE_IDENTIFIER_KEYS = new Set(["handleid", "handle_id", "handleids", "handle_ids"])

const requiredResources: Record<string, string[]> = {
  manual: ["storyRevisionId"],
  collection_article_added: ["collectionId"],
  new_source_item: ["sourceIds"],
  research: ["providerProfileId"],
  generate_content_pack: ["editorialProfileId", "providerProfileId", "promptVersionIds"],
  telegram_publish: ["destinationId"],
}

const resourceFields: Record<string, AutomationResourceRequest["kind"]> = {
  collectionId: "collection",
  sourceId: "source",
  sourceIds: "source",
  providerProfileId: "provider",
  editorialProfileId: "editorial_profile",
  promptTemplateVersionId: "prompt_version",
  promptVersionIds: "prompt_version",
  destinationId: "destination",
}

export function catalogDefinition(catalog: AutomationNodeCatalog, type: string) {
  return catalog.nodes.find((item) => item.type === type)
}

export function workflowNodeActionState(
  graph: WorkflowGraph,
  catalog: AutomationNodeCatalog,
  nodeId: string,
): WorkflowNodeActionState {
  const node = graph.nodes.find((item) => item.id === nodeId)
  if (!node) {
    return {
      canDuplicate: false,
      duplicateReason: "Step no longer exists.",
      canDelete: false,
      deleteReason: "Step no longer exists.",
    }
  }

  const definition = catalogDefinition(catalog, node.type)
  if (!definition) {
    return {
      canDuplicate: false,
      duplicateReason: "Step is not available in the server catalog.",
      canDelete: true,
    }
  }

  const incoming = graph.edges.filter((edge) => edge.targetNodeId === nodeId)
  const outgoing = graph.edges.filter((edge) => edge.sourceNodeId === nodeId)
  let deleteReason: string | undefined
  if (nodeId === graph.entryNodeId || definition.entry) {
    deleteReason = "Workflow Graph v1 requires one trigger. Edit its settings instead."
  } else if (graph.outputNodeIds.includes(nodeId)) {
    deleteReason = "Workflow needs one terminal output. Add another output before deleting this one."
  } else if (incoming.length > 1 || outgoing.length > 1) {
    deleteReason = "Delete supports linear Workflow Graph v1 paths only."
  } else if (incoming[0] && outgoing[0]) {
    const source = graph.nodes.find((item) => item.id === incoming[0].sourceNodeId)
    const target = graph.nodes.find((item) => item.id === outgoing[0].targetNodeId)
    const sourceDefinition = source ? catalogDefinition(catalog, source.type) : undefined
    const targetDefinition = target ? catalogDefinition(catalog, target.type) : undefined
    if (!source || !target || !sourceDefinition || !targetDefinition || !compatiblePortPairs(sourceDefinition, targetDefinition)[0]) {
      deleteReason = "Deleting this step would leave incompatible neighbors."
    }
  }

  let duplicateReason: string | undefined
  if (definition.entry) {
    duplicateReason = "Workflow Graph v1 supports one trigger. Replace trigger settings instead."
  } else if (definition.terminal) {
    duplicateReason = "Workflow Graph v1 keeps one terminal output at the end of its linear path."
  } else if (graph.nodes.length >= catalog.maxNodes) {
    duplicateReason = `Workflow is limited to ${catalog.maxNodes} steps.`
  }

  return {
    canDuplicate: !duplicateReason,
    duplicateReason,
    canDelete: !deleteReason,
    deleteReason,
  }
}

export function orderedWorkflowNodes(graph: WorkflowGraph): WorkflowNode[] {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]))
  const outgoing = new Map<string, string[]>()
  for (const edge of graph.edges) {
    const values = outgoing.get(edge.sourceNodeId) ?? []
    values.push(edge.targetNodeId)
    outgoing.set(edge.sourceNodeId, values)
  }
  const ordered: WorkflowNode[] = []
  const visited = new Set<string>()
  const visit = (id: string) => {
    if (visited.has(id)) return
    const node = nodes.get(id)
    if (!node) return
    visited.add(id)
    ordered.push(node)
    for (const next of outgoing.get(id) ?? []) visit(next)
  }
  visit(graph.entryNodeId)
  for (const node of graph.nodes) visit(node.id)
  return ordered
}

export function compatiblePortPairs(source: AutomationNodeDefinition, target: AutomationNodeDefinition) {
  return source.outputs.flatMap((output) => target.inputs
    .filter((input) => output.artifactTypes.some((type) => input.artifactTypes.includes(type)))
    .map((input) => ({ sourcePort: output.name, targetPort: input.name })))
}

export function insertWorkflowNode(
  graph: WorkflowGraph,
  catalog: AutomationNodeCatalog,
  type: string,
  afterNodeId?: string | null,
  config?: Record<string, unknown>,
): GraphEditResult {
  const definition = catalogDefinition(catalog, type)
  if (!definition || definition.runtimeStatus === "unavailable") return { error: "Node is unavailable in server catalog." }
  if (graph.nodes.length >= catalog.maxNodes) return { error: `Workflow is limited to ${catalog.maxNodes} steps.` }

  if (!graph.nodes.length) {
    if (!definition.entry) return { error: "Add a trigger before adding workflow steps." }
    const nodeId = uniqueNodeId(graph, type)
    return {
      nodeId,
      graph: {
        ...graph,
        entryNodeId: nodeId,
        nodes: [{ id: nodeId, type, config: config ?? defaultConfig(definition) }],
        edges: [],
        outputNodeIds: definition.terminal ? [nodeId] : [],
        metadata: { layout: { ...graph.metadata.layout, [nodeId]: { x: 80, y: 120 } } },
      },
    }
  }

  if (definition.entry) return { error: "Workflow Graph v1 supports one trigger. Replace trigger settings instead." }

  const ordered = orderedWorkflowNodes(graph)
  const lastNode = ordered.at(-1)
  const lastDefinition = lastNode ? catalogDefinition(catalog, lastNode.type) : undefined
  const fallback = lastDefinition?.terminal && ordered.length > 1 ? ordered.at(-2)?.id : lastNode?.id
  const sourceId = afterNodeId && graph.nodes.some((node) => node.id === afterNodeId) ? afterNodeId : fallback
  const sourceNode = graph.nodes.find((node) => node.id === sourceId)
  if (!sourceNode) return { error: "Choose a step before adding the next step." }
  const sourceDefinition = catalogDefinition(catalog, sourceNode.type)
  if (!sourceDefinition) return { error: "Selected predecessor is not in server catalog." }
  const outgoing = graph.edges.filter((edge) => edge.sourceNodeId === sourceNode.id)
  if (outgoing.length > 1) return { error: "Add-next-step supports linear v1 paths only." }
  const successorEdge = outgoing[0]
  const successorNode = successorEdge
    ? graph.nodes.find((node) => node.id === successorEdge.targetNodeId)
    : undefined
  const successorDefinition = successorNode ? catalogDefinition(catalog, successorNode.type) : undefined
  const firstPair = compatiblePortPairs(sourceDefinition, definition)[0]
  if (!firstPair) return { error: `${definition.displayName} cannot accept output from ${sourceDefinition.displayName}.` }
  const secondPair = successorDefinition ? compatiblePortPairs(definition, successorDefinition)[0] : undefined
  if (successorDefinition && !secondPair) {
    return { error: `${definition.displayName} cannot connect to ${successorDefinition.displayName}.` }
  }
  const nodeId = uniqueNodeId(graph, type)
  const sourcePoint = graph.metadata.layout[sourceNode.id] ?? { x: 80, y: 120 }
  const successorPoint = successorNode ? graph.metadata.layout[successorNode.id] : undefined
  const point = successorPoint
    ? { x: (sourcePoint.x + successorPoint.x) / 2, y: (sourcePoint.y + successorPoint.y) / 2 }
    : { x: sourcePoint.x + 280, y: sourcePoint.y }
  const nextNode: WorkflowNode = { id: nodeId, type, config: config ?? defaultConfig(definition) }
  const nextEdges = graph.edges.filter((edge) => edge !== successorEdge)
  nextEdges.push({
    sourceNodeId: sourceNode.id,
    sourcePort: firstPair.sourcePort,
    targetNodeId: nodeId,
    targetPort: firstPair.targetPort,
  })
  if (successorNode && secondPair) {
    nextEdges.push({
      sourceNodeId: nodeId,
      sourcePort: secondPair.sourcePort,
      targetNodeId: successorNode.id,
      targetPort: secondPair.targetPort,
    })
  }
  const replacesTerminalOutput = !successorNode && graph.outputNodeIds.includes(sourceNode.id)
  const nextOutputNodeIds = successorNode
    ? graph.outputNodeIds
    : definition.terminal
      ? [nodeId]
      : replacesTerminalOutput
        ? []
        : graph.outputNodeIds
  return {
    nodeId,
    graph: {
      ...graph,
      nodes: [...graph.nodes, nextNode],
      edges: nextEdges,
      outputNodeIds: nextOutputNodeIds,
      metadata: { layout: { ...graph.metadata.layout, [nodeId]: point } },
    },
  }
}

export function deleteWorkflowNode(
  graph: WorkflowGraph,
  catalog: AutomationNodeCatalog,
  nodeId: string,
): GraphEditResult {
  const node = graph.nodes.find((item) => item.id === nodeId)
  if (!node) return { error: "Step no longer exists." }
  const actionState = workflowNodeActionState(graph, catalog, nodeId)
  if (!actionState.canDelete) return { error: actionState.deleteReason ?? "Step cannot be deleted." }
  if (!catalogDefinition(catalog, node.type)) {
    const { [nodeId]: _removed, ...layout } = graph.metadata.layout
    return {
      graph: {
        ...graph,
        entryNodeId: graph.entryNodeId === nodeId ? "" : graph.entryNodeId,
        nodes: graph.nodes.filter((item) => item.id !== nodeId),
        edges: graph.edges.filter((edge) => edge.sourceNodeId !== nodeId && edge.targetNodeId !== nodeId),
        outputNodeIds: graph.outputNodeIds.filter((item) => item !== nodeId),
        metadata: { layout },
      },
    }
  }
  const incoming = graph.edges.filter((edge) => edge.targetNodeId === nodeId)
  const outgoing = graph.edges.filter((edge) => edge.sourceNodeId === nodeId)
  const nextEdges = graph.edges.filter((edge) => edge.sourceNodeId !== nodeId && edge.targetNodeId !== nodeId)
  if (incoming[0] && outgoing[0]) {
    const source = graph.nodes.find((item) => item.id === incoming[0].sourceNodeId)
    const target = graph.nodes.find((item) => item.id === outgoing[0].targetNodeId)
    const sourceDefinition = source ? catalogDefinition(catalog, source.type) : undefined
    const targetDefinition = target ? catalogDefinition(catalog, target.type) : undefined
    const pair = sourceDefinition && targetDefinition ? compatiblePortPairs(sourceDefinition, targetDefinition)[0] : undefined
    if (!pair || !source || !target) return { error: "Deleting this step would leave incompatible neighbors." }
    nextEdges.push({ sourceNodeId: source.id, sourcePort: pair.sourcePort, targetNodeId: target.id, targetPort: pair.targetPort })
  }
  const { [nodeId]: _removed, ...layout } = graph.metadata.layout
  return {
    graph: {
      ...graph,
      nodes: graph.nodes.filter((item) => item.id !== nodeId),
      edges: nextEdges,
      outputNodeIds: graph.outputNodeIds.filter((item) => item !== nodeId),
      metadata: { layout },
    },
  }
}

export function duplicateWorkflowNode(
  graph: WorkflowGraph,
  catalog: AutomationNodeCatalog,
  nodeId: string,
): GraphEditResult {
  const node = graph.nodes.find((item) => item.id === nodeId)
  if (!node) return { error: "Step no longer exists." }
  const actionState = workflowNodeActionState(graph, catalog, nodeId)
  if (!actionState.canDuplicate) return { error: actionState.duplicateReason ?? "Step cannot be duplicated." }
  const definition = catalogDefinition(catalog, node.type)
  if (!definition) return { error: "Step is not available in the server catalog." }
  const result = insertWorkflowNode(graph, catalog, node.type, node.id, duplicateEditableConfig(node.config, definition.configSchema as JsonSchema))
  if (!result.graph || !result.nodeId) return result
  const originalPoint = graph.metadata.layout[node.id] ?? { x: 80, y: 120 }
  const point = duplicatePoint(result.graph, result.nodeId, originalPoint)
  return { ...result, graph: updateNodePosition(result.graph, result.nodeId, point) }
}

export function moveWorkflowNode(
  graph: WorkflowGraph,
  catalog: AutomationNodeCatalog,
  nodeId: string,
  direction: -1 | 1,
): GraphEditResult {
  const ordered = orderedWorkflowNodes(graph)
  const index = ordered.findIndex((node) => node.id === nodeId)
  const nextIndex = index + direction
  if (index <= 0 || nextIndex <= 0 || nextIndex >= ordered.length - 1) {
    return { error: "Trigger stays first and terminal output stays last." }
  }
  const reordered = [...ordered]
  ;[reordered[index], reordered[nextIndex]] = [reordered[nextIndex], reordered[index]]
  const edges: WorkflowEdge[] = []
  for (let cursor = 0; cursor < reordered.length - 1; cursor += 1) {
    const source = catalogDefinition(catalog, reordered[cursor].type)
    const target = catalogDefinition(catalog, reordered[cursor + 1].type)
    const pair = source && target ? compatiblePortPairs(source, target)[0] : undefined
    if (!pair) return { error: "Reorder blocked because adjacent ports would be incompatible." }
    edges.push({
      sourceNodeId: reordered[cursor].id,
      sourcePort: pair.sourcePort,
      targetNodeId: reordered[cursor + 1].id,
      targetPort: pair.targetPort,
    })
  }
  return { graph: { ...graph, nodes: reordered, edges } }
}

export function connectWorkflowNodes(
  graph: WorkflowGraph,
  catalog: AutomationNodeCatalog,
  edge: WorkflowEdge,
): GraphEditResult {
  if (edge.sourceNodeId === edge.targetNodeId) return { error: "A step cannot connect to itself." }
  if (graph.edges.some((item) => JSON.stringify(item) === JSON.stringify(edge))) return { error: "Connection already exists." }
  if (graph.edges.length >= catalog.maxEdges) return { error: `Workflow is limited to ${catalog.maxEdges} connections.` }
  const sourceNode = graph.nodes.find((node) => node.id === edge.sourceNodeId)
  const targetNode = graph.nodes.find((node) => node.id === edge.targetNodeId)
  const source = sourceNode ? catalogDefinition(catalog, sourceNode.type) : undefined
  const target = targetNode ? catalogDefinition(catalog, targetNode.type) : undefined
  if (!source || !target) return { error: "Connection references an unavailable step." }
  if (target.entry) return { error: "Trigger steps cannot receive incoming connections." }
  const output = source.outputs.find((port) => port.name === edge.sourcePort)
  const input = target.inputs.find((port) => port.name === edge.targetPort)
  if (!output || !input || !output.artifactTypes.some((type) => input.artifactTypes.includes(type))) {
    return { error: `Ports ${edge.sourcePort} and ${edge.targetPort} are incompatible.` }
  }
  const outgoingCount = graph.edges.filter((item) => item.sourceNodeId === edge.sourceNodeId && item.sourcePort === edge.sourcePort).length
  const incomingCount = graph.edges.filter((item) => item.targetNodeId === edge.targetNodeId && item.targetPort === edge.targetPort).length
  if (output.maxConnections !== null && output.maxConnections !== undefined && outgoingCount >= output.maxConnections) {
    return { error: `Output ${edge.sourcePort} already reached its connection limit.` }
  }
  if (input.maxConnections !== null && input.maxConnections !== undefined && incomingCount >= input.maxConnections) {
    return { error: `Input ${edge.targetPort} already reached its connection limit.` }
  }
  const candidate = { ...graph, edges: [...graph.edges, edge] }
  if (hasCycle(candidate)) return { error: "Workflow Graph v1 cannot contain cycles." }
  return { graph: candidate }
}

export function updateNodeConfig(graph: WorkflowGraph, nodeId: string, config: Record<string, unknown>): WorkflowGraph {
  return { ...graph, nodes: graph.nodes.map((node) => node.id === nodeId ? { ...node, config } : node) }
}

export function updateNodePosition(graph: WorkflowGraph, nodeId: string, point: { x: number; y: number }): WorkflowGraph {
  return { ...graph, metadata: { layout: { ...graph.metadata.layout, [nodeId]: point } } }
}

export function workflowResourceRequests(graph: WorkflowGraph): AutomationResourceRequest[] {
  const values = new Map<string, AutomationResourceRequest>()
  for (const node of graph.nodes) {
    for (const [field, kind] of Object.entries(resourceFields)) {
      const raw = node.config[field]
      const ids = Array.isArray(raw) ? raw : [raw]
      for (const id of ids) {
        if (typeof id !== "string" || !id) continue
        values.set(`${kind}:${id}`, { kind, id })
      }
    }
  }
  return [...values.values()].sort((a, b) => `${a.kind}:${a.id}`.localeCompare(`${b.kind}:${b.id}`))
}

export function validateWorkflowClient(graph: WorkflowGraph, catalog: AutomationNodeCatalog): GraphValidation {
  const findings: ValidationFinding[] = []
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]))
  const inputCounts = new Map<string, number>()
  const outputCounts = new Map<string, number>()
  const edgeKeys = new Set<string>()
  const entry = nodes.get(graph.entryNodeId)
  const entryDefinition = entry ? catalogDefinition(catalog, entry.type) : undefined
  if (!entryDefinition?.entry) findings.push(finding("graph_entry_invalid", "Choose one supported trigger.", graph.entryNodeId, "Select Manual, Collection article added, New Source Item, or Schedule."))
  if (graph.nodes.filter((node) => catalogDefinition(catalog, node.type)?.entry).length !== 1) {
    findings.push(finding("graph_entry_invalid", "Workflow requires exactly one trigger.", undefined, "Keep one trigger."))
  }
  for (const node of graph.nodes) {
    const definition = catalogDefinition(catalog, node.type)
    if (!definition) findings.push(finding("node_type_unsupported", "Saved workflow contains a node type that is no longer supported.", node.id, "Remove this step explicitly; no replacement was applied automatically."))
    for (const field of requiredResources[node.type] ?? []) {
      const value = node.config[field]
      if (value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) {
        findings.push(finding("automation_resource_unavailable", "Required resource is not configured.", node.id, "Select a saved resource.", `config.${field}`))
      }
    }
    const unsafe = findUnsafeField(node.config)
    if (unsafe) findings.push(finding("node_config_invalid", "Credential and executable fields are prohibited.", node.id, "Remove unsafe field.", `config.${unsafe}`))
  }
  for (const [index, edge] of graph.edges.entries()) {
    const edgeKey = `${edge.sourceNodeId}:${edge.sourcePort}:${edge.targetNodeId}:${edge.targetPort}`
    if (edgeKeys.has(edgeKey)) {
      findings.push({ ...finding("edge_cardinality_invalid", "Duplicate connection is not allowed.", edge.targetNodeId, "Remove the duplicate connection."), edgeIndex: index })
      continue
    }
    edgeKeys.add(edgeKey)
    const sourceNode = nodes.get(edge.sourceNodeId)
    const targetNode = nodes.get(edge.targetNodeId)
    const source = sourceNode ? catalogDefinition(catalog, sourceNode.type) : undefined
    const target = targetNode ? catalogDefinition(catalog, targetNode.type) : undefined
    const compatible = source && target && source.outputs.some((output) => output.name === edge.sourcePort && target.inputs.some((input) => input.name === edge.targetPort && output.artifactTypes.some((type) => input.artifactTypes.includes(type))))
    if (target?.entry) findings.push({ ...finding("edge_port_invalid", "Trigger steps cannot receive incoming connections.", targetNode?.id, "Keep the trigger first and connect only from its output."), edgeIndex: index })
    else if (!compatible) findings.push({ ...finding("edge_port_invalid", "Connected ports are incompatible.", targetNode?.id, "Choose ports sharing an artifact type."), edgeIndex: index })
    else {
      const inputKey = `${edge.targetNodeId}:${edge.targetPort}`
      const outputKey = `${edge.sourceNodeId}:${edge.sourcePort}`
      inputCounts.set(inputKey, (inputCounts.get(inputKey) ?? 0) + 1)
      outputCounts.set(outputKey, (outputCounts.get(outputKey) ?? 0) + 1)
    }
  }
  for (const node of graph.nodes) {
    const definition = catalogDefinition(catalog, node.type)
    if (!definition) continue
    for (const port of definition.inputs) {
      const count = inputCounts.get(`${node.id}:${port.name}`) ?? 0
      if (port.required && count === 0) findings.push(finding("edge_cardinality_invalid", "Required input is not connected.", node.id, "Connect one compatible predecessor.", `inputs.${port.name}`))
      if (port.maxConnections !== null && port.maxConnections !== undefined && count > port.maxConnections) findings.push(finding("edge_cardinality_invalid", "Input has too many connections.", node.id, "Remove extra incoming connections.", `inputs.${port.name}`))
    }
    for (const port of definition.outputs) {
      const count = outputCounts.get(`${node.id}:${port.name}`) ?? 0
      if (port.maxConnections !== null && port.maxConnections !== undefined && count > port.maxConnections) findings.push(finding("edge_cardinality_invalid", "Output has too many connections.", node.id, "Remove extra outgoing connections.", `outputs.${port.name}`))
    }
  }
  if (hasCycle(graph)) findings.push(finding("graph_cycle", "Workflow Graph v1 cannot contain cycles.", undefined, "Remove a cycle connection."))
  const reachable = reachableNodeIds(graph)
  for (const node of graph.nodes) if (!reachable.has(node.id)) findings.push(finding("graph_unreachable_node", "Step is not connected to trigger.", node.id, "Connect or remove this step."))
  for (const outputId of graph.outputNodeIds) {
    const output = nodes.get(outputId)
    if (!output || !catalogDefinition(catalog, output.type)?.terminal || graph.edges.some((edge) => edge.sourceNodeId === outputId)) {
      findings.push(finding("graph_output_invalid", "Workflow must finish at a terminal output.", outputId, "Choose a supported output step."))
    }
  }
  return { valid: !findings.some((item) => item.severity === "error"), graphHash: "client-unsaved", findings }
}

export function defaultConfig(definition: AutomationNodeDefinition): Record<string, unknown> {
  const schema = definition.configSchema as JsonSchema
  const properties = schema.properties ?? {}
  return Object.fromEntries(Object.entries(properties).flatMap(([key, value]) => {
    const field = resolveSchema(value)
    if (field.default !== undefined) return [[key, structuredClone(field.default)]]
    if (field.type === "array") return [[key, []]]
    if (field.type === "boolean") return [[key, false]]
    return []
  }))
}

export type JsonSchema = {
  type?: string
  title?: string
  description?: string
  default?: unknown
  enum?: unknown[]
  anyOf?: JsonSchema[]
  properties?: Record<string, JsonSchema>
  items?: JsonSchema
  minimum?: number
  maximum?: number
  minLength?: number
  maxLength?: number
  pattern?: string
  format?: string
}

export function resolveSchema(schema: JsonSchema): JsonSchema {
  return schema.anyOf?.find((item) => item.type !== "null") ?? schema
}

function uniqueNodeId(graph: WorkflowGraph, type: string) {
  const stem = type.replace(/_/g, "-")
  let index = 1
  while (graph.nodes.some((node) => node.id === `${stem}-${index}`)) index += 1
  return `${stem}-${index}`
}

function duplicatePoint(graph: WorkflowGraph, nodeId: string, originalPoint: { x: number; y: number }) {
  let offset = DUPLICATE_OFFSET
  while (Object.entries(graph.metadata.layout).some(([id, point]) => id !== nodeId && point.x === originalPoint.x + offset.x && point.y === originalPoint.y + offset.y)) {
    offset = { x: offset.x + DUPLICATE_OFFSET.x, y: offset.y + DUPLICATE_OFFSET.y }
  }
  return { x: originalPoint.x + offset.x, y: originalPoint.y + offset.y }
}

function duplicateEditableConfig(config: Record<string, unknown>, schema: JsonSchema): Record<string, unknown> {
  const cloned = cloneEditableValue(config, resolveSchema(schema), "")
  return cloned && typeof cloned === "object" && !Array.isArray(cloned) ? cloned as Record<string, unknown> : {}
}

function cloneEditableValue(value: unknown, schema: JsonSchema, fieldName: string): unknown {
  if (isTransientDuplicateField(fieldName)) return undefined
  const resolved = resolveSchema(schema)
  if (Array.isArray(value)) {
    return value
      .map((item) => cloneEditableValue(item, resolved.items ? resolveSchema(resolved.items) : {}, fieldName))
      .filter((item) => item !== undefined)
  }
  if (!value || typeof value !== "object") {
    return makeDuplicatedIdentifier(value, fieldName)
  }
  if (!resolved.properties) return structuredClone(value)
  const output: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value)) {
    if (!Object.prototype.hasOwnProperty.call(resolved.properties, key)) continue
    const cloned = cloneEditableValue(item, resolved.properties[key], key)
    if (cloned !== undefined) output[key] = cloned
  }
  return output
}

function makeDuplicatedIdentifier(value: unknown, fieldName: string): unknown {
  if (typeof value !== "string" || !isIdentifierField(fieldName)) return structuredClone(value)
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `${value}-copy-${suffix}`
}

function isIdentifierField(fieldName: string) {
  const normalized = fieldName.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLocaleLowerCase()
  return INSTANCE_IDENTIFIER_KEYS.has(normalized) || HANDLE_IDENTIFIER_KEYS.has(normalized)
}

function isTransientDuplicateField(fieldName: string) {
  const normalized = fieldName.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLocaleLowerCase()
  return TRANSIENT_DUPLICATE_KEYS.has(normalized) || TRANSIENT_DUPLICATE_KEYS.has(normalized.replaceAll("_", ""))
}

function reachableNodeIds(graph: WorkflowGraph) {
  const reachable = new Set<string>()
  const queue = [graph.entryNodeId]
  while (queue.length) {
    const id = queue.shift()!
    if (reachable.has(id)) continue
    reachable.add(id)
    for (const edge of graph.edges) if (edge.sourceNodeId === id) queue.push(edge.targetNodeId)
  }
  return reachable
}

function hasCycle(graph: WorkflowGraph) {
  const visiting = new Set<string>()
  const visited = new Set<string>()
  const visit = (id: string): boolean => {
    if (visiting.has(id)) return true
    if (visited.has(id)) return false
    visiting.add(id)
    for (const edge of graph.edges) if (edge.sourceNodeId === id && visit(edge.targetNodeId)) return true
    visiting.delete(id)
    visited.add(id)
    return false
  }
  return graph.nodes.some((node) => visit(node.id))
}

function finding(code: string, message: string, nodeId?: string, recoveryAction?: string, fieldPath?: string): ValidationFinding {
  return { code, severity: "error", message, nodeId: nodeId ?? null, edgeIndex: null, fieldPath: fieldPath ?? null, recoveryAction: recoveryAction ?? null }
}

function findUnsafeField(value: unknown, prefix = ""): string | null {
  if (!value || typeof value !== "object") return null
  for (const [key, item] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (isUnsafeWorkflowField(key)) return path
    const nested = findUnsafeField(item, path)
    if (nested) return nested
  }
  return null
}

export function isUnsafeWorkflowField(field: string) {
  const normalized = field.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLocaleLowerCase()
  return /(?:^|_)(?:api_key|authorization|credentials?|environment|filesystem|job_type|password|prompt_body|roles?|scopes?|secret|secret_ref|system_template|token|user_template)(?:_|$)/.test(normalized)
}
