import {
  emptyWorkflowGraph,
} from "@/features/automations/workflow-editor-state"

describe("workflow editor initial graph", () => {
  it("provides a blank graph for new workflows", () => {
    expect(emptyWorkflowGraph()).toMatchObject({ entryNodeId: "", nodes: [], edges: [], outputNodeIds: [] })
  })
})
