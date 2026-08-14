import { findUnsafeField } from "./workflow-field-policy"
import { connectionCompatibility } from "./workflow-graph-contracts"
import { catalogDefinition, hasCycle, reachableNodeIds } from "./workflow-graph-topology"

import type {
  AutomationNodeCatalog,
  GraphValidation,
  ValidationFinding,
  WorkflowGraph,
} from "./automation-types"

/** Client-side pre-flight validation, mirroring the server graph contract. */

const requiredResources: Record<string, string[]> = {
  manual: ["storyRevisionId"],
  collection_article_added: ["collectionId"],
  new_source_item: ["sourceIds"],
  research: ["providerProfileId"],
  generate_content_pack: ["editorialProfileId", "providerProfileId", "promptVersionIds"],
  telegram_publish: ["destinationId"],
}

export function validateWorkflowClient(graph: WorkflowGraph, catalog: AutomationNodeCatalog): GraphValidation {
  const findings: ValidationFinding[] = []
  const shapeCache = new Map()
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
    const compatible = source && target ? connectionCompatibility(graph, catalog, edge, shapeCache) : "incompatible"
    if (target?.entry) findings.push({ ...finding("edge_port_invalid", "Trigger steps cannot receive incoming connections.", targetNode?.id, "Keep the trigger first and connect only from its output."), edgeIndex: index })
    else if (compatible === "incompatible") findings.push({ ...finding("edge_port_invalid", "Connected ports require incompatible artifact capabilities.", targetNode?.id, "Choose an output satisfying the input contract."), edgeIndex: index })
    else if (compatible === "incomplete") findings.push({ ...finding("edge_artifact_contract_incomplete", "Artifact compatibility is incomplete until an upstream artifact is available.", targetNode?.id, "Configure and run the upstream step before activation.", undefined, "warning"), edgeIndex: index })
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

function finding(code: string, message: string, nodeId?: string, recoveryAction?: string, fieldPath?: string, severity: "error" | "warning" = "error"): ValidationFinding {
  return { code, severity, message, nodeId: nodeId ?? null, edgeIndex: null, fieldPath: fieldPath ?? null, recoveryAction: recoveryAction ?? null }
}
