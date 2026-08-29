import { compatiblePortPairs, connectionCompatibility } from "./workflow-graph-contracts"
import { catalogDefinition, hasCycle, orderedWorkflowNodes } from "./workflow-graph-topology"
import { type JsonSchema, defaultConfig, duplicateEditableConfig } from "./workflow-config-schema"

import type {
  AutomationNodeCatalog,
  WorkflowEdge,
  WorkflowGraph,
  WorkflowNode,
} from "./automation-types"

/** Every mutating graph edit. Each returns a new graph or a user-facing error. */

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
  const isEntry = nodeId === graph.entryNodeId || definition.entry
  let deleteReason: string | undefined
  if (!isEntry && graph.outputNodeIds.includes(nodeId)) {
    deleteReason = "Workflow needs one terminal output. Add another output before deleting this one."
  } else if (!isEntry && (incoming.length > 1 || outgoing.length > 1)) {
    deleteReason = "Delete supports linear Workflow Graph v1 paths only."
  } else if (!isEntry && incoming[0] && outgoing[0]) {
    const source = graph.nodes.find((item) => item.id === incoming[0].sourceNodeId)
    const target = graph.nodes.find((item) => item.id === outgoing[0].targetNodeId)
    const sourceDefinition = source ? catalogDefinition(catalog, source.type) : undefined
    const targetDefinition = target ? catalogDefinition(catalog, target.type) : undefined
    if (!source || !target || !sourceDefinition || !targetDefinition || !compatiblePortPairs(sourceDefinition, targetDefinition)[0]) {
      deleteReason = "Deleting this step would leave incompatible neighbors."
    }
  }

  let duplicateReason: string | undefined
  if (definition.terminal && !definition.entry) {
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
  const isEntry = nodeId === graph.entryNodeId || catalogDefinition(catalog, node.type)?.entry === true
  if (!isEntry && incoming[0] && outgoing[0]) {
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
      entryNodeId: graph.entryNodeId === nodeId ? "" : graph.entryNodeId,
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
  if (definition.entry) {
    const duplicateId = uniqueNodeId(graph, node.type)
    const duplicate = {
      id: duplicateId,
      type: node.type,
      config: duplicateEditableConfig(node.config, definition.configSchema as JsonSchema),
    }
    const nextGraph = {
      ...graph,
      nodes: [...graph.nodes, duplicate],
      metadata: { layout: { ...graph.metadata.layout, [duplicateId]: { x: 0, y: 0 } } },
    }
    const originalPoint = graph.metadata.layout[node.id] ?? { x: 80, y: 120 }
    return {
      nodeId: duplicateId,
      graph: updateNodePosition(nextGraph, duplicateId, duplicatePoint(nextGraph, duplicateId, originalPoint)),
    }
  }
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
  if (!output || !input) {
    return { error: `Ports ${edge.sourcePort} and ${edge.targetPort} are unavailable.` }
  }
  const compatibility = connectionCompatibility(graph, catalog, edge)
  if (compatibility === "incompatible") {
    return { error: `Ports ${edge.sourcePort} and ${edge.targetPort} require incompatible artifact capabilities.` }
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
