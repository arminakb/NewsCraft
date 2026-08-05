import { describe, expect, it } from "vitest"

import {
  alignWorkflowNodePosition,
  WORKFLOW_ALIGNMENT_TOLERANCE,
  workflowEdgeRouting,
} from "@/features/automations/workflow-layout"

const nodes = [
  { id: "trigger", position: { x: 80, y: 120 } },
  { id: "generate", position: { x: 340, y: 120 } },
  { id: "drafts", position: { x: 600, y: 280 } },
]

describe("workflow canvas layout", () => {
  it("snaps a dragged node to nearby existing axes without guide data", () => {
    const result = alignWorkflowNodePosition("drafts", { x: 348, y: 129 }, nodes)

    expect(result).toEqual({ position: { x: 340, y: 120 } })
  })

  it("leaves positions alone outside alignment tolerance", () => {
    const position = { x: 359, y: 150 }
    const result = alignWorkflowNodePosition("drafts", position, nodes)

    expect(result).toEqual({ position })
    expect(WORKFLOW_ALIGNMENT_TOLERANCE).toBe(12)
  })

  it("uses straight routing for aligned handles and smooth steps for offsets", () => {
    expect(workflowEdgeRouting(120, 120)).toBe("straight")
    expect(workflowEdgeRouting(120, 120.5)).toBe("straight")
    expect(workflowEdgeRouting(120, 122)).toBe("smoothstep")
  })
})
