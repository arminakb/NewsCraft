import {
  deleteWorkflowNode,
  duplicateWorkflowNode,
  validateWorkflowClient,
  workflowNodeActionState,
} from "@/features/automations/workflow-graph"
import type { AutomationNodeCatalog, WorkflowGraph } from "@/features/automations/automation-types"

describe("workflow node actions", () => {
  it("deletes a connected node, removes its attached edges, and bridges compatible neighbors", () => {
    const graph = workflowGraph({
      nodes: [
        node("trigger-1", "manual", {}, { x: 80, y: 120 }),
        node("filter-1", "filter_content", {}, { x: 340, y: 120 }),
        node("output-1", "save_drafts", {}, { x: 600, y: 120 }),
      ],
      edges: [
        edge("trigger-1", "story", "filter-1", "story"),
        edge("filter-1", "accepted", "output-1", "drafts"),
      ],
      outputNodeIds: ["output-1"],
    })

    const result = deleteWorkflowNode(graph, catalog, "filter-1")

    expect(result.graph?.nodes.map((item) => item.id)).toEqual(["trigger-1", "output-1"])
    expect(result.graph?.edges).toEqual([edge("trigger-1", "story", "output-1", "drafts")])
    expect(result.graph?.edges.some((item) => item.sourceNodeId === "filter-1" || item.targetNodeId === "filter-1")).toBe(false)
    expect(result.graph?.metadata.layout).not.toHaveProperty("filter-1")
  })

  it("duplicates editable configuration without copying runtime state or mutating the original", () => {
    const originalConfig = {
      batchSize: 4,
      instanceId: "filter-instance-1",
      handleIds: ["filter-handle-a", "filter-handle-b"],
      runtimeState: { status: "succeeded" },
      executionResults: [{ output: "should not copy" }],
      validationErrors: [{ message: "should not copy" }],
      temporaryUiState: { expanded: true },
    }
    const graph = workflowGraph({
      nodes: [
        node("trigger-1", "manual", {}),
        node("filter-1", "filter_content", originalConfig, { x: 340, y: 120 }),
        node("output-1", "save_drafts", {}),
      ],
      edges: [
        edge("trigger-1", "story", "filter-1", "story"),
        edge("filter-1", "accepted", "output-1", "drafts"),
      ],
      outputNodeIds: ["output-1"],
    })

    const result = duplicateWorkflowNode(graph, catalog, "filter-1")
    const duplicate = result.graph?.nodes.find((item) => item.id !== "trigger-1" && item.id !== "filter-1" && item.id !== "output-1")

    expect(duplicate?.id).toBe("filter-content-1")
    expect(duplicate?.type).toBe("filter_content")
    expect(duplicate?.config).toMatchObject({ batchSize: 4 })
    expect(duplicate?.config.instanceId).not.toBe(originalConfig.instanceId)
    expect(duplicate?.config.handleIds).not.toEqual(originalConfig.handleIds)
    expect(duplicate?.config).not.toHaveProperty("runtimeState")
    expect(duplicate?.config).not.toHaveProperty("executionResults")
    expect(duplicate?.config).not.toHaveProperty("validationErrors")
    expect(duplicate?.config).not.toHaveProperty("temporaryUiState")
    expect(graph.nodes.find((item) => item.id === "filter-1")?.config).toEqual(originalConfig)
    expect(result.graph?.metadata.layout["filter-content-1"]).toEqual({ x: 388, y: 168 })
    expect(result.graph?.edges).toEqual([
      edge("trigger-1", "story", "filter-1", "story"),
      edge("filter-1", "accepted", "filter-content-1", "story"),
      edge("filter-content-1", "accepted", "output-1", "drafts"),
    ])
    expect(validateWorkflowClient(result.graph!, catalog).findings.filter((item) => item.code.startsWith("graph_"))).toEqual([])
  })

  it("keeps documented singleton constraints disabled with an explicit reason", () => {
    const graph = workflowGraph({
      nodes: [node("trigger-1", "manual", {}), node("output-1", "save_drafts", {})],
      edges: [edge("trigger-1", "story", "output-1", "drafts")],
      outputNodeIds: ["output-1"],
    })

    expect(workflowNodeActionState(graph, catalog, "trigger-1")).toMatchObject({
      canDuplicate: false,
      duplicateReason: expect.stringContaining("one trigger"),
      canDelete: false,
    })
    expect(workflowNodeActionState(graph, catalog, "output-1")).toMatchObject({
      canDuplicate: false,
      duplicateReason: expect.stringContaining("terminal output"),
      canDelete: false,
    })
    expect(workflowNodeActionState(graph, catalog, "filter-1")).toMatchObject({
      canDuplicate: false,
      duplicateReason: "Step no longer exists.",
      canDelete: false,
    })
  })

  it("allows explicit removal of an unsupported saved step without silent rewiring", () => {
    const graph = workflowGraph({
      nodes: [
        node("trigger-1", "manual", {}),
        node("legacy-1", "telegram_new_item", {}),
        node("output-1", "save_drafts", {}),
      ],
      edges: [
        edge("trigger-1", "story", "legacy-1", "story"),
        edge("legacy-1", "draft", "output-1", "drafts"),
      ],
      outputNodeIds: ["output-1"],
    })

    expect(workflowNodeActionState(graph, catalog, "legacy-1")).toMatchObject({
      canDuplicate: false,
      canDelete: true,
    })
    const result = deleteWorkflowNode(graph, catalog, "legacy-1")
    expect(result.graph?.nodes.map((item) => item.id)).toEqual(["trigger-1", "output-1"])
    expect(result.graph?.edges).toEqual([])
  })
})

