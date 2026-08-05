import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { useState } from "react"

import AutomationTestStudio from "@/features/automations/automation-test-studio"
import * as api from "@/features/automations/automation-api"
import * as articles from "@/features/articles/api"
import type { GraphValidation } from "@/features/automations/automation-types"

let search = new URLSearchParams()
const replace = vi.fn()

vi.mock("next/navigation", () => ({
  usePathname: () => "/automations/automation-1",
  useRouter: () => ({ replace }),
  useSearchParams: () => search,
}))

vi.mock("@/features/articles/api", () => ({ getArticles: vi.fn() }))
vi.mock("@/features/automations/automation-api", () => ({
  getAutomationRun: vi.fn(),
  startAutomationRun: vi.fn(),
  validateAutomationVersion: vi.fn(),
}))

describe("Phase 5 Automation Test Studio", () => {
  beforeEach(() => {
    search = new URLSearchParams()
    replace.mockReset()
    vi.clearAllMocks()
    vi.mocked(articles.getArticles).mockResolvedValue({ items: [{ coverage: { stories: [{ id: "story-1", title: "Verified newsroom story" }] } }], nextCursor: null, resultCount: 1 } as never)
    vi.mocked(api.validateAutomationVersion).mockResolvedValue({ valid: true, graphHash: "validated", findings: [] })
    vi.mocked(api.startAutomationRun).mockResolvedValue(runFixture() as never)
  })

  it("validates exact version, selects safe Feed input, and starts durable dry run", async () => {
    renderStudio()
    expect(await screen.findByRole("option", { name: "Verified newsroom story" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Start full dry run" })).toBeDisabled()
    expect(screen.queryByRole("button", { name: /run until|retry node|compare outputs/i })).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("Feed story"), { target: { value: "story-1" } })
    fireEvent.click(screen.getByRole("button", { name: "Validate only" }))
    expect(await screen.findByText("Persisted version 3 is ready for dry run.")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Start full dry run" }))

    await waitFor(() => expect(api.startAutomationRun).toHaveBeenCalledWith(
      "automation-1",
      { versionNumber: 3, dryRun: true, storyId: "story-1" },
      expect.stringContaining("workflow-dry-run-"),
    ))
    expect(replace).toHaveBeenCalledWith(expect.stringContaining("runId=run-1"), { scroll: false })
  })

  it("resumes persisted run from URL and hides client-side secret-shaped summary fields", async () => {
    search = new URLSearchParams("runId=run-1")
    vi.mocked(api.getAutomationRun).mockResolvedValue(runFixture() as never)
    renderStudio(true)

    expect(await screen.findByRole("heading", { name: "Run run-1" })).toBeInTheDocument()
    expect(screen.getByText("Safe output")).toBeInTheDocument()
    expect(screen.queryByText("credential-canary")).not.toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Open exact revision" })).toHaveAttribute("href", "/review/revision-1")
    expect(screen.getByRole("link", { name: "Related Job" })).toHaveAttribute("href", "/operations?view=jobs&job=job-1")
  })
})

function renderStudio(initiallyValidated = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  function Harness() {
    const [validation, setValidation] = useState<GraphValidation | null>(initiallyValidated ? { valid: true, graphHash: "validated", findings: [] } : null)
    return <AutomationTestStudio automationId="automation-1" versionNumber={3} graph={graph as never} dirty={false} validated={validation?.valid === true} onValidation={setValidation} onRunStarted={vi.fn()} />
  }
  return render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>)
}

const graph = {
  schemaVersion: 1,
  entryNodeId: "manual-1",
  nodes: [{ id: "manual-1", type: "manual", config: { storyRevisionId: "saved-revision" } }],
  edges: [],
  outputNodeIds: ["manual-1"],
  metadata: { layout: {} },
}

function runFixture() {
  return {
    id: "run-1",
    automationId: "automation-1",
    automationVersionId: "version-3",
    rootWorkflowJobId: "job-1",
    triggerKind: "manual",
    triggerMetadata: { storyId: "story-1" },
    dryRun: true,
    status: "succeeded",
    currentNodeId: null,
    resourceSnapshot: { automationVersion: 3 },
    safeErrorCode: null,
    safeErrorMessage: null,
    startedAt: "2026-08-01T08:00:00Z",
    finishedAt: "2026-08-01T08:00:02Z",
    createdAt: "2026-08-01T08:00:00Z",
    nodes: [{
      id: "node-run-1",
      automationRunId: "run-1",
      nodeId: "generate-1",
      attempt: 1,
      status: "succeeded",
      workflowJobId: "job-1",
      automationDispatchId: null,
      researchRunId: null,
      generationRunId: "generation-1",
      platformVariantRevisionId: "revision-1",
      publishJobId: null,
      publicationId: null,
      inputSummary: {},
      outputSummary: { summary: "Safe output", apiKey: "credential-canary" },
      usage: { totalTokens: 25 },
      retryMetadata: {},
      safeErrorCode: null,
      safeErrorMessage: null,
      startedAt: "2026-08-01T08:00:00Z",
      finishedAt: "2026-08-01T08:00:02Z",
      createdAt: "2026-08-01T08:00:00Z",
    }],
  }
}
