import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NoticeProvider } from "@/components/providers/notice-provider"
import { getAutomationControl } from "@/features/control/api"
import { getJobs, getJobSummary } from "@/features/jobs/api"
import type { JobFilters, WorkflowJob } from "@/features/jobs/types"
import { TodayPage } from "@/features/today/today-page"

vi.mock("@/features/control/api", () => ({
  getAutomationControl: vi.fn(),
  updateAutomationControl: vi.fn(),
}))
vi.mock("@/features/jobs/api", () => ({
  getJobs: vi.fn(),
  getJobSummary: vi.fn(),
}))

const summary = { queued: 3, running: 1, attention: 2, succeeded_today: 4 }
const runningJob = job({ status: "running", progress: 42, progress_message: "در حال پردازش منابع" })
const failedJob = job({ id: "22222222-2222-4222-8222-222222222222", status: "failed", error_message: "خطای شبکه" })
const successJob = job({ id: "33333333-3333-4333-8333-333333333333", status: "succeeded", progress: 100 })
const reviewJob = job({ id: "44444444-4444-4444-8444-444444444444", status: "needs_review" })

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
    expect(alert).toHaveAttribute("data-slot", "error-state")
    expect(alert).toHaveAttribute("dir", "auto")
    fireEvent.click(screen.getByRole("button", { name: "Retry Today" }))
    await waitFor(() => expect(getJobSummary).toHaveBeenCalledTimes(2))
  })

  it("renders the exact all-zero empty state", async () => {
    vi.mocked(getJobSummary).mockResolvedValue({ queued: 0, running: 0, attention: 0, succeeded_today: 0 })
    vi.mocked(getJobs).mockResolvedValue([])
    renderToday()

    expect(await screen.findByText("No workflow jobs yet")).toBeInTheDocument()
    const priority = screen.getByRole("region", { name: "Highest-priority decision" })
    expect(within(priority).getByText("Queue is clear")).toBeInTheDocument()
    expect(within(priority).queryByRole("link")).not.toBeInTheDocument()
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
    const priority = screen.getByRole("region", { name: "Highest-priority decision" })
    expect(within(priority).getByText("Resolve failed workflow")).toBeInTheDocument()
    expect(within(priority).getByRole("link", { name: /Inspect and retry/ })).toHaveAttribute(
      "href",
      `/jobs?status=attention&job=${failedJob.id}`,
    )
    expect(screen.getByRole("link", { name: "Open job" })).toHaveAttribute(
      "href",
      `/jobs?status=attention&job=${failedJob.id}`,
    )
    expect(screen.getByRole("region", { name: "Recent successes" })).toHaveTextContent(successJob.job_type)
  })

  it("routes review decisions through the surviving job detail", async () => {
    vi.mocked(getJobs).mockImplementation(async (filters = {}) => {
      if (filters.statuses?.includes("failed")) return [reviewJob]
      return []
    })
    renderToday()

    const reviewLinks = await screen.findAllByRole("link", { name: "Continue review" })
    expect(reviewLinks).toHaveLength(2)
    for (const link of reviewLinks) {
      expect(link).toHaveAttribute("href", `/jobs?status=attention&job=${reviewJob.id}`)
    }
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
    job_type: "ingest.collect",
    status: "queued",
    origin: "manual",
    priority: 0,
    pause_sensitive: false,
    scheduled_for: "2026-07-12T08:00:00Z",
    attempt_count: 0,
    max_attempts: 3,
    progress: 0,
    progress_message: null,
    error_class: null,
    error_code: null,
    error_message: null,
    started_at: null,
    finished_at: null,
    created_at: "2026-07-12T08:00:00Z",
    updated_at: "2026-07-12T08:00:00Z",
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
