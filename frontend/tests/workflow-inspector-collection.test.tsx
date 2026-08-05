import { fireEvent, render, screen } from "@testing-library/react"

import { WorkflowInspector } from "@/features/automations/workflow-inspector"
import type { ArticleCollection } from "@/features/articles/types"
import type { AutomationNodeCatalog } from "@/features/automations/automation-types"

type InspectorProps = Parameters<typeof WorkflowInspector>[0]

const collectionId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

describe("collection trigger inspector", () => {
  it("exposes loading, empty, and recovery states", () => {
    const props = baseProps()
    const { rerender } = render(<WorkflowInspector {...props} collectionsPending />)
    expect(screen.getByRole("status")).toHaveTextContent("Loading Feed collections")

    rerender(<WorkflowInspector {...props} collections={[]} />)
    expect(screen.getByRole("status")).toHaveTextContent("No Feed collections yet")
    expect(screen.getByRole("link", { name: /Create Feed collection/i })).toHaveAttribute("href", "/feed")

    rerender(<WorkflowInspector {...props} collectionsError={new Error("Feed unavailable")} onRetryCollections={props.onRetryCollections} />)
    expect(screen.getByRole("alert")).toHaveTextContent("Feed unavailable")
    fireEvent.click(screen.getByRole("button", { name: "Retry collections" }))
    expect(props.onRetryCollections).toHaveBeenCalledTimes(1)
  })

  it("selects exactly one stable collection ID", () => {
    const onGraphChange = vi.fn()
    render(<WorkflowInspector {...baseProps({ onGraphChange })} collections={[collection]} />)

    const select = screen.getByLabelText("Feed collection")
    expect(select).toHaveValue("")
    fireEvent.change(select, { target: { value: collectionId } })
    expect(onGraphChange).toHaveBeenCalledWith(expect.objectContaining({
      nodes: [expect.objectContaining({ config: { collectionId } })],
    }))
  })
})

function baseProps(overrides: Partial<InspectorProps> = {}): InspectorProps {
  return {
    graph,
    catalog,
    selectedNodeId: "collection-trigger-1",
    resources: [],
    findings: [],
    onGraphChange: vi.fn(),
    onRejected: vi.fn(),
    onRetryCollections: vi.fn(),
    ...overrides,
  }
}

const graph = {
  schemaVersion: 1 as const,
  entryNodeId: "collection-trigger-1",
  nodes: [{ id: "collection-trigger-1", type: "collection_article_added", config: {} }],
  edges: [],
  outputNodeIds: [],
  metadata: { layout: {} },
}

const collection = {
  id: collectionId,
  name: "Reading queue",
  articleCount: 0,
  createdAt: "2026-08-05T00:00:00Z",
  updatedAt: "2026-08-05T00:00:00Z",
} satisfies ArticleCollection

const catalog = {
  schemaVersion: 1,
  maxNodes: 30,
  maxEdges: 60,
  nodes: [{
    type: "collection_article_added",
    family: "trigger",
    displayName: "Collection article added",
    description: "Start when a new article is saved to one Feed collection.",
    entry: true,
    terminal: true,
    runtimeStatus: "existing",
    runtimeOwner: "compiler",
    runtimeJobTypes: ["automation.run.start"],
    inputs: [],
    outputs: [{ name: "article", artifactTypes: ["article.collection_added"], required: false, maxConnections: null }],
    configSchema: { type: "object", properties: { collectionId: { type: "string", title: "Collection" } } },
    uiHints: { icon: "file-text" },
  }],
} satisfies AutomationNodeCatalog
