import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import * as api from "@/features/automations/automation-api"
import { WorkflowLibrary } from "@/features/automations/workflow-library"

const push = vi.fn()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}))

vi.mock("@/features/automations/automation-api", () => ({
  activateAutomation: vi.fn(),
  archiveAutomation: vi.fn(),
  duplicateAutomation: vi.fn(),
  getAutomations: vi.fn(),
  pauseAutomation: vi.fn(),
  resumeAutomation: vi.fn(),
}))

describe("workflow card actions", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getAutomations).mockResolvedValue({ items: [workflow], nextCursor: null } as never)
    vi.mocked(api.archiveAutomation).mockResolvedValue({ ...workflow, lifecycle: "archived" } as never)
  })

  it("keeps card click navigation and removes Open editor from the menu", async () => {
    renderLibrary()

    const card = await screen.findByText(workflow.name)
    fireEvent.click(screen.getByRole("button", { name: `Open workflow: ${workflow.name}` }))
    expect(push).toHaveBeenCalledWith(`/automations/${workflow.id}`)

    fireEvent.click(within(card.closest("[data-workflow-card]") as HTMLElement).getByRole("button", { name: `More actions for ${workflow.name}` }))
    expect(screen.queryByRole("menuitem", { name: "Open editor" })).not.toBeInTheDocument()
    expect(screen.getByRole("menuitem", { name: "Test workflow" })).toBeInTheDocument()
  })

  it("cancels delete with No and invokes existing archive action once with Yes", async () => {
    renderLibrary()

    const card = await screen.findByText(workflow.name)
    const cardElement = card.closest("[data-workflow-card]") as HTMLElement
    fireEvent.click(within(cardElement).getByRole("button", { name: `More actions for ${workflow.name}` }))
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }))

    let dialog = await screen.findByRole("dialog", { name: "Delete workflow?" })
    expect(dialog).toHaveTextContent(workflow.name)
    fireEvent.click(within(dialog).getByRole("button", { name: "No" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Delete workflow?" })).not.toBeInTheDocument())
    expect(api.archiveAutomation).not.toHaveBeenCalled()

    fireEvent.click(within(cardElement).getByRole("button", { name: `More actions for ${workflow.name}` }))
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }))
    dialog = await screen.findByRole("dialog", { name: "Delete workflow?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Yes, delete workflow" }))

    await waitFor(() => expect(api.archiveAutomation).toHaveBeenCalledTimes(1))
    expect(api.archiveAutomation).toHaveBeenCalledWith(workflow.id, workflow.revision)
  })
})

function renderLibrary() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><WorkflowLibrary /></QueryClientProvider>)
}

const workflow = {
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
  preview: {
    version: 1,
    versionState: "draft",
    stages: [
      { nodeId: "trigger", nodeType: "manual", label: "Manual", category: "trigger", platforms: [], needsAttention: false },
      { nodeId: "output", nodeType: "save_drafts", label: "Save to Drafts", category: "draft", platforms: ["draft"], needsAttention: false },
    ],
    outputPlatforms: ["draft"],
    valid: true,
    runCount: 0,
    successRate: null,
    lastRunAt: null,
    lastOutcome: null,
  },
} as const
