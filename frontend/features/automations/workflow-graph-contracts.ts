import { catalogDefinition } from "./workflow-graph-topology"

import type {
  ArtifactCapability,
  ArtifactInputContract,
  ArtifactKind,
  ArtifactOutputContract,
  AutomationNodeCatalog,
  AutomationNodeDefinition,
  WorkflowEdge,
  WorkflowGraph,
} from "./automation-types"

/** The artifact-capability algebra: which output may feed which input. */

export type CompatibilityStatus = "compatible" | "incomplete" | "incompatible"

type ArtifactShape = {
  kind: ArtifactKind | null
  capabilities: Set<ArtifactCapability>
  known: boolean
}

export function compatiblePortPairs(source: AutomationNodeDefinition, target: AutomationNodeDefinition) {
  return source.outputs.flatMap((output) => target.inputs
    .filter((input) => staticPortCompatibility(source, output, target, input) !== "incompatible")
    .map((input) => ({ sourcePort: output.name, targetPort: input.name })))
}

export function connectionCompatibility(
  graph: WorkflowGraph,
  catalog: AutomationNodeCatalog,
  edge: WorkflowEdge,
  cache?: Map<string, ArtifactShape>,
): CompatibilityStatus {
  const sourceNode = graph.nodes.find((node) => node.id === edge.sourceNodeId)
  const targetNode = graph.nodes.find((node) => node.id === edge.targetNodeId)
  const source = sourceNode ? catalogDefinition(catalog, sourceNode.type) : undefined
  const target = targetNode ? catalogDefinition(catalog, targetNode.type) : undefined
  const output = source?.outputs.find((port) => port.name === edge.sourcePort)
  const input = target?.inputs.find((port) => port.name === edge.targetPort)
  if (!source || !target || !output || !input) return "incompatible"
  if (!hasContract(output, input, source, target)) return legacyPortCompatibility(output, input)
  const shape = artifactShapeForOutput(graph, catalog, edge.sourceNodeId, edge.sourcePort, cache ?? new Map())
  return matchInputContract(shape, inputContract(target, input))
}

function staticPortCompatibility(
  source: AutomationNodeDefinition,
  output: AutomationNodeDefinition["outputs"][number],
  target: AutomationNodeDefinition,
  input: AutomationNodeDefinition["inputs"][number],
): CompatibilityStatus {
  if (!hasContract(output, input, source, target)) return legacyPortCompatibility(output, input)
  return matchInputContract(staticOutputShape(outputContract(source, output)), inputContract(target, input))
}

function hasContract(
  output: AutomationNodeDefinition["outputs"][number],
  input: AutomationNodeDefinition["inputs"][number],
  source: AutomationNodeDefinition,
  target: AutomationNodeDefinition,
) {
  return Boolean(outputContract(source, output) || inputContract(target, input))
}

function inputContract(
  definition: AutomationNodeDefinition,
  port: AutomationNodeDefinition["inputs"][number],
): ArtifactInputContract | null {
  return port.inputContract ?? definition.inputContract ?? null
}

function outputContract(
  definition: AutomationNodeDefinition,
  port: AutomationNodeDefinition["outputs"][number],
): ArtifactOutputContract | null {
  return port.outputContract ?? definition.outputContract ?? null
}

function legacyPortCompatibility(
  output: AutomationNodeDefinition["outputs"][number],
  input: AutomationNodeDefinition["inputs"][number],
): CompatibilityStatus {
  // Boundary fallback for catalogs captured before capability contracts shipped.
  return output.artifactTypes.some((type) => input.artifactTypes.includes(type)) ? "compatible" : "incompatible"
}

