export type WorkflowLayoutPoint = {
  x: number
  y: number
}

export type WorkflowLayoutNode = {
  id: string
  position: WorkflowLayoutPoint
}

export type WorkflowNodeAlignment = {
  position: WorkflowLayoutPoint
}

export const WORKFLOW_SNAP_GRID: [number, number] = [20, 20]
export const WORKFLOW_ALIGNMENT_TOLERANCE = 12
export const WORKFLOW_EDGE_ALIGNMENT_TOLERANCE = 1

export function alignWorkflowNodePosition(
  nodeId: string,
  position: WorkflowLayoutPoint,
  nodes: WorkflowLayoutNode[],
  tolerance = WORKFLOW_ALIGNMENT_TOLERANCE,
): WorkflowNodeAlignment {
  const otherNodes = nodes.filter((node) => node.id !== nodeId)
  const xMatch = nearestAlignment(position.x, otherNodes.map((node) => ({ value: node.position.x, targetNodeId: node.id })), tolerance)
  const yMatch = nearestAlignment(position.y, otherNodes.map((node) => ({ value: node.position.y, targetNodeId: node.id })), tolerance)
  const alignedPosition = {
    x: xMatch?.value ?? position.x,
    y: yMatch?.value ?? position.y,
  }

  return {
    position: alignedPosition,
  }
}

export function workflowEdgeRouting(sourceY: number, targetY: number, tolerance = WORKFLOW_EDGE_ALIGNMENT_TOLERANCE) {
  return Math.abs(sourceY - targetY) <= tolerance ? "straight" : "smoothstep"
}

type AlignmentCandidate = {
  value: number
  targetNodeId: string
}

function nearestAlignment(value: number, candidates: AlignmentCandidate[], tolerance: number) {
  return candidates.reduce<AlignmentCandidate | null>((nearest, candidate) => {
    const distance = Math.abs(value - candidate.value)
    if (distance > tolerance) return nearest
    if (!nearest || distance < Math.abs(value - nearest.value)) return candidate
    if (distance === Math.abs(value - nearest.value) && candidate.targetNodeId.localeCompare(nearest.targetNodeId) < 0) return candidate
    return nearest
  }, null)
}
