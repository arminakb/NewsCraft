import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import { AutomationTemplatesPage } from "@/features/automations/automation-templates-page"
import * as api from "@/features/automations/automation-api"
import { NewWorkflowPage } from "@/features/automations/new-workflow-page"
import { WorkflowLibrary } from "@/features/automations/workflow-library"
import { summarizePreviewStages } from "@/features/automations/workflow-mini-preview"
import type { AutomationPlatform, AutomationPreview, AutomationPreviewStage } from "@/features/automations/automation-types"

const push = vi.fn()
const searchParams = new URLSearchParams()

vi.mock("next/navigation", () => ({
  usePathname: () => "/automations",
  useRouter: () => ({ push }),
  useSearchParams: () => searchParams,
}))

vi.mock("@/features/automations/automation-api", () => ({
  activateAutomation: vi.fn(),
  archiveAutomation: vi.fn(),
  createAutomation: vi.fn(),
  createAutomationFromTemplate: vi.fn(),
  duplicateAutomation: vi.fn(),
  getAutomation: vi.fn(),
  getAutomationNodeCatalog: vi.fn(),
  getAutomationResourceCatalog: vi.fn(),
  getAutomationRuns: vi.fn(),
  getAutomations: vi.fn(),
  getAutomationTemplates: vi.fn(),
  pauseAutomation: vi.fn(),
  resumeAutomation: vi.fn(),
}))