function legacyShape(artifactType: string): ArtifactShape {
  const base = { capabilities: new Set<ArtifactCapability>(), known: true }
  if (artifactType === "article_package") return { kind: "article", capabilities: new Set(["textual", "structured", "article", "reviewable", "generatable"]), known: true }
  if (artifactType === "research_package") return { kind: "research", capabilities: new Set(["textual", "structured", "research", "reviewable", "generatable"]), known: true }
  if (artifactType === "package" || artifactType === "draft_package" || artifactType === "content_package") return { kind: "draft", capabilities: new Set(["textual", "structured", "draft", "reviewable"]), known: true }
  if (artifactType === "story.revision_ref" || artifactType === "article.collection_added" || artifactType === "source_item.ref" || artifactType === "content_item.ref" || artifactType === "story.revision_set_ref") {
    const context: ArtifactCapability | null = artifactType === "article.collection_added" ? "collection-context" : artifactType === "source_item.ref" || artifactType === "content_item.ref" ? "source-context" : null
    const capabilities: ArtifactCapability[] = ["textual", "structured", "article", "reviewable", "generatable"]
    if (context) capabilities.push(context)
    return { kind: "article", capabilities: new Set<ArtifactCapability>(capabilities), known: true }
  }
  if (artifactType === "story.researched_revision_ref") return { kind: "research", capabilities: new Set(["textual", "structured", "research", "reviewable", "generatable"]), known: true }
  if (artifactType.startsWith("draft.") || artifactType === "export.manual_package_ref") {
    const capabilities = new Set<ArtifactCapability>(["textual", "structured", "draft", "reviewable"])
    if (artifactType === "draft.approved_telegram_revision_ref") capabilities.add("approved"), capabilities.add("publishable")
    return { kind: "draft", capabilities, known: true }
  }
  if (artifactType === "run.signal") return { kind: "schedule_event", capabilities: new Set(["structured", "schedule-context"]), known: true }
  if (artifactType === "publication.telegram_ref") return { kind: "publication", capabilities: new Set(["structured", "approved", "publishable"]), known: true }
  return { kind: null, ...base, known: false }
}

function staticOutputShape(contract: ArtifactOutputContract | null): ArtifactShape {
  if (!contract) return { kind: null, capabilities: new Set(), known: false }
  return {
    kind: contract.kind ?? null,
    capabilities: new Set([...(contract.capabilities ?? []), ...(contract.addsCapabilities ?? [])]),
    known: Boolean(contract.kind) && !contract.preservesInputArtifact,
  }
}

function artifactShapeForOutput(
  graph: WorkflowGraph,
  catalog: AutomationNodeCatalog,
  nodeId: string,
  portName: string,
  cache: Map<string, ArtifactShape>,
  visiting = new Set<string>(),
): ArtifactShape {
  const cacheKey = `${nodeId}:${portName}`
  const cached = cache.get(cacheKey)
  if (cached) return cached
  if (visiting.has(cacheKey)) return { kind: null, capabilities: new Set(), known: false }
  const node = graph.nodes.find((item) => item.id === nodeId)
  const definition = node ? catalogDefinition(catalog, node.type) : undefined
  const port = definition?.outputs.find((item) => item.name === portName)
  if (!definition || !port) return { kind: null, capabilities: new Set(), known: false }
  const contract = outputContract(definition, port)
  if (!contract) {
    const shapes = port.artifactTypes.map(legacyShape).filter((shape) => shape.known)
    const shape = shapes.length === 1 ? shapes[0] : { kind: null, capabilities: new Set<ArtifactCapability>(), known: false }
    cache.set(cacheKey, shape)
    return shape
  }
  visiting.add(cacheKey)
  const incoming = graph.edges.filter((edge) => edge.targetNodeId === nodeId)
  const upstream = incoming.length === 1
    ? artifactShapeForOutput(graph, catalog, incoming[0].sourceNodeId, incoming[0].sourcePort, cache, visiting)
    : { kind: null, capabilities: new Set<ArtifactCapability>(), known: false }
  visiting.delete(cacheKey)
  const shape = contract.preservesInputArtifact
    ? {
        kind: contract.kind ?? upstream.kind,
        capabilities: new Set([...upstream.capabilities, ...(contract.capabilities ?? []), ...(contract.addsCapabilities ?? [])]),
        known: upstream.known && Boolean(contract.kind ?? upstream.kind),
      }
    : staticOutputShape(contract)
  cache.set(cacheKey, shape)
  return shape
}

function matchInputContract(shape: ArtifactShape, contract: ArtifactInputContract | null): CompatibilityStatus {
  if (!contract) return "incompatible"
  if (!shape.known) return "incomplete"
  if (contract.acceptedKinds?.length && !contract.acceptedKinds.includes(shape.kind as ArtifactKind)) return "incompatible"
  if (contract.allOf?.some((capability) => !shape.capabilities.has(capability))) return "incompatible"
  if (contract.anyOf?.length && !contract.anyOf.some((capability) => shape.capabilities.has(capability))) return "incompatible"
  return "compatible"
}
