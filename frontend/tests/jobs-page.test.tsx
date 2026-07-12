import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NoticeProvider } from "@/components/providers/notice-provider"
import { cancelJob, getJob, getJobs, getJobSummary, retryJob } from "@/features/jobs/api"
import type { JobFilters, WorkflowJob, WorkflowJobDetail } from "@/features/jobs/types"
import { JobsPage } from "@/features/jobs/jobs-page"

vi.mock("@/features/jobs/api", () => ({
  cancelJob: vi.fn(),
  getJob: vi.fn(),
  getJobs: vi.fn(),
  getJobSummary: vi.fn(),
  retryJob: vi.fn(),
}))

const failed = job({ status: "failed", errorClass: "retryable", errorMessage: "Network timeout" })
const queued = job({ id: "22222222-2222-4222-8222-222222222222", status: "queued" })
const detail: WorkflowJobDetail = {
  ...failed,
  payload: { source_ids: ["source-1"], authorization: "[REDACTED]" },
  result: { fetched: 4 },
  events: [
    {
      id: "33333333-3333-4333-8333-333333333333",
      eventType: "job.failed",
      actor: "worker-1",
      eventData: { error_code: "network_timeout" },
      createdAt: "2026-07-12T08:02:00Z",
    },
  ],
}

describe("JobsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getJobs).mockResolvedValue([failed])
    vi.mocked(getJob).mockResolvedValue(detail)
    vi.mocked(getJobSummary).mockResolvedValue({ queued: 1, running: 0, attention: 1, succeededToday: 0 })
    vi.mocked(retryJob).mockResolvedValue({ ...failed, status: "queued" })
    vi.mocked(cancelJob).mockResolvedValue({ ...queued, status: "cancelled" })
  })

  it("maps every queue filter to the exact API statuses", async () => {
    renderJobs()
    await screen.findByRole("button", { name: /view ingest.collect job/i })

    const cases: Array<[string, JobFilters]> = [
      ["All", { limit: 100 }],
      ["Queued", { statuses: ["queued"], limit: 100 }],
      ["Running", { statuses: ["running"], limit: 100 }],
      ["Attention", { statuses: ["failed", "needs_review"], limit: 100 }],
      ["Succeeded", { statuses: ["succeeded"], limit: 100 }],
      ["Cancelled", { statuses: ["cancelled"], limit: 100 }],
    ]

    for (const [label, filters] of cases) {
      fireEvent.click(screen.getByRole("button", { name: label }))
      await waitFor(() => expect(getJobs).toHaveBeenLastCalledWith(filters))
    }
  })

  it("renders loading, empty, and error states with retry", async () => {
    vi.mocked(getJobs).mockImplementation(() => new Promise(() => undefined))
    const first = renderJobs()
    expect(screen.getByRole("status", { name: "Loading jobs" })).toBeInTheDocument()
    first.unmount()

    vi.mocked(getJobs).mockRejectedValueOnce(new Error("queue offline")).mockResolvedValueOnce([])
    renderJobs()
    expect(await screen.findByRole("alert")).toHaveTextContent("queue offline")
    fireEvent.click(screen.getByRole("button", { name: "Retry jobs" }))
    expect(await screen.findByText("No jobs match this filter")).toBeInTheDocument()
  })

  it("opens sanitized detail, traps focus, closes on Escape, and restores the selected row", async () => {
    renderJobs()
    const rowButton = await screen.findByRole("button", { name: /view ingest.collect job/i })
    ;(detail as WorkflowJobDetail & { lease_owner?: string }).lease_owner = "internal-worker"
    fireEvent.click(rowButton)

    const dialog = await screen.findByRole("dialog", { name: "Job details" })
    const close = within(dialog).getByRole("button", { name: "Close job details" })
    await waitFor(() => expect(close).toHaveFocus())
    expect(dialog).toHaveTextContent("source-1")
    expect(dialog).toHaveTextContent("[REDACTED]")
    expect(dialog).toHaveTextContent("job.failed")
    expect(dialog).not.toHaveTextContent("internal-worker")
    expect(within(dialog).getByRole("button", { name: "Retry job" })).toBeInTheDocument()
    expect(within(dialog).queryByRole("button", { name: "Cancel job" })).not.toBeInTheDocument()

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true })
    expect(within(dialog).getByRole("button", { name: "Retry job" })).toHaveFocus()
    fireEvent.keyDown(document, { key: "Tab" })
    expect(close).toHaveFocus()

    fireEvent.keyDown(document, { key: "Escape" })
    expect(screen.queryByRole("dialog", { name: "Job details" })).not.toBeInTheDocument()
    expect(rowButton).toHaveFocus()
  })

  it("offers cancel only for queued jobs and disables actions while pending", async () => {
    vi.mocked(getJobs).mockResolvedValue([queued])
    vi.mocked(getJob).mockResolvedValue({ ...detail, ...queued, payload: {}, result: {}, events: [] })
    vi.mocked(cancelJob).mockImplementation(() => new Promise(() => undefined))
    renderJobs()

    fireEvent.click(await screen.findByRole("button", { name: /view ingest.collect job/i }))
    const cancel = await screen.findByRole("button", { name: "Cancel job" })
    expect(screen.queryByRole("button", { name: "Retry job" })).not.toBeInTheDocument()
    fireEvent.click(cancel)
    await waitFor(() => expect(cancel).toBeDisabled())
  })

  it("keeps focus inside the aria-modal dialog when a pending action becomes disabled", async () => {
    vi.mocked(getJobs).mockResolvedValue([queued])
    vi.mocked(getJob).mockResolvedValue({ ...detail, ...queued, payload: {}, result: {}, events: [] })
    vi.mocked(cancelJob).mockImplementation(() => new Promise(() => undefined))
    renderJobs()

    fireEvent.click(await screen.findByRole("button", { name: /view ingest.collect job/i }))
    const dialog = await screen.findByRole("dialog", { name: "Job details" })
    expect(dialog).toHaveAttribute("aria-modal", "true")
    const cancel = await within(dialog).findByRole("button", { name: "Cancel job" })
    const close = within(dialog).getByRole("button", { name: "Close job details" })
    cancel.focus()
    fireEvent.click(cancel)
    await waitFor(() => expect(cancel).toBeDisabled())

    cancel.blur()
    expect(document.activeElement).toBe(document.body)
    fireEvent.keyDown(document, { key: "Tab" })
    expect(close).toHaveFocus()
    document.body.tabIndex = -1
    document.body.focus()
    expect(document.activeElement).toBe(document.body)
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true })
    expect(close).toHaveFocus()
    document.body.removeAttribute("tabindex")
  })

  it("retries an attention job and invalidates all job truth", async () => {
    const { queryClient } = renderJobs()
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries")
    fireEvent.click(await screen.findByRole("button", { name: /view ingest.collect job/i }))
    fireEvent.click(await screen.findByRole("button", { name: "Retry job" }))

    await waitFor(() => expect(retryJob).toHaveBeenCalledWith(failed.id))
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["jobs"] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["jobs", failed.id] })
    expect(screen.getByText("Retry requested", { selector: "[data-notice-title]" })).toBeInTheDocument()
  })
})

function job(overrides: Partial<WorkflowJob> = {}): WorkflowJob {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    jobType: "ingest.collect",
    status: "queued",
    origin: "manual",
    priority: 0,
    pauseSensitive: false,
    scheduledFor: "2026-07-12T08:00:00Z",
    attemptCount: 1,
    maxAttempts: 3,
    progress: 0,
    progressMessage: null,
    errorClass: null,
    errorCode: null,
    errorMessage: null,
    startedAt: null,
    finishedAt: null,
    createdAt: "2026-07-12T08:00:00Z",
    updatedAt: "2026-07-12T08:00:00Z",
    ...overrides,
  }
}

function renderJobs() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <NoticeProvider>
          <JobsPage />
        </NoticeProvider>
      </QueryClientProvider>
    ),
  }
}
