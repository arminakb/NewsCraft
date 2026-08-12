import { fireEvent, render, screen, within } from "@testing-library/react"

import { WorkflowValidationDialog } from "@/features/automations/workflow-validation-dialog"

describe("workflow validation dialog", () => {
  it("renders backend-shaped findings grouped by node with readable context", () => {
    const onOpenChange = vi.fn()
    const onSelectNode = vi.fn()
    const findings = [
      finding("automation_resource_unavailable", "Required resource is not configured.", "generate-1", "Select a saved resource.", "config.providerProfileId"),
      finding("node_config_invalid", "Credential and executable fields are prohibited.", "generate-1", "Remove unsafe field.", "config.apiKey"),
      finding("edge_port_invalid", "Connected ports require incompatible artifact capabilities.", null, "Choose a compatible output.", null, 0),
      finding("graph_unreachable_node", "Step is not connected to trigger.", "draft-1", "Connect or remove the step.", null),
    ]

    render(<WorkflowValidationDialog catalog={catalog as never} findings={findings} graph={graph as never} onOpenChange={onOpenChange} onSelectNode={onSelectNode} open returnFocus={null} />)

    const dialog = screen.getByRole("dialog", { name: "Needs attention" })
    expect(within(dialog).getByText(/4 issues found\./)).toBeInTheDocument()
    expect(within(dialog).getByRole("heading", { name: "Generate content package" })).toBeInTheDocument()
    expect(within(dialog).getByText("Required resource is not configured.")).toBeInTheDocument()
    expect(within(dialog).getByText("Credential and executable fields are prohibited.")).toBeInTheDocument()
    expect(within(dialog).getByText("Field: Config · Provider Profile Id")).toBeInTheDocument()
    expect(within(dialog).getByText("Workflow connection")).toBeInTheDocument()
    expect(within(dialog).getAllByText("Error", { exact: true })).toHaveLength(4)

    fireEvent.click(within(dialog).getByRole("button", { name: "Select Generate content package" }))
    expect(onSelectNode).toHaveBeenCalledWith("generate-1")
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it("keeps long issue lists inside a bounded scroll region and closes normally", () => {
    const onOpenChange = vi.fn()
    const findings = Array.from({ length: 7 }, (_value, index) => finding(`issue_${index}`, `Issue ${index + 1}`, "generate-1", null, null))

    render(<WorkflowValidationDialog catalog={catalog as never} findings={findings} graph={graph as never} onOpenChange={onOpenChange} open returnFocus={null} />)

    expect(screen.getByText(/7 issues found\./)).toBeInTheDocument()
    expect(screen.getAllByRole("listitem")).toHaveLength(7)
    expect(document.querySelector(".overflow-y-auto")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Close needs attention" }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})

const graph = {
  schemaVersion: 1,
  entryNodeId: "trigger-1",
  nodes: [
    { id: "trigger-1", type: "manual", config: {} },
    { id: "generate-1", type: "generate_content_pack", config: {} },
    { id: "draft-1", type: "save_drafts", config: {} },
  ],
  edges: [
    { sourceNodeId: "trigger-1", sourcePort: "story", targetNodeId: "generate-1", targetPort: "story" },
    { sourceNodeId: "generate-1", sourcePort: "drafts", targetNodeId: "draft-1", targetPort: "drafts" },
  ],
  outputNodeIds: ["draft-1"],
  metadata: { layout: {} },
}

const catalog = {
  schemaVersion: 1,
  maxNodes: 30,
  maxEdges: 60,
  nodes: [
    node("manual", "Manual"),
    node("generate_content_pack", "Generate content package"),
    node("save_drafts", "Save to Drafts"),
  ],
}

function node(type: string, displayName: string) {
  return {
    type,
    family: "workflow",
    displayName,
    description: `${displayName} description`,
    entry: type === "manual",
    terminal: type === "save_drafts",
    runtimeStatus: "existing",
    runtimeOwner: "compiler",
    runtimeJobTypes: [],
    inputs: [],
    outputs: [],
    configSchema: { type: "object", properties: {} },
    uiHints: { icon: "filter" },
  }
}

function finding(code: string, message: string, nodeId: string | null, recoveryAction: string | null, fieldPath: string | null, edgeIndex: number | null = null) {
  return { code, severity: "error" as const, message, nodeId, edgeIndex, fieldPath, recoveryAction }
}