describe("workflow gallery", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    searchParams.delete("blank")
    searchParams.delete("name")
    vi.mocked(api.getAutomationRuns).mockResolvedValue({ items: [], nextCursor: null })
  })

  it("keeps empty, loading, and error states useful", async () => {
    vi.mocked(api.getAutomations).mockResolvedValue({ items: [], nextCursor: null })
    const empty = renderPage(<WorkflowLibrary />)
    expect(await screen.findByRole("heading", { name: "No workflows yet" })).toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: /^Runs$/ })).not.toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /^Workflows$/ })).toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: /^Templates$/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Automations" })).not.toBeInTheDocument()
    expect(screen.queryByText("Build, validate, and operate versioned newsroom workflows.", { exact: true })).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Telegram routes" })).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "New workflow" })).not.toBeInTheDocument()
    expect(empty.container.querySelector("[data-slot='page-header']")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Create new workflow" })).toBeInTheDocument()
    expect(screen.queryByText("Start from a template", { exact: true })).not.toBeInTheDocument()
    expect(screen.queryByText("Create a blank workflow", { exact: true })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Create new workflow" }))
    expect(screen.getByRole("dialog", { name: "Name your workflow" })).toBeInTheDocument()
    expect(push).not.toHaveBeenCalled()
    const nameInput = screen.getByRole("textbox", { name: "Workflow name" })
    fireEvent.change(nameInput, { target: { value: "   " } })
    fireEvent.blur(nameInput)
    expect(nameInput).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a workflow name.")
    fireEvent.click(screen.getByRole("button", { name: "Create workflow" }))
    expect(push).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    empty.unmount()

    vi.mocked(api.getAutomations).mockReturnValue(new Promise(() => {}))
    const loading = renderPage(<WorkflowLibrary />)
    expect(await screen.findByRole("status")).toHaveTextContent("Loading workflows")
    loading.unmount()

    vi.mocked(api.getAutomations).mockRejectedValue(new Error("library offline"))
    renderPage(<WorkflowLibrary />)
    expect(await screen.findByRole("heading", { name: "Workflow library unavailable" })).toBeInTheDocument()
    expect(screen.getByText("library offline")).toBeInTheDocument()
  })

  it("renders compact cards entirely from bounded list summaries", async () => {
    vi.mocked(api.getAutomations).mockResolvedValue({ items: [automation()], nextCursor: null } as never)
    const view = renderPage(<WorkflowLibrary />)

    expect(await screen.findByText("Morning newsroom")).toBeInTheDocument()
    expect(screen.getByRole("img", { name: "Output platform: Draft" })).toBeInTheDocument()
    expect(screen.getByRole("img", { name: "Workflow stages: Manual, AI generation, Save to Drafts." })).toBeInTheDocument()
    expect(screen.getByText("Manual", { selector: "span[title='Manual']" })).toBeInTheDocument()
    expect(screen.getByText("Manual to Draft", { selector: ".sr-only" })).toBeInTheDocument()
    expect(view.container.querySelector("[data-stage-type='generate_content_pack'] .lucide-bot")).toBeInTheDocument()
    expect(view.container.querySelector("[data-workflow-card] [data-slot='badge']")).not.toBeInTheDocument()
    expect(screen.getByText("Not run yet")).toBeInTheDocument()
    expect(screen.queryByText("Daily package")).not.toBeInTheDocument()
    expect(screen.queryByText("Provider")).not.toBeInTheDocument()
    expect(api.getAutomation).not.toHaveBeenCalled()
    expect(api.getAutomationRuns).not.toHaveBeenCalled()
    expect(api.getAutomationResourceCatalog).not.toHaveBeenCalled()
    expect(view.container.querySelectorAll("[data-workflow-card]")).toHaveLength(1)
  })

  it("shows exactly Empty for a workflow with no preview stages", async () => {
    vi.mocked(api.getAutomations).mockResolvedValue({
      items: [automation({ preview: { ...preview("unknown"), stages: [], outputPlatforms: ["unknown"] } })],
      nextCursor: null,
    } as never)
    renderPage(<WorkflowLibrary />)

    expect(await screen.findByText("Empty", { exact: true })).toBeInTheDocument()
    expect(screen.queryByText("Workflow preview unavailable")).not.toBeInTheDocument()
  })

  it("shows output identity from actual preview outputs, including fallback cases", async () => {
    vi.mocked(api.getAutomations).mockResolvedValue({
      items: [
        automation({ id: "telegram", name: "Newsroom channel", preview: preview("telegram") }),
        automation({ id: "draft", name: "Research notes", preview: preview("draft") }),
        automation({ id: "multi", name: "Distribution package", preview: preview("multi") }),
        automation({ id: "custom", name: "Custom handoff", preview: preview("unknown") }),
      ],
      nextCursor: null,
    } as never)
    renderPage(<WorkflowLibrary />)

    expect(await screen.findByRole("img", { name: "Output platform: Telegram" })).toBeInTheDocument()
    expect(screen.getByRole("img", { name: "Output platform: Draft" })).toBeInTheDocument()
    expect(screen.getByRole("img", { name: "Output platform: X + Blog" })).toBeInTheDocument()
    expect(screen.getByRole("img", { name: "Output platform: Custom output" })).toBeInTheDocument()
    expect(document.querySelector("[data-platform-logo='telegram']")).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/api[_ -]?key|password|secret[_ -]?ref|credential-canary/i)
  })

  it("uses deterministic paths, preserves endpoints, and collapses long workflows", async () => {
    const longStages = [
      stage("trigger", "manual", "Manual", "trigger"),
      stage("select", "select_content", "Select content", "content"),
      stage("filter", "filter_content", "Filter content", "content"),
      stage("research", "research", "AI Research", "content"),
      stage("generate", "generate_content_pack", "Generate content package", "ai"),
      stage("validate", "validate", "Validate", "validation"),
      stage("review", "human_review", "Human Review", "review", [], true),
      stage("publish", "telegram_publish", "Publish to Telegram", "publish", ["telegram"]),
    ]
    const collapsed = summarizePreviewStages(longStages)
    expect(collapsed.visible[0].nodeId).toBe("trigger")
    expect(collapsed.visible.at(-1)?.nodeId).toBe("publish")
    expect(collapsed.hiddenCount).toBe(4)

    vi.mocked(api.getAutomations).mockResolvedValue({
      items: [automation({
        name: "A very long workflow title that must not collide with its platform and menu controls",
        lifecycle: "paused",
        preview: { ...preview("telegram"), valid: false, stages: longStages },
      })],
      nextCursor: null,
    } as never)
    const view = renderPage(<WorkflowLibrary />)

    await screen.findByTitle(/A very long workflow title/)
    expect(screen.queryByText("Needs attention")).not.toBeInTheDocument()
    expect(screen.getByRole("img", { name: /4 additional workflow steps are collapsed visually/ })).toBeInTheDocument()
    expect(screen.getByText("+4")).toBeInTheDocument()
    expect(view.container.querySelector("[data-flow-motion='paused']")).toBeInTheDocument()
    expect(view.container.querySelector(".workflow-flow-particle")).not.toBeInTheDocument()
    expect(screen.getByTitle(/A very long workflow title/)).toBeInTheDocument()
  })

  it("searches persisted name, platform, trigger, and stage summaries and clears cleanly", async () => {
    vi.mocked(api.getAutomations).mockResolvedValue({
      items: [
        automation({ id: "telegram", name: "Breaking desk", lifecycle: "active", preview: preview("telegram") }),
        automation({ id: "draft", name: "Research notes", lifecycle: "paused", preview: {
          ...preview("draft"),
          stages: [
            stage("trigger", "manual", "Manual", "trigger"),
            stage("research", "research", "AI Research", "content"),
            stage("output", "save_drafts", "Save to Drafts", "draft", ["draft"]),
          ],
        } }),
      ],
      nextCursor: null,
    } as never)
    renderPage(<WorkflowLibrary />)

    const search = await screen.findByRole("searchbox", { name: "Search workflows" })
    const activeCard = screen.getByText("Breaking desk").closest("[data-workflow-card]")
    const pausedCard = screen.getByText("Research notes").closest("[data-workflow-card]")
    expect(activeCard).toHaveClass("border-success/40")
    expect(activeCard?.className).toContain("var(--success)")
    expect(activeCard?.querySelector("[data-slot='badge']")).toHaveTextContent("Active")
    expect(pausedCard).toHaveClass("border-warning/40")
    expect(pausedCard?.className).toContain("var(--warning)")
    expect(pausedCard?.querySelector("[data-slot='badge']")).toHaveTextContent("Paused")

    fireEvent.change(search, { target: { value: "research" } })
    expect(screen.getByText("Research notes")).toBeInTheDocument()
    expect(screen.queryByText("Breaking desk")).not.toBeInTheDocument()

    fireEvent.change(search, { target: { value: "telegram" } })
    expect(screen.getByText("Breaking desk")).toBeInTheDocument()
    expect(screen.queryByText("Research notes")).not.toBeInTheDocument()

    fireEvent.change(search, { target: { value: "nothing here" } })
    expect(screen.getByRole("heading", { name: "No workflows match" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }))
    expect(screen.getByText("Breaking desk")).toBeInTheDocument()
    expect(screen.getByText("Research notes")).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("Filter workflows by status"), { target: { value: "paused" } })
    expect(screen.queryByText("Breaking desk")).not.toBeInTheDocument()
    expect(screen.getByText("Research notes")).toBeInTheDocument()
  })

  it("uses semantic short labels, category treatments, state-aware motion, and compact success", async () => {
    const activePreview = {
      ...preview("telegram"),
      stages: [
        stage("trigger", "manual", "Manual", "trigger"),
        stage("research", "research", "AI Research", "content"),
        stage("generate", "generate_content_pack", "Generate content package", "ai"),
        stage("draft", "save_drafts", "Save to Drafts", "draft", ["telegram"]),
      ],
      runCount: 24,
      successRate: 96,
      lastRunAt: "2026-08-01T07:58:00Z",
      lastOutcome: "succeeded",
    }
    vi.mocked(api.getAutomations).mockResolvedValue({ items: [automation({ lifecycle: "active", preview: activePreview })], nextCursor: null } as never)
    const view = renderPage(<WorkflowLibrary />)

    expect((await screen.findAllByText("AI Research")).some((item) => item.tagName === "SPAN")).toBe(true)
    expect(screen.getByText("AI Generate", { selector: "span" })).toBeInTheDocument()
    expect(screen.getByText("Draft", { selector: "span" })).toBeInTheDocument()
    const endpoints = screen.getByText("Manual to Telegram", { selector: ".sr-only" }).closest("[data-workflow-endpoints]")
    const arrow = endpoints?.querySelector("[data-workflow-arrow]")
    expect(endpoints).toHaveClass("flex", "items-center")
    expect(endpoints).not.toHaveClass("text-center", "justify-center")
    expect(arrow).toHaveClass("size-3", "shrink-0")
    expect(arrow?.getAttribute("style")).toContain("/icons/right-arrow-svgrepo-com.svg")
    expect(screen.queryByText("Research", { exact: true })).not.toBeInTheDocument()
    expect(view.container.querySelector("[data-stage-category='trigger']")).toBeInTheDocument()
    expect(view.container.querySelector("[data-stage-category='ai']")).toBeInTheDocument()
    expect(view.container.querySelector("[data-stage-type='generate_content_pack'] .lucide-bot")).toBeInTheDocument()
    expect(view.container.querySelector("[data-stage-category='draft']")).toBeInTheDocument()
    expect(view.container.querySelector("[data-stage-type='save_drafts'] [data-platform-logo='telegram']")).toBeInTheDocument()
    expect(view.container.querySelectorAll("[data-flow-connector][data-animated='true']")).toHaveLength(3)
    expect(view.container.querySelectorAll(".workflow-flow-particle")).toHaveLength(3)
    expect(screen.getByRole("img", { name: "Success rate: 96%" })).toHaveTextContent("96%")
    expect(screen.queryByText(/success rate|success/i)).not.toBeInTheDocument()
  })

  it("stops active flow before an attention-blocking stage", async () => {
    const blockedStages = [
      stage("trigger", "manual", "Manual", "trigger"),
      stage("collect", "select_content", "Select content", "content"),
      stage("review", "human_review", "Human Review", "review", [], true),
      stage("publish", "telegram_publish", "Publish to Telegram", "publish", ["telegram"]),
    ]
    vi.mocked(api.getAutomations).mockResolvedValue({
      items: [automation({ lifecycle: "active", preview: { ...preview("telegram"), valid: false, stages: blockedStages } })],
      nextCursor: null,
    } as never)
    const view = renderPage(<WorkflowLibrary />)

    await screen.findByRole("img", { name: /Workflow stages:/ })
    expect(screen.queryByText("Needs attention")).not.toBeInTheDocument()
    expect(view.container.querySelectorAll("[data-flow-connector][data-animated='true']")).toHaveLength(1)
    expect(view.container.querySelectorAll("[data-flow-connector][data-animated='false']")).toHaveLength(2)
    expect(view.container.querySelectorAll(".workflow-flow-particle")).toHaveLength(1)
  })

  it("opens cards and creation with native keyboard-capable buttons while menu remains independent", async () => {
    vi.mocked(api.getAutomations).mockResolvedValue({ items: [automation()], nextCursor: null } as never)
    renderPage(<WorkflowLibrary />)

    fireEvent.click(await screen.findByRole("button", { name: "Open workflow: Morning newsroom" }))
    expect(push).toHaveBeenLastCalledWith("/automations/automation-1")
    push.mockClear()

    fireEvent.click(screen.getByRole("button", { name: "More actions for Morning newsroom" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "Test workflow" }))
    expect(push).toHaveBeenCalledWith("/automations/automation-1#test-studio")
    expect(push).not.toHaveBeenCalledWith("/automations/automation-1")

    fireEvent.click(screen.getByRole("button", { name: "Create new workflow" }))
    fireEvent.change(screen.getByRole("textbox", { name: "Workflow name" }), { target: { value: "  Morning & research  " } })
    fireEvent.click(screen.getByRole("button", { name: "Create workflow" }))
    expect(push).toHaveBeenLastCalledWith("/automations/new?name=Morning%20%26%20research")
  })

  it.each([5, 20, 50])("renders %i lightweight previews without per-card requests", async (count) => {
    vi.mocked(api.getAutomations).mockResolvedValue({
      items: Array.from({ length: count }, (_, index) => automation({
        id: `automation-${index + 1}`,
        name: `Workflow ${index + 1}`,
      })),
      nextCursor: null,
    } as never)
    const view = renderPage(<WorkflowLibrary />)

    await screen.findByText(`Workflow ${count}`)
    expect(view.container.querySelectorAll("[data-workflow-card]")).toHaveLength(count)
    expect(api.getAutomation).not.toHaveBeenCalled()
    expect(api.getAutomationRuns).not.toHaveBeenCalled()
    expect(api.getAutomationResourceCatalog).not.toHaveBeenCalled()
  })

  it("creates an inactive editable copy from server template data", async () => {
    vi.mocked(api.getAutomationTemplates).mockResolvedValue([template] as never)
    vi.mocked(api.createAutomationFromTemplate).mockResolvedValue(detail as never)
    renderPage(<AutomationTemplatesPage creationMode />)

    fireEvent.click(await screen.findByRole("button", { name: "Use this template" }))
    await waitFor(() => expect(api.createAutomationFromTemplate).toHaveBeenCalledWith("blank-workflow", {}, expect.stringContaining("template-blank-workflow-")))
    expect(push).toHaveBeenCalledWith("/automations/automation-1")
  })

  it("creates blank workflow and opens its editor directly", async () => {
    vi.mocked(api.createAutomation).mockResolvedValue(detail as never)
    renderPage(<NewWorkflowPage />)

    await waitFor(() => expect(api.createAutomation).toHaveBeenCalledWith(expect.objectContaining({
      name: "New workflow",
      graph: expect.objectContaining({ entryNodeId: "", nodes: [], edges: [], outputNodeIds: [] }),
      creationReason: "blank workflow created",
    }), expect.stringContaining("workflow-create-")))
    expect(push).toHaveBeenCalledWith("/automations/automation-1")
  })

  it("passes trimmed popup name into blank workflow creation", async () => {
    searchParams.set("name", "  Morning newsroom  ")
    vi.mocked(api.createAutomation).mockResolvedValue(detail as never)
    renderPage(<NewWorkflowPage />)

    await waitFor(() => expect(api.createAutomation).toHaveBeenCalledWith(expect.objectContaining({
      name: "Morning newsroom",
      graph: expect.objectContaining({ entryNodeId: "", nodes: [], edges: [], outputNodeIds: [] }),
    }), expect.stringContaining("workflow-create-")))
    expect(push).toHaveBeenCalledWith("/automations/automation-1")
  })
})

