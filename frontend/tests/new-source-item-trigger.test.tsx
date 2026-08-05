import { fireEvent, render, screen } from "@testing-library/react"

import type { SourceSummary } from "@/features/operations/ingestion-types"
import { NodePicker } from "@/features/automations/workflow-node-library"
import { WorkflowInspector } from "@/features/automations/workflow-inspector"
import { configuredNodeLabel } from "@/features/automations/workflow-node-visual"
import { emptyWorkflowGraph } from "@/features/automations/workflow-editor-state"
import { insertWorkflowNode, validateWorkflowClient, workflowResourceRequests } from "@/features/automations/workflow-graph"
import type { AutomationNodeCatalog, AutomationResource } from "@/features/automations/automation-types"

const sourceId = "11111111-1111-4111-8111-111111111111"
const secondSourceId = "22222222-2222-4222-8222-222222222222"

describe("New Source Item trigger", () => {
  it("is a first-only trigger and stays invalid until source IDs are selected", () => {
    const inserted = insertWorkflowNode(emptyWorkflowGraph(), catalog, "new_source_item")
    expect(inserted.graph).toMatchObject({
      entryNodeId: "new-source-item-1",
      outputNodeIds: ["new-source-item-1"],
      nodes: [{ type: "new_source_item", config: { sourceIds: [] } }],
    })
    expect(validateWorkflowClient(inserted.graph!, catalog).findings).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "automation_resource_unavailable", fieldPath: "config.sourceIds" }),
      ]),
    )
    expect(insertWorkflowNode(inserted.graph!, catalog, "new_source_item").error).toMatch(/one trigger/i)

    const configured = {
      ...inserted.graph!,
      nodes: [{ ...inserted.graph!.nodes[0], config: { sourceIds: [sourceId, secondSourceId] } }],
    }
    expect(validateWorkflowClient(configured, catalog).valid).toBe(true)
    expect(workflowResourceRequests(configured)).toEqual([
      { kind: "source", id: sourceId },
      { kind: "source", id: secondSourceId },
    ])
  })

  it("renders stable selected source names and unavailable references", () => {
    const resources = [resource(sourceId, "OpenAI"), resource(secondSourceId, "Reuters")]
    expect(configuredNodeLabel(
      { type: "new_source_item", config: { sourceIds: [sourceId, secondSourceId] } },
      "New Source Item",
      resources,
    )).toBe("OpenAI, Reuters")
    expect(configuredNodeLabel({ type: "new_source_item", config: { sourceIds: [] } }, "New Source Item", [])).toBe("Select one or more sources")
    expect(configuredNodeLabel({ type: "new_source_item", config: { sourceIds: [sourceId] } }, "New Source Item", [])).toBe("Loading sources…")
  })

  it("is available as a draggable first-node library tile", () => {
    const onAdd = vi.fn()
    render(<NodePicker allowEntry catalog={catalog} onAdd={onAdd} />)
    const tile = screen.getByRole("button", { name: "New Source Item" })
    expect(tile).toHaveAttribute("draggable", "true")
    fireEvent.click(tile)
    expect(onAdd).toHaveBeenCalledWith("new_source_item")
  })

  it("shows source loading, retry, empty, and stable-ID selection states", () => {
    const props = baseProps()
    const { rerender } = render(<WorkflowInspector {...props} sourcesPending />)
    expect(screen.getByRole("status")).toHaveTextContent("Loading sources")

    rerender(<WorkflowInspector {...props} sourcesError={new Error("Sources unavailable")} />)
    expect(screen.getByRole("alert")).toHaveTextContent("Sources unavailable")
    fireEvent.click(screen.getByRole("button", { name: "Retry sources" }))
    expect(props.onRetrySources).toHaveBeenCalledTimes(1)

    rerender(<WorkflowInspector {...props} sources={[]} />)
    expect(screen.getByRole("status")).toHaveTextContent("Add a source under Sources")
    expect(screen.getByRole("link", { name: /Add a source under Sources/i })).toHaveAttribute("href", "/sources")

    const onGraphChange = vi.fn()
    rerender(<WorkflowInspector {...baseProps({ onGraphChange, sources: [source] })} />)
    fireEvent.click(screen.getByRole("checkbox"))
    expect(onGraphChange).toHaveBeenCalledWith(expect.objectContaining({
      nodes: [expect.objectContaining({ config: { sourceIds: [sourceId] } })],
    }))
  })
})

function baseProps(overrides: Partial<Parameters<typeof WorkflowInspector>[0]> = {}): Parameters<typeof WorkflowInspector>[0] {
  return {
    graph,
    catalog,
    selectedNodeId: "source-trigger-1",
    resources: [],
    findings: [],
    onGraphChange: vi.fn(),
    onRejected: vi.fn(),
    onRetrySources: vi.fn(),
    ...overrides,
  }
}

function resource(id: string, displayName: string, state: "ready" | "unavailable" = "ready"): AutomationResource {
  return {
    id,
    kind: "source",
    displayName,
    state,
    reasonCode: state === "ready" ? null : "resource_missing",
    capabilities: ["new_source_item"],
    referencedByActiveVersion: false,
    manageHref: "/sources",
  }
}

const source: SourceSummary = {
  id: sourceId,
  platform: "rss",
  name: "OpenAI",
  url: "https://example.test/feed.xml",
  category: "News",
  language: "en",
  status: "healthy",
  items24h: 1,
  new24h: 1,
  failed24h: 0,
  lastSuccess: "2026-08-05T08:00:00Z",
  fetchIntervalMinutes: 15,
  totalItems: 1,
  media24h: 0,
  addedAt: "2026-08-05T07:00:00Z",
  lastCheckedAt: "2026-08-05T08:00:00Z",
  failureReason: null,
}

const graph = {
  schemaVersion: 1 as const,
  entryNodeId: "source-trigger-1",
  nodes: [{ id: "source-trigger-1", type: "new_source_item", config: { sourceIds: [] } }],
  edges: [],
  outputNodeIds: ["source-trigger-1"],
  metadata: { layout: {} },
}

const catalog: AutomationNodeCatalog = {
  schemaVersion: 1,
  maxNodes: 30,
  maxEdges: 60,
  nodes: [{
    type: "new_source_item",
    family: "trigger",
    displayName: "New Source Item",
    description: "Start after a genuinely new source item is persisted.",
    entry: true,
    terminal: true,
    runtimeStatus: "existing",
    runtimeOwner: "source",
    runtimeJobTypes: ["automation.run.start"],
    inputs: [],
    outputs: [{ name: "item", artifactTypes: ["source_item.ref", "content_item.ref"], required: false, maxConnections: null }],
    configSchema: { type: "object", properties: { sourceIds: { type: "array", items: { type: "string" } } } },
    uiHints: { icon: "radio" },
  }],
}
