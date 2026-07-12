import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NoticeProvider } from "@/components/providers/notice-provider"
import { getAutomationControl } from "@/features/control/api"
import { cancelJob, getJobs, getJobSummary, retryJob } from "@/features/jobs/api"
import type { JobFilters, WorkflowJob } from "@/features/jobs/types"
import { TodayPage } from "@/features/today/today-page"

vi.mock("@/features/control/api", () => ({
  getAutomationControl: vi.fn(),
  updateAutomationControl: vi.fn(),
}))
vi.mock("@/features/jobs/api", () => ({
  getJobs: vi.fn(),
  getJobSummary: vi.fn(),
  retryJob: vi.fn(),
  cancelJob: vi.fn(),
}))

const summary = { queued: 3, running: 1, attention: 2, succeededToday: 4 }
const runningJob = job({ status: "running", progress: 42, progressMessage: "در حال پردازش منابع" })
const failedJob = job({ id: "22222222-2222-4222-8222-222222222222", status: "failed", errorMessage: "خطای شبکه" })
const successJob = job({ id: "33333333-3333-4333-8333-333333333333", status: "succeeded", progress: 100 })

describe("TodayPage", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getAutomationControl).mockResolvedValue({
      globalPause: false,
      dryRun: false,
      pauseReason: null,
      pausedAt: null,
      updatedAt: "2026-07-12T08:00:00Z",
    })
    vi.mocked(getJobSummary).mockResolvedValue(summary)
    vi.mocked(getJobs).mockImplementation(async (filters = {}) => jobsFor(filters))
    vi.mocked(retryJob).mockResolvedValue({ ...failedJob, status: "queued" })
    vi.mocked(cancelJob).mockResolvedValue({ ...failedJob, status: "cancelled" })
  })

  it("shows the Today heading and loading skeletons", () => {
    vi.mocked(getJobSummary).mockImplementation(() => new Promise(() => undefined))
    vi.mocked(getJobs).mockImplementation(() => new Promise(() => undefined))
    renderToday()

    expect(screen.getByRole("heading", { name: "Today" })).toBeInTheDocument()
    const loading = screen.getByRole("status", { name: "Loading Today" })
    expect(within(loading).getAllByTestId("today-skeleton")).toHaveLength(4)
    expect(screen.queryByText("Loading Today")).not.toBeInTheDocument()
  })

  it("shows an API error with retry and preserves API text direction", async () => {
    vi.mocked(getJobSummary).mockRejectedValueOnce(new Error("سامانه در دسترس نیست"))
    renderToday()

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("سامانه در دسترس نیست")
    expect(alert).toHaveAttribute("dir", "auto")
    fireEvent.click(screen.getByRole("button", { name: "Retry Today" }))
    await waitFor(() => expect(getJobSummary).toHaveBeenCalledTimes(2))
  })

  it("renders the exact all-zero empty state", async () => {
    vi.mocked(getJobSummary).mockResolvedValue({ queued: 0, running: 0, attention: 0, succeededToday: 0 })
    vi.mocked(getJobs).mockResolvedValue([])
    renderToday()

    expect(await screen.findByText("No workflow jobs yet")).toBeInTheDocument()
  })

  it("renders summary-only counts, exact attention statuses, progress API text, and successes", async () => {
    renderToday()

    expect(await screen.findByText("3", { selector: "[data-summary=queued]" })).toBeInTheDocument()
    expect(screen.getByText("1", { selector: "[data-summary=running]" })).toBeInTheDocument()
    expect(screen.getByText("2", { selector: "[data-summary=attention]" })).toBeInTheDocument()
    expect(screen.getByText("4", { selector: "[data-summary=succeeded]" })).toBeInTheDocument()
    expect(getJobs).toHaveBeenCalledWith({ statuses: ["failed", "needs_review"], limit: 25 })
    expect(getJobs).toHaveBeenCalledWith({ statuses: ["running"], limit: 25 })
    expect(getJobs).toHaveBeenCalledWith({ statuses: ["succeeded"], limit: 10 })
    const progressText = screen.getByText("در حال پردازش منابع")
    expect(progressText).toHaveAttribute("dir", "auto")
    expect(screen.getByText("42%", { selector: "[data-progress-label]" })).toHaveAttribute("dir", "auto")
    expect(screen.getByText("خطای شبکه")).toHaveAttribute("dir", "auto")
    expect(screen.getByRole("region", { name: "Recent successes" })).toHaveTextContent(successJob.jobType)
  })

  it.each([
    ["success", false],
    ["error", true],
  ] as const)("re-enables Retry after a settled %s, including a failed-job refetch", async (_name, rejects) => {
    if (rejects) vi.mocked(retryJob).mockRejectedValue(new Error("retry rejected"))
    renderToday()

    const retry = await screen.findByRole("button", { name: "Retry" })
    fireEvent.click(retry)
    await waitFor(() => expect(retryJob).toHaveBeenCalledWith(failedJob.id))
    await waitFor(() => expect(retry).not.toBeDisabled())
    if (!rejects) expect(getJobs).toHaveBeenCalledTimes(6)
  })

  it.each([
    ["success", false],
    ["error", true],
  ] as const)("re-enables Cancel after a settled %s", async (_name, rejects) => {
    const queuedAttention = job({ id: "44444444-4444-4444-8444-444444444444", status: "queued" })
    vi.mocked(getJobs).mockImplementation(async (filters = {}) =>
      filters.statuses?.includes("failed") ? [queuedAttention] : jobsFor(filters)
    )
    if (rejects) vi.mocked(cancelJob).mockRejectedValue(new Error("cancel rejected"))
    renderToday()

    const cancel = await screen.findByRole("button", { name: "Cancel" })
    fireEvent.click(cancel)
    await waitFor(() => expect(cancelJob).toHaveBeenCalledWith(queuedAttention.id))
    await waitFor(() => expect(cancel).not.toBeDisabled())
  })
})

function jobsFor(filters: JobFilters): WorkflowJob[] {
  if (filters.statuses?.includes("running")) return [runningJob]
  if (filters.statuses?.includes("failed")) return [failedJob]
  if (filters.statuses?.includes("succeeded")) return [successJob]
  return []
}

function job(overrides: Partial<WorkflowJob> = {}): WorkflowJob {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    jobType: "ingest.collect",
    status: "queued",
    origin: "manual",
    priority: 0,
    pauseSensitive: false,
    scheduledFor: "2026-07-12T08:00:00Z",
    attemptCount: 0,
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

function renderToday() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <NoticeProvider>
        <TodayPage />
      </NoticeProvider>
    </QueryClientProvider>
  )
}