function renderPage(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

function automation(overrides: Record<string, unknown> = {}) {
  return {
    id: "automation-1",
    name: "Morning newsroom",
    description: "Daily package",
    lifecycle: "inactive",
    ownerType: "operator_managed",
    revision: 1,
    activeVersionId: null,
    draftVersionId: "version-1",
    archivedAt: null,
    createdAt: "2026-08-01T08:00:00Z",
    updatedAt: "2026-08-01T08:00:00Z",
    preview: preview("draft"),
    ...overrides,
  }
}

function preview(kind: "telegram" | "draft" | "multi" | "unknown"): AutomationPreview {
  const outputPlatforms: AutomationPlatform[] = kind === "multi" ? ["x", "blog"] : [kind]
  const outputType = kind === "telegram" ? "telegram_publish" : kind === "draft" ? "save_drafts" : kind === "multi" ? "manual_package" : "custom_output"
  const outputLabel = kind === "telegram" ? "Publish to Telegram" : kind === "draft" ? "Save to Drafts" : kind === "multi" ? "Manual publishing package" : "Custom output"
  return {
    version: 2,
    versionState: "draft",
    stages: [
      stage("trigger", "manual", "Manual", "trigger"),
      stage("generate", "generate_content_pack", "Generate content package", "ai"),
      stage("output", outputType, outputLabel, kind === "draft" ? "draft" : "publish", outputPlatforms),
    ],
    outputPlatforms,
    valid: true,
    runCount: 0,
    successRate: null,
    lastRunAt: null,
    lastOutcome: null,
  }
}

function stage(
  nodeId: string,
  nodeType: string,
  label: string,
  category: AutomationPreviewStage["category"],
  platforms: AutomationPlatform[] = [],
  needsAttention = false,
): AutomationPreviewStage {
  return { nodeId, nodeType, label, category, platforms, needsAttention }
}

const graph = {
  schemaVersion: 1,
  entryNodeId: "trigger-1",
  nodes: [
    { id: "trigger-1", type: "manual", config: { storyRevisionId: "story-1" } },
    { id: "generate-1", type: "generate_content_pack", config: { providerProfileId: "provider-1" } },
    { id: "draft-1", type: "save_drafts", config: {} },
  ],
  edges: [
    { sourceNodeId: "trigger-1", sourcePort: "story", targetNodeId: "generate-1", targetPort: "story" },
    { sourceNodeId: "generate-1", sourcePort: "drafts", targetNodeId: "draft-1", targetPort: "drafts" },
  ],
  outputNodeIds: ["draft-1"],
  metadata: { layout: {} },
} as const

const templateAutomation = automation()
const version = { id: "version-1", automationId: "automation-1", version: 1, schemaVersion: 1, graph, graphHash: "hash", compilerVersion: "1", compiledPlan: {}, validationSummary: { valid: true, graphHash: "hash", findings: [] }, creationActorType: "human", creationActorId: "owner", creationReason: "created", createdAt: "2026-08-01T08:00:00Z" }
const detail = { ...templateAutomation, draftVersion: version, activeVersion: null, legacyRouteId: null }
const template = { id: "template-1", seedKey: "blank-workflow", seedVersion: 1, ownership: "system_managed", name: "Blank workflow", description: "Start safely", complexity: "starter", graphSeed: graph, capabilityRequirements: ["manual", "drafts"], createdAt: "2026-08-01T08:00:00Z", updatedAt: "2026-08-01T08:00:00Z" }
