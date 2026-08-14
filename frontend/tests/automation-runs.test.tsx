import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type React from "react"

import { AutomationRunsPage } from "@/features/automations/automation-runs-page"
import AutomationVersionHistory from "@/features/automations/automation-version-history"
import * as api from "@/features/automations/automation-api"

let search = new URLSearchParams("automationId=automation-1")
const replace = vi.fn()

vi.mock("next/navigation", () => ({
  usePathname: () => "/automations/runs",
  useRouter: () => ({ replace }),
  useSearchParams: () => search,
}))

vi.mock("@/features/automations/automation-api", () => ({
  approveAutomationArtifactReview: vi.fn(),
  getAutomationRun: vi.fn(),
  getAutomationRuns: vi.fn(),
  getAutomations: vi.fn(),
  getAutomationVersions: vi.fn(),
  restoreAutomationVersion: vi.fn(),
}))

describe("Phase 5 Automation Runs", () => {
  beforeEach(() => {
    search = new URLSearchParams("automationId=automation-1")
    replace.mockReset()
    vi.clearAllMocks()
    vi.mocked(api.getAutomations).mockResolvedValue({ items: [{ id: "automation-1", name: "Morning newsroom" }], nextCursor: null } as never)
    vi.mocked(api.getAutomationRuns).mockResolvedValue({ items: [runFixture()], nextCursor: null } as never)
    vi.mocked(api.getAutomationRun).mockResolvedValue(runFixture() as never)
    vi.mocked(api.approveAutomationArtifactReview).mockResolvedValue({ ...runFixture(), status: "running" } as never)
  })

  it("renders bounded filters, persisted columns, exact links, and deep-linked run detail", async () => {
    renderWithClient(<AutomationRunsPage />)
    const table = await screen.findByRole("table", { name: "Automation runs" })
    expect(within(table).getByText("Version 3")).toBeInTheDocument()
    expect(within(table).getByText("Generate 1")).toBeInTheDocument()
    expect(within(table).getByRole("link", { name: "Revision" })).toHaveAttribute("href", "/review/revision-1")
    expect(within(table).getByRole("link", { name: "Job" })).toHaveAttribute("href", "/operations?view=jobs&job=job-1")

    fireEvent.change(screen.getByLabelText("State"), { target: { value: "failed" } })
    expect(replace).toHaveBeenCalledWith(expect.stringContaining("status=failed"), { scroll: false })

    fireEvent.click(within(table).getByRole("button", { name: "Inspect" }))
    expect(replace).toHaveBeenCalledWith(expect.stringContaining("runId=run-1"), { scroll: false })
  })

  it("opens run detail from URL, shows node truth once, and restores close focus", async () => {
    search = new URLSearchParams("automationId=automation-1&runId=run-1")
    renderWithClient(<AutomationRunsPage />)
    const dialog = await screen.findByRole("dialog", { name: "Run detail" })
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Close run detail" })).toHaveFocus())
    expect(await within(dialog).findByRole("article", { name: "Step 1: Generate 1" })).toBeInTheDocument()
    expect(within(dialog).getByText("Safe output")).toBeInTheDocument()
    expect(within(dialog).queryByText("credential-canary")).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole("button", { name: "Close run detail" }))
    expect(replace).toHaveBeenCalledWith(expect.not.stringContaining("runId"), { scroll: false })
  })

  it("approves runs waiting at the artifact review boundary", async () => {
    search = new URLSearchParams("automationId=automation-1&runId=run-1")
    vi.mocked(api.getAutomationRun).mockResolvedValue({ ...runFixture(), status: "waiting_for_review" } as never)
    renderWithClient(<AutomationRunsPage />)

    const dialog = await screen.findByRole("dialog", { name: "Run detail" })
    fireEvent.click(await within(dialog).findByRole("button", { name: "Approve artifact review" }))

    await waitFor(() => expect(api.approveAutomationArtifactReview).toHaveBeenCalledWith("run-1"))
    expect(await within(dialog).findByText("Artifact review approved.")).toBeInTheDocument()
  })
})

describe("Phase 5 immutable version history", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getAutomationVersions).mockResolvedValue({ items: [versionFixture(3), versionFixture(1)], nextCursor: null } as never)
    vi.mocked(api.getAutomationRuns).mockResolvedValue({ items: [runFixture()], nextCursor: null } as never)
    vi.mocked(api.restoreAutomationVersion).mockResolvedValue(versionFixture(4) as never)
  })

  it("shows active/run-pinned versions, safe structural diff, and restores into new draft", async () => {
    const onRestored = vi.fn()
    renderWithClient(<AutomationVersionHistory open onOpenChange={vi.fn()} automationId="automation-1" activeVersionId="version-3" draftVersionId="version-3" currentVersion={versionFixture(3) as never} expectedRevision={7} onRestored={onRestored} />)

    const dialog = await screen.findByRole("dialog", { name: "Immutable version history" })
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Close version history" })).toHaveFocus())
    expect(await within(dialog).findByText("Active")).toBeInTheDocument()
    expect(within(dialog).getByText("Run pinned")).toBeInTheDocument()
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Compare structure" })[1])
    expect(within(dialog).getByText("Configs changed")).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole("button", { name: "Restore as new draft" }))
    await waitFor(() => expect(api.restoreAutomationVersion).toHaveBeenCalledWith("automation-1", 1, 7, expect.stringContaining("workflow-restore-1-")))
    expect(onRestored).toHaveBeenCalledWith(expect.objectContaining({ version: 4 }))
    expect(await within(dialog).findByText(/History stayed immutable/)).toBeInTheDocument()
  })
})

function renderWithClient(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

function runFixture() {
  return {
    id: "run-1", automationId: "automation-1", automationVersionId: "version-3", rootWorkflowJobId: "job-1",
    triggerKind: "manual", triggerMetadata: {}, dryRun: true, status: "succeeded", currentNodeId: "generate-1",
    resourceSnapshot: { automationVersion: 3 }, safeErrorCode: null, safeErrorMessage: null,
    startedAt: "2026-08-01T08:00:00Z", finishedAt: "2026-08-01T08:00:02Z", createdAt: "2026-08-01T08:00:00Z",
    nodes: [{ id: "node-run-1", automationRunId: "run-1", nodeId: "generate-1", attempt: 1, status: "succeeded", workflowJobId: "job-1", automationDispatchId: null, researchRunId: null, generationRunId: "generation-1", platformVariantRevisionId: "revision-1", publishJobId: null, publicationId: null, inputSummary: {}, outputSummary: { summary: "Safe output", apiKey: "credential-canary" }, usage: {}, retryMetadata: {}, safeErrorCode: null, safeErrorMessage: null, startedAt: "2026-08-01T08:00:00Z", finishedAt: "2026-08-01T08:00:02Z", createdAt: "2026-08-01T08:00:00Z" }],
  }
}

function versionFixture(version: number) {
  const changed = version === 3
  return {
    id: `version-${version}`, automationId: "automation-1", version, schemaVersion: 1,
    graph: { schemaVersion: 1, entryNodeId: "manual-1", nodes: [{ id: "manual-1", type: "manual", config: changed ? { storyRevisionId: "new" } : {} }], edges: [], outputNodeIds: ["manual-1"], metadata: { layout: {} } },
    graphHash: `hash-${version}`, compilerVersion: "1", compiledPlan: {}, validationSummary: {}, creationActorType: "human", creationActorId: "owner", creationReason: `version ${version}`, createdAt: `2026-08-0${Math.min(version, 9)}T08:00:00Z`,
  }
}
