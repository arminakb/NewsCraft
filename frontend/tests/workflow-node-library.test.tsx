import { fireEvent, render, screen } from "@testing-library/react"

import { NodePicker, WorkflowNodeLibrary } from "@/features/automations/workflow-node-library"

describe("workflow node library", () => {
  it("renders the server catalog, including the collection article trigger", () => {
    const onAdd = vi.fn()
    const { container } = render(<WorkflowNodeLibrary allowEntry catalog={catalog as never} issueCount={2} onAdd={onAdd} />)

    expect(screen.getByRole("heading", { name: "Node library" })).toBeInTheDocument()
    expect(screen.getByText("2 issues")).toBeInTheDocument()
    expect(screen.getByText("Search nodes")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Collection article added" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Filter content" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "AI Research" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Telegram new item" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Generate Telegram draft" })).not.toBeInTheDocument()
    expect(container.querySelector("[data-node-library-grid]")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Collection article added" }))
    expect(onAdd).toHaveBeenCalledWith("collection_article_added")
  })

  it("keeps the accessible empty state for an empty server catalog", () => {
    const onAdd = vi.fn()
    const { container } = render(<WorkflowNodeLibrary catalog={{ ...catalog, nodes: [] } as never} issueCount={2} onAdd={onAdd} />)

    expect(screen.getByRole("status")).toHaveTextContent("No nodes available")
    expect(screen.getByText("Node definitions will appear here when they are ready to add.")).toBeInTheDocument()
    expect(screen.queryByText("Search nodes")).not.toBeInTheDocument()
    expect(container.querySelector("[data-node-library-grid]")).toBeNull()
    expect(onAdd).not.toHaveBeenCalled()
  })

  it("keeps catalog picker available for ordered-editor add-step flows", () => {
    const onAdd = vi.fn()
    const { container } = render(<NodePicker catalog={catalog as never} onAdd={onAdd} />)

    const tile = screen.getByRole("button", { name: "Filter content" })
    expect(container.querySelector("[data-node-library-grid]")).toBeInTheDocument()
    expect(tile).toHaveAttribute("draggable", "true")
    fireEvent.click(tile)
    expect(onAdd).toHaveBeenCalledWith("filter_content")
  })
})

const catalog = {
  schemaVersion: 1,
  maxNodes: 30,
  maxEdges: 60,
  nodes: [
    node("manual", "trigger", "Manual", true, "Trigger description"),
    node("collection_article_added", "trigger", "Collection article added", true, "Start when an article is saved to a Feed collection."),
    node("filter_content", "select_filter", "Filter content", false, "Long filter instructions must stay out of the tile."),
    node("research", "research", "AI Research", false, "Research description"),
    node("generate_content_pack", "generate", "Generate content package", false, "Generate description"),
    node("save_drafts", "output", "Save to Drafts", false, "Output description"),
  ],
}

function node(type: string, family: string, displayName: string, entry: boolean, description: string) {
  return {
    type,
    family,
    displayName,
    description,
    entry,
    terminal: family === "output",
    runtimeStatus: "existing",
    runtimeOwner: "compiler",
    runtimeJobTypes: [],
    inputs: [],
    outputs: [],
    configSchema: { type: "object", properties: {} },
    uiHints: { icon: "filter" },
  }
}
