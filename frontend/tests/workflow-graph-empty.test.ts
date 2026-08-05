import { insertWorkflowNode } from "@/features/automations/workflow-graph"
import { emptyWorkflowGraph } from "@/features/automations/workflow-editor-state"

describe("empty workflow graph editing", () => {
  it("adds trigger first, then compatible steps without injecting defaults", () => {
    const trigger = insertWorkflowNode(emptyWorkflowGraph(), catalog as never, "manual")
    expect(trigger.graph).toMatchObject({ entryNodeId: "manual-1", nodes: [{ id: "manual-1", type: "manual" }], edges: [], outputNodeIds: [] })

    const generate = insertWorkflowNode(trigger.graph!, catalog as never, "generate_content_pack")
    expect(generate.graph?.nodes.map((node) => node.type)).toEqual(["manual", "generate_content_pack"])
    expect(generate.graph?.edges).toHaveLength(1)

    const output = insertWorkflowNode(generate.graph!, catalog as never, "save_drafts")
    expect(output.graph?.nodes.map((node) => node.type)).toEqual(["manual", "generate_content_pack", "save_drafts"])
    expect(output.graph?.outputNodeIds).toEqual(["save-drafts-1"])
  })
})

const catalog = {
  schemaVersion: 1,
  maxNodes: 30,
  maxEdges: 60,
  nodes: [
    node("manual", "trigger", true, false, [], [{ name: "story", artifactTypes: ["story.revision_ref"], required: false, maxConnections: null }]),
    node("generate_content_pack", "generate", false, false, [{ name: "story", artifactTypes: ["story.revision_ref"], required: true, maxConnections: 1 }], [{ name: "drafts", artifactTypes: ["draft.revision_set_ref"], required: false, maxConnections: null }]),
    node("save_drafts", "output", false, true, [{ name: "drafts", artifactTypes: ["draft.revision_set_ref"], required: true, maxConnections: 1 }], []),
  ],
}

function node(type: string, family: string, entry: boolean, terminal: boolean, inputs: unknown[], outputs: unknown[]) {
  return {
    type,
    family,
    displayName: type,
    description: type,
    entry,
    terminal,
    runtimeStatus: "existing",
    runtimeOwner: "compiler",
    runtimeJobTypes: [],
    inputs,
    outputs,
    configSchema: { type: "object", properties: {} },
    uiHints: {},
  }
}
