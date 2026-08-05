import { fireEvent, render, screen, within } from "@testing-library/react"

import { WorkflowInspector } from "@/features/automations/workflow-inspector"
import { WorkflowOrderedEditor } from "@/features/automations/workflow-ordered-editor"
import { validateWorkflowClient } from "@/features/automations/workflow-graph"

describe("Phase 4 workflow editor accessibility", () => {
  it("exposes named native controls for full non-drag editing", () => {
    const onSelected = vi.fn()
    const validation = validateWorkflowClient(graph, catalog as never)
    render(<WorkflowOrderedEditor graph={graph} catalog={catalog as never} validation={validation} selectedNodeId="generate-1" onGraphChange={vi.fn()} onSelectedNodeChange={onSelected} onInspect={vi.fn()} onRejected={vi.fn()} />)

    const editor = screen.getByRole("region", { name: "Ordered workflow editor" })
    expect(within(editor).getByRole("button", { name: "Add next step" })).toHaveClass("min-h-11")
    expect(within(editor).getByRole("button", { name: "Move Generate content package up" })).toBeInTheDocument()
    expect(within(editor).getByRole("button", { name: "Move Generate content package down" })).toBeInTheDocument()
    expect(within(editor).getByRole("button", { name: "Edit Generate content package settings" })).toBeInTheDocument()
    expect(within(editor).getByRole("button", { name: "Delete Generate content package" })).toBeInTheDocument()
    fireEvent.click(within(editor).getByRole("button", { name: "Select Generate content package" }))
    expect(onSelected).toHaveBeenCalledWith("generate-1")
  })

  it("announces validation beyond color and never renders credential controls or raw JSON", () => {
    const unsafeCatalog = { ...catalog, nodes: catalog.nodes.map((item) => item.type === "generate_content_pack" ? { ...item, configSchema: { type: "object", properties: { providerProfileId: { anyOf: [{ type: "string" }, { type: "null" }], title: "Provider" }, apiKey: { type: "string", title: "API key" }, password: { type: "string", title: "Password" }, retryPolicy: { type: "object", title: "Retry policy" } } } } : item) }
    const validation = validateWorkflowClient(graph, unsafeCatalog as never)
    render(<WorkflowInspector graph={graph} catalog={unsafeCatalog as never} selectedNodeId="generate-1" resources={[{ id: "missing", kind: "provider", displayName: "Unavailable provider", state: "unavailable", reasonCode: "resource_missing", capabilities: [], referencedByActiveVersion: false, manageHref: "/settings?section=llm-providers" }]} findings={validation.findings} onGraphChange={vi.fn()} onRejected={vi.fn()} />)

    expect(screen.getAllByText("Required resource is not configured.").length).toBeGreaterThan(0)
    expect(screen.getByRole("link", { name: /Configure provider/i })).toHaveAttribute("href", "/settings?section=llm-providers")
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/api key/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/[{}][\s\S]*[{}]/)).not.toBeInTheDocument()
    expect(screen.getByDisplayValue("Managed structured policy")).toHaveAttribute("readonly")
  })

  it("keeps stale saved connections recoverable instead of crashing inspector", () => {
    const staleGraph = {
      ...graph,
      edges: [graph.edges[0], { sourceNodeId: "generate-1", sourcePort: "drafts", targetNodeId: "removed-output", targetPort: "drafts" }],
    }
    render(<WorkflowInspector graph={staleGraph} catalog={catalog as never} selectedNodeId="generate-1" resources={[]} findings={[]} onGraphChange={vi.fn()} onRejected={vi.fn()} />)

    expect(screen.getByRole("alert")).toHaveTextContent("Saved connection references an unavailable step")
  })

  it("announces retired saved steps and offers explicit removal", () => {
    const unsupportedGraph = {
      ...graph,
      nodes: [graph.nodes[0], { id: "legacy-1", type: "telegram_new_item", config: {} }, graph.nodes[2]],
      edges: [
        { sourceNodeId: "trigger-1", sourcePort: "story", targetNodeId: "legacy-1", targetPort: "story" },
        { sourceNodeId: "legacy-1", sourcePort: "draft", targetNodeId: "draft-1", targetPort: "drafts" },
      ],
    }
    const validation = validateWorkflowClient(unsupportedGraph, catalog as never)
    render(<WorkflowOrderedEditor graph={unsupportedGraph} catalog={catalog as never} validation={validation} selectedNodeId="legacy-1" onGraphChange={vi.fn()} onSelectedNodeChange={vi.fn()} onInspect={vi.fn()} onRejected={vi.fn()} />)

    expect(screen.getByRole("alert", { name: "Step 2: Unsupported saved step" })).toHaveTextContent("not replaced automatically")
    expect(screen.getByRole("button", { name: "Remove unsupported step" })).toBeInTheDocument()
  })

  it("shows the same retired-step state in the inspector", () => {
    const unsupportedGraph = {
      ...graph,
      nodes: [...graph.nodes, { id: "legacy-1", type: "generate_telegram", config: {} }],
    }
    const validation = validateWorkflowClient(unsupportedGraph, catalog as never)
    render(<WorkflowInspector graph={unsupportedGraph} catalog={catalog as never} selectedNodeId="legacy-1" resources={[]} findings={validation.findings} onGraphChange={vi.fn()} onRejected={vi.fn()} />)

    expect(screen.getByRole("alert", { name: "Unsupported saved step" })).toHaveTextContent("generate_telegram")
    expect(screen.getByRole("button", { name: "Remove unsupported step" })).toBeInTheDocument()
  })
})

const graph = {
  schemaVersion: 1 as const,
  entryNodeId: "trigger-1",
  nodes: [{ id: "trigger-1", type: "manual", config: {} }, { id: "generate-1", type: "generate_content_pack", config: {} }, { id: "draft-1", type: "save_drafts", config: {} }],
  edges: [{ sourceNodeId: "trigger-1", sourcePort: "story", targetNodeId: "generate-1", targetPort: "story" }, { sourceNodeId: "generate-1", sourcePort: "drafts", targetNodeId: "draft-1", targetPort: "drafts" }],
  outputNodeIds: ["draft-1"], metadata: { layout: {} },
}
const catalog = { schemaVersion: 1 as const, maxNodes: 30, maxEdges: 60, nodes: [node("manual", "trigger", "Manual", true, false, [], [port("story", ["story.revision_ref"], null)]), node("generate_content_pack", "generate", "Generate content package", false, false, [port("story", ["story.revision_ref"], 1)], [port("drafts", ["draft.revision_set_ref"], null)]), node("save_drafts", "output", "Save to Drafts", false, true, [port("drafts", ["draft.revision_set_ref", "draft.validated_revision_set_ref"], 1)], [])] }
function port(name: string, artifactTypes: string[], maxConnections: number | null) { return { name, artifactTypes, required: true, maxConnections } }
function node(type: string, family: string, displayName: string, entry: boolean, terminal: boolean, inputs: unknown[], outputs: unknown[]) { return { type, family, displayName, description: `${displayName} description`, entry, terminal, runtimeStatus: "existing" as const, runtimeOwner: "compiler" as const, runtimeJobTypes: [], inputs, outputs, configSchema: { type: "object", properties: {} }, uiHints: {} } }
