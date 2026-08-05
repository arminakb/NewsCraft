import {
  emptyWorkflowGraph,
  initialWorkflowEditorGraph,
} from "@/features/automations/workflow-editor-state"
import type { WorkflowGraph } from "@/features/automations/automation-types"

const persistedGraph: WorkflowGraph = {
  schemaVersion: 1,
  entryNodeId: "trigger-1",
  nodes: [{ id: "trigger-1", type: "manual", config: {} }],
  edges: [],
  outputNodeIds: ["trigger-1"],
  metadata: { layout: {} },
}

describe("workflow editor initial graph", () => {
  it("keeps the persisted graph authoritative during editor initialization", () => {
    expect(initialWorkflowEditorGraph(persistedGraph)).toBe(persistedGraph)
    expect(emptyWorkflowGraph()).toMatchObject({ entryNodeId: "", nodes: [], edges: [], outputNodeIds: [] })
  })

  it("keeps persisted workflow nodes on direct initialization", () => {
    expect(initialWorkflowEditorGraph(persistedGraph)).toBe(persistedGraph)
  })
})
