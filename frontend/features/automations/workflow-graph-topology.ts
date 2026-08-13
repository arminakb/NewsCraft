import type {
  AutomationNodeCatalog,
  WorkflowGraph,
  WorkflowNode,
} from "./automation-types"

/** Read-only graph and catalog lookups shared by every other workflow module. */

export function catalogDefinition(catalog: AutomationNodeCatalog, type: string) {
  return catalog.nodes.find((item) => item.type === type)
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

/** Node ids reachable from the entry node. */
export function reachableNodeIds(graph: WorkflowGraph) {
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

export function hasCycle(graph: WorkflowGraph) {
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