const catalog = {
  schemaVersion: 1,
  maxNodes: 30,
  maxEdges: 60,
  nodes: [
    definition("manual", "trigger", "Manual", true, false, [], [port("story", ["story.revision_ref"], null)]),
    definition(
      "filter_content",
      "select_filter",
      "Filter content",
      false,
      false,
      [port("story", ["story.revision_ref"], 1)],
      [port("accepted", ["story.revision_ref"], null)],
      {
        type: "object",
        properties: {
          batchSize: { type: "integer" },
          instanceId: { type: "string" },
          handleIds: { type: "array", items: { type: "string" } },
          runtimeState: { type: "object" },
          executionResults: { type: "array" },
          validationErrors: { type: "array" },
          temporaryUiState: { type: "object" },
        },
      },
    ),
    definition("save_drafts", "output", "Save to Drafts", false, true, [port("drafts", ["story.revision_ref"], 1)], []),
  ],
} as unknown as AutomationNodeCatalog

function workflowGraph(input: {
  nodes: Array<{ id: string; type: string; config: Record<string, unknown>; point?: { x: number; y: number } }>
  edges: Array<{ sourceNodeId: string; sourcePort: string; targetNodeId: string; targetPort: string }>
  outputNodeIds: string[]
}): WorkflowGraph {
  return {
    schemaVersion: 1 as const,
    entryNodeId: "trigger-1",
    nodes: input.nodes.map(({ point: _point, ...item }) => item),
    edges: input.edges,
    outputNodeIds: input.outputNodeIds,
    metadata: { layout: Object.fromEntries(input.nodes.map((item) => [item.id, item.point ?? { x: 80, y: 120 }])) },
  }
}

function node(id: string, type: string, config: Record<string, unknown>, point = { x: 80, y: 120 }) {
  return { id, type, config, point }
}

function edge(sourceNodeId: string, sourcePort: string, targetNodeId: string, targetPort: string) {
  return { sourceNodeId, sourcePort, targetNodeId, targetPort }
}

function port(name: string, artifactTypes: string[], maxConnections: number | null) {
  return { name, artifactTypes, required: true, maxConnections }
}

function definition(
  type: string,
  family: string,
  displayName: string,
  entry: boolean,
  terminal: boolean,
  inputs: unknown[],
  outputs: unknown[],
  configSchema = { type: "object", properties: {} },
) {
  return {
    type,
    family,
    displayName,
    description: `${displayName} description`,
    entry,
    terminal,
    runtimeStatus: "existing" as const,
    runtimeOwner: "compiler" as const,
    runtimeJobTypes: [],
    inputs,
    outputs,
    configSchema,
    uiHints: {},
  }
}
