import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { AutomationBuilder } from "@/features/automations/automation-builder"
import * as api from "@/features/automations/automation-api"
import { ApiError } from "@/lib/http"
import {
  connectWorkflowNodes,
  deleteWorkflowNode,
  duplicateWorkflowNode,
  moveWorkflowNode,
  validateWorkflowClient,
} from "@/features/automations/workflow-graph"

vi.mock("next/navigation", () => ({
  usePathname: () => "/automations/automation-1",
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock("@/features/automations/telegram-api", () => ({
  getTelegramAutomationOptions: vi.fn().mockResolvedValue({ sources: [], destinations: [], brandProfiles: [], promptTemplateVersions: [], aiProviderProfiles: [] }),
}))

vi.mock("@/features/automations/automation-api", () => ({
  activateAutomation: vi.fn(),
  createAutomation: vi.fn(),
  createAutomationVersion: vi.fn(),
  getAutomation: vi.fn(),
  getAutomationNodeCatalog: vi.fn(),
  getAutomationResourceCatalog: vi.fn(),
  pauseAutomation: vi.fn(),
  resumeAutomation: vi.fn(),
  startAutomationRun: vi.fn(),
  validateAutomationVersion: vi.fn(),
}))

describe("Phase 4 automation builder", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getAutomation).mockResolvedValue(detail as never)
    vi.mocked(api.getAutomationNodeCatalog).mockResolvedValue(catalog as never)
    vi.mocked(api.getAutomationResourceCatalog).mockResolvedValue({ resources: [] })
    vi.mocked(api.createAutomationVersion).mockImplementation(async (_id, input) => ({ ...version, version: 2, id: "version-2", graph: input.graph } as never))
    window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })
  })

  it("adds a compatible step without drag, supports undo/redo, and saves canonical graph", async () => {
    renderBuilder()
    expect(await screen.findByRole("region", { name: "Ordered workflow editor" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Select Generate content package" }))
    fireEvent.click(screen.getByRole("button", { name: "Add next step" }))
    const sheet = await screen.findByRole("dialog")
    fireEvent.click(within(sheet).getByRole("button", { name: /Validate/ }))

    expect(screen.getByRole("article", { name: "Step 3: Validate" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled()
    fireEvent.click(screen.getByRole("button", { name: "Undo workflow change" }))
    expect(screen.queryByRole("article", { name: "Step 3: Validate" })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Redo workflow change" }))
    expect(screen.getByRole("article", { name: "Step 3: Validate" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Save draft" }))
    await waitFor(() => expect(api.createAutomationVersion).toHaveBeenCalled())
    const saved = vi.mocked(api.createAutomationVersion).mock.calls[0][1].graph
    expect(saved.nodes.map((node) => node.type)).toEqual(["manual", "generate_content_pack", "save_drafts", "validate"])
    expect(saved.edges).toContainEqual(expect.objectContaining({ sourceNodeId: "generate-1", targetNodeId: "validate-1" }))
    expect(JSON.stringify(saved)).not.toMatch(/password|secret|prompt_body|authorization/i)
  })

  it("keeps editor errors compact, high-contrast, and dismissible", async () => {
    const errorText = "Workflow validation failed because this long message must wrap without forcing a fixed-width notification."
    vi.mocked(api.validateAutomationVersion).mockRejectedValue(new Error(errorText))
    renderBuilder()
    await screen.findByRole("region", { name: "Ordered workflow editor" })

    fireEvent.click(screen.getByRole("button", { name: "More workflow actions" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "Validate saved version" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent(errorText)
    expect(alert).toHaveClass("w-fit", "max-w-[min(40rem,calc(100%-1.5rem))]", "p-1.5", "bg-[#001F54]", "text-white")
    expect(within(alert).getByText(errorText)).toHaveClass("break-words", "text-white")
    expect(within(alert).getByRole("button", { name: "Dismiss workflow message" })).toHaveClass("min-h-11", "min-w-11", "text-white/90")

    fireEvent.click(within(alert).getByRole("button", { name: "Dismiss workflow message" }))
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("opens an empty draft without defaults and saves only the steps added by the user", async () => {
    vi.mocked(api.getAutomation).mockResolvedValue(emptyDetail as never)
    renderBuilder()
    const editor = await screen.findByRole("region", { name: "Ordered workflow editor" })

    expect(within(editor).queryByRole("article")).not.toBeInTheDocument()
    fireEvent.click(within(editor).getByRole("button", { name: "Add next step" }))
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Add next step" })).getByRole("button", { name: "Manual" }))
    fireEvent.click(within(editor).getByRole("button", { name: "Add next step" }))
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Add next step" })).getByRole("button", { name: "Generate content package" }))
    fireEvent.click(within(editor).getByRole("button", { name: "Add next step" }))
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Add next step" })).getByRole("button", { name: "Save to Drafts" }))

    expect(within(editor).getAllByRole("article")).toHaveLength(3)
    expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled()
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }))
    await waitFor(() => expect(api.createAutomationVersion).toHaveBeenCalled())
    const saved = vi.mocked(api.createAutomationVersion).mock.calls[0][1].graph
    expect(saved.nodes.map((node) => node.type)).toEqual(["manual", "generate_content_pack", "save_drafts"])
    expect(saved.edges).toHaveLength(2)
    expect(saved.outputNodeIds).toEqual(["save-drafts-1"])
  })

  it("keeps unsaved state and offers reload/copy recovery on version conflict", async () => {
    vi.mocked(api.createAutomationVersion).mockRejectedValue(new ApiError("Conflict", 409, JSON.stringify({ detail: { code: "automation_version_conflict" } })))
    renderBuilder()
    await screen.findByRole("region", { name: "Ordered workflow editor" })
    fireEvent.click(screen.getByRole("button", { name: "Select Generate content package" }))
    fireEvent.click(screen.getByRole("button", { name: "Add next step" }))
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /Validate/ }))
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }))

    expect(await screen.findByRole("heading", { name: "Workflow changed on server" })).toBeInTheDocument()
    expect(screen.getByText("Current unsaved graph remains in this editor until you choose.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Create recovery copy" })).toBeInTheDocument()
  })

  it("customizes the correct node through a draft-safe modal and preserves validation", async () => {
    renderBuilder()
    const editor = await screen.findByRole("region", { name: "Ordered workflow editor" })
    const editOutput = within(editor).getByRole("button", { name: "Edit Save to Drafts settings" })

    fireEvent.click(editOutput)
    let dialog = await screen.findByRole("dialog", { name: "Customize Save to Drafts" })
    const batchSize = within(dialog).getByLabelText("Batch size")
    fireEvent.change(batchSize, { target: { value: "8" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }))
    expect(dialog).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Save draft", hidden: true })).toBeDisabled()

    fireEvent.change(batchSize, { target: { value: "3" } })
    fireEvent.keyDown(document, { key: "Escape" })
    expect(within(dialog).getByText("Discard unsaved node changes?")).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
    fireEvent.click(within(dialog).getByRole("button", { name: "Discard changes" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Customize Save to Drafts" })).not.toBeInTheDocument())
    expect(editOutput).toHaveFocus()

    fireEvent.click(editOutput)
    dialog = await screen.findByRole("dialog", { name: "Customize Save to Drafts" })
    expect(within(dialog).getByLabelText("Batch size")).toHaveValue(null)
    fireEvent.change(within(dialog).getByLabelText("Batch size"), { target: { value: "3" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Customize Save to Drafts" })).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole("button", { name: "Save draft" }))
    await waitFor(() => expect(api.createAutomationVersion).toHaveBeenCalled())
    const saved = vi.mocked(api.createAutomationVersion).mock.calls[0][1].graph
    expect(saved.nodes.find((node) => node.id === "draft-1")?.config).toEqual({ batchSize: 3 })
  })

  it("closes customization with Escape when no node changes exist", async () => {
    renderBuilder()
    const editor = await screen.findByRole("region", { name: "Ordered workflow editor" })
    fireEvent.click(within(editor).getByRole("button", { name: "Edit Save to Drafts settings" }))
    expect(await screen.findByRole("dialog", { name: "Customize Save to Drafts" })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Customize Save to Drafts" })).not.toBeInTheDocument())
  })

  it("validates and duplicates compatible linear steps without losing backend graph shape", () => {
    const filterGraph = {
      ...graph,
      nodes: [graph.nodes[0], { id: "filter-1", type: "filter_content", config: {} }, graph.nodes[1], graph.nodes[2]],
      edges: [
        { sourceNodeId: "trigger-1", sourcePort: "story", targetNodeId: "filter-1", targetPort: "story" },
        { sourceNodeId: "filter-1", sourcePort: "accepted", targetNodeId: "generate-1", targetPort: "story" },
        graph.edges[1],
      ],
    }
    const duplicated = duplicateWorkflowNode(filterGraph, catalog as never, "filter-1")
    expect(duplicated.graph?.nodes.filter((node) => node.type === "filter_content")).toHaveLength(2)
    expect(duplicated.graph && validateWorkflowClient(duplicated.graph, catalog as never).findings.filter((item) => item.code.startsWith("graph_"))).toEqual([])
  })

  it("supports deterministic reorder/delete and rejects unsafe or invalid connections", () => {
    const filterGraph = {
      ...graph,
      nodes: [graph.nodes[0], { id: "filter-1", type: "filter_content", config: {} }, { id: "filter-2", type: "filter_content", config: {} }, graph.nodes[1], graph.nodes[2]],
      edges: [
        { sourceNodeId: "trigger-1", sourcePort: "story", targetNodeId: "filter-1", targetPort: "story" },
        { sourceNodeId: "filter-1", sourcePort: "accepted", targetNodeId: "filter-2", targetPort: "story" },
        { sourceNodeId: "filter-2", sourcePort: "accepted", targetNodeId: "generate-1", targetPort: "story" },
        graph.edges[1],
      ],
    }
    const moved = moveWorkflowNode(filterGraph, catalog as never, "filter-2", -1)
    expect(moved.graph && moved.graph.nodes.map((node) => node.id)).toEqual(["trigger-1", "filter-2", "filter-1", "generate-1", "draft-1"])
    const deleted = moved.graph && deleteWorkflowNode(moved.graph, catalog as never, "filter-1")
    expect(deleted?.graph?.edges).toContainEqual({ sourceNodeId: "filter-2", sourcePort: "accepted", targetNodeId: "generate-1", targetPort: "story" })

    expect(connectWorkflowNodes(graph, catalog as never, { sourceNodeId: "trigger-1", sourcePort: "story", targetNodeId: "draft-1", targetPort: "drafts" }).error).toMatch(/incompatible/i)
    expect(connectWorkflowNodes(graph, catalog as never, { sourceNodeId: "generate-1", sourcePort: "drafts", targetNodeId: "generate-1", targetPort: "story" }).error).toMatch(/itself/i)
    const unsafe = { ...graph, nodes: graph.nodes.map((node) => node.id === "generate-1" ? { ...node, config: { apiKey: "credential-canary" } } : node) }
    expect(validateWorkflowClient(unsafe, catalog as never).findings).toContainEqual(expect.objectContaining({ code: "node_config_invalid", fieldPath: "config.apiKey" }))
  })

  it("requires authoritative validation before activate and can pause the updated revision", async () => {
    vi.mocked(api.validateAutomationVersion).mockResolvedValue({ valid: true, graphHash: "validated", findings: [] })
    vi.mocked(api.activateAutomation).mockResolvedValue({ ...detail, lifecycle: "active", revision: 2 } as never)
    vi.mocked(api.pauseAutomation).mockResolvedValue({ ...detail, lifecycle: "paused", revision: 3 } as never)
    renderBuilder()
    await screen.findByRole("region", { name: "Ordered workflow editor" })

    expect(screen.getByRole("button", { name: "Activate" })).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: "More workflow actions" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "Validate saved version" }))
    await waitFor(() => expect(screen.getByRole("button", { name: "Activate" })).toBeEnabled())
    fireEvent.click(screen.getByRole("button", { name: "Activate" }))
    await waitFor(() => expect(api.activateAutomation).toHaveBeenCalledWith("automation-1", 1, expect.stringContaining("workflow-activate-")))
    fireEvent.click(await screen.findByRole("button", { name: "Pause" }))
    await waitFor(() => expect(api.pauseAutomation).toHaveBeenCalledWith("automation-1", 2))
  })
})

function renderBuilder() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><AutomationBuilder automationId="automation-1" /></QueryClientProvider>)
}

const graph = {
  schemaVersion: 1 as const,
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
  metadata: { layout: { "trigger-1": { x: 80, y: 120 }, "generate-1": { x: 340, y: 120 }, "draft-1": { x: 600, y: 120 } } },
}
const version = { id: "version-1", automationId: "automation-1", version: 1, schemaVersion: 1, graph, graphHash: "hash", compilerVersion: "1", compiledPlan: {}, validationSummary: { valid: false, graphHash: "hash", findings: [] }, creationActorType: "human", creationActorId: "owner", creationReason: "created", createdAt: "2026-08-01T08:00:00Z" }
const detail = { id: "automation-1", name: "Morning newsroom", description: "Daily package", lifecycle: "inactive", ownerType: "operator_managed", revision: 1, activeVersionId: null, draftVersionId: "version-1", archivedAt: null, createdAt: "2026-08-01T08:00:00Z", updatedAt: "2026-08-01T08:00:00Z", draftVersion: version, activeVersion: null, legacyRouteId: null }
const emptyGraph = { schemaVersion: 1 as const, entryNodeId: "", nodes: [], edges: [], outputNodeIds: [], metadata: { layout: {} } }
const emptyVersion = { ...version, id: "empty-version", graph: emptyGraph, graphHash: "empty-hash", validationSummary: { valid: false, graphHash: "empty-hash", findings: [] } }
const emptyDetail = { ...detail, draftVersionId: "empty-version", draftVersion: emptyVersion }

const catalog = {
  schemaVersion: 1 as const, maxNodes: 30, maxEdges: 60,
  nodes: [
    node("manual", "trigger", "Manual", true, false, [], [port("story", "story.revision_ref", null)]),
    node("filter_content", "select_filter", "Filter content", false, false, [port("story", "story.revision_ref", 1)], [port("accepted", "story.revision_ref", null)]),
    node("generate_content_pack", "generate", "Generate content package", false, false, [port("story", "story.revision_ref", 1)], [port("drafts", "draft.revision_set_ref", null)]),
    node("validate", "validate", "Validate", false, false, [port("drafts", "draft.revision_set_ref", 1)], [port("valid", "draft.validated_revision_set_ref", null)]),
    { ...node("save_drafts", "output", "Save to Drafts", false, true, [port("drafts", "draft.revision_set_ref", 1)], []), inputs: [{ name: "drafts", artifactTypes: ["draft.revision_set_ref", "draft.validated_revision_set_ref"], required: true, maxConnections: 1 }], configSchema: { type: "object", properties: { batchSize: { type: "integer", title: "Batch size", minimum: 1, maximum: 5 } } } },
  ],
}
function port(name: string, artifact: string, maxConnections: number | null) { return { name, artifactTypes: [artifact], required: true, maxConnections } }
function node(type: string, family: string, displayName: string, entry: boolean, terminal: boolean, inputs: unknown[], outputs: unknown[]) { return { type, family, displayName, description: `${displayName} description`, entry, terminal, runtimeStatus: "existing" as const, runtimeOwner: "compiler" as const, runtimeJobTypes: [], inputs, outputs, configSchema: { type: "object", properties: {} }, uiHints: {} } }
