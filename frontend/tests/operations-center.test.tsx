import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NoticeProvider } from "@/components/providers/notice-provider"
import { cancelJob, getJob, getJobs, getJobSummary, retryJob } from "@/features/jobs/api"
import type { WorkflowJob, WorkflowJobDetail } from "@/features/jobs/types"
import { fetchOperationalHealth, fetchOperationsDiagnostics } from "@/features/operations/api"
import { OperationsCenter } from "@/features/operations/operations-center"
import type { OperationalHealthSnapshot, OperationsSnapshot } from "@/features/operations/types"

const navigation = vi.hoisted(() => ({ replace: vi.fn() }))
const searchParams = new URLSearchParams()

vi.mock("next/navigation", () => ({
  usePathname: () => "/operations",
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => searchParams,
}))

vi.mock("@/features/jobs/api", () => ({
  cancelJob: vi.fn(),
  getJob: vi.fn(),
  getJobs: vi.fn(),
  getJobSummary: vi.fn(),
  retryJob: vi.fn(),
}))

vi.mock("@/features/operations/api", () => ({
  fetchOperationalHealth: vi.fn(),
  fetchOperationsDiagnostics: vi.fn(),
}))

const failedJob = job({
  status: "failed",
  error_class: "retryable",
  error_code: "provider_unavailable",
  error_message: "Provider is temporarily unavailable",
})

const queuedJob = job({
  id: "22222222-2222-4222-8222-222222222222",
  status: "queued",
  job_type: "telegram.publish",
})

const jobDetail: WorkflowJobDetail = {
  ...failedJob,
  payload: { authorization: "Bearer secret-value", source_id: "private-source" },
  result: { provider_response: "raw-secret-response" },
  events: [
    {
      id: "33333333-3333-4333-8333-333333333333",
      event_type: "job.failed",
      actor: "internal-worker-name",
      event_data: { traceback: "secret stack trace" },
      created_at: "2026-07-13T07:59:00Z",
    },
  ],
}

const diagnostics: OperationsSnapshot = {
  generated_at: "2026-07-13T08:00:00Z",
  global_paused: false,
  dry_run: false,
  components: {},
  queue_counts: { queued: 1, running: 0, failed: 1, needs_review: 0, succeeded: 0, cancelled: 0 },
  attention: [
    {
      id: failedJob.id,
      severity: "error",
      kind: "job",
      title: "Generation provider is unavailable",
      occurred_at: "2026-07-13T07:59:00Z",
      action_url: `/jobs?status=attention&job=${failedJob.id}`,
    },
  ],
  outbound_proxy: {
    mode: "direct",
    scheme: null,
    bypass_rule_count: 0,
    last_connectivity_status: "not_checked",
    configuration_error_code: null,
  },
}

const health: OperationalHealthSnapshot = {
  generated_at: "2026-07-13T08:00:00Z",
  state: "unavailable",
  state_definitions: {},
  dependencies: {
    database: {
      state: "unavailable",
      code: "database_unavailable",
      observed_at: "2026-07-13T08:00:00Z",
      latency_ms: 1500,
      message: "Database connectivity is unavailable",
      runbook_url: "/docs/operations/readiness-and-health#database-unavailable",
    },
  },
  components: {
    "worker-source-generation": {
      component_id: "worker-source-generation",
      component_type: "worker",
      state: "healthy",
      code: "heartbeat_fresh",
      observed_at: "2026-07-13T07:59:55Z",
      last_success_at: "2026-07-13T07:59:55Z",
      heartbeat_age_seconds: 5,
      last_success_age_seconds: 5,
      capabilities: ["generation"],
      activity: "idle",
      active_work_type: null,
      active_work_age_seconds: null,
      process_started_at: "2026-07-13T07:00:00Z",
      restart_state: "stable",
      restart_count_window: 0,
      restart_window_seconds: 3600,
      last_restart_at: null,
      message: "Worker heartbeat is fresh",
      runbook_url: "/docs/operations/readiness-and-health#worker-unavailable",
    },
  },
  queues: [],
  recoveries: [],
  alerts: [
    {
      code: "database_unavailable",
      state: "unavailable",
      scope: "dependency:database",
      message: "Database connectivity is unavailable",
      runbook_url: "/docs/operations/readiness-and-health#database-unavailable",
    },
  ],
  metrics: {},
  outbound_proxy: diagnostics.outbound_proxy,
}

describe("OperationsCenter", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.stubGlobal("confirm", vi.fn(() => true))
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: vi.fn() } })
    vi.mocked(getJobs).mockResolvedValue([failedJob, queuedJob])
    vi.mocked(getJobSummary).mockResolvedValue({ queued: 1, running: 0, attention: 1, succeeded_today: 4 })
    vi.mocked(getJob).mockResolvedValue(jobDetail)
    vi.mocked(retryJob).mockResolvedValue({ ...failedJob, status: "queued" })
    vi.mocked(cancelJob).mockResolvedValue({ ...queuedJob, status: "cancelled" })
    vi.mocked(fetchOperationsDiagnostics).mockResolvedValue(diagnostics)
    vi.mocked(fetchOperationalHealth).mockResolvedValue(health)
  })

  afterEach(() => vi.unstubAllGlobals())

  it("renders unified health, jobs, checks, and deduplicated actionable issues", async () => {
    renderCenter()

    expect(await screen.findByRole("heading", { name: "Operations Center" })).toBeInTheDocument()
    expect((await screen.findAllByText("Unavailable", { exact: true })).length).toBeGreaterThan(0)
    expect(await screen.findByText("1 of 1")).toBeInTheDocument()
    expect(await screen.findByText("Generation provider is unavailable")).toBeInTheDocument()
    expect(screen.getAllByText("Database connectivity is unavailable")).toHaveLength(2)
    expect(screen.getByText("Recent and active jobs")).toBeInTheDocument()
    expect(screen.getByText("System checks")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Database" })).toBeInTheDocument()
    expect(screen.queryByText("Bearer secret-value")).not.toBeInTheDocument()
  })

  it("preserves job filters in route state and resets them", async () => {
    renderCenter({ view: "jobs" })
    await screen.findByRole("heading", { name: "Jobs" })

    fireEvent.change(screen.getByLabelText("Filter jobs by status"), { target: { value: "attention" } })
    expect(navigation.replace).toHaveBeenLastCalledWith("/operations?view=jobs&status=attention", { scroll: false })

    fireEvent.change(screen.getByPlaceholderText("Search type, ID, or safe error"), { target: { value: "provider" } })
    fireEvent.keyDown(screen.getByPlaceholderText("Search type, ID, or safe error"), { key: "Enter" })
    expect(navigation.replace).toHaveBeenLastCalledWith("/operations?view=jobs&search=provider", { scroll: false })
  })

  it("shows safe job detail only and retries eligible failures after confirmation", async () => {
    renderCenter({ view: "jobs", job: failedJob.id })

    const dialog = await screen.findByRole("dialog", { name: "Job details" })
    await within(dialog).findByText("provider_unavailable")
    expect(dialog).toHaveTextContent("provider_unavailable")
    expect(dialog).toHaveTextContent("Provider is temporarily unavailable")
    expect(dialog).toHaveTextContent("Job Failed")
    expect(dialog).not.toHaveTextContent("Bearer secret-value")
    expect(dialog).not.toHaveTextContent("raw-secret-response")
    expect(dialog).not.toHaveTextContent("secret stack trace")
    expect(dialog).not.toHaveTextContent("internal-worker-name")

    fireEvent.click(within(dialog).getByRole("button", { name: "Retry job" }))
    await waitFor(() => expect(retryJob).toHaveBeenCalledWith(failedJob.id))
  })

  it("runs bounded diagnostics together and announces completion", async () => {
    renderCenter({ view: "diagnostics" })
    await screen.findByRole("heading", { name: "System checks" })
    await screen.findByRole("button", { name: "Run diagnostics" })

    fireEvent.click(screen.getByRole("button", { name: "Run diagnostics" }))
    await waitFor(() => expect(fetchOperationalHealth).toHaveBeenCalledTimes(2))
    expect(fetchOperationsDiagnostics).toHaveBeenCalledTimes(2)
    expect(screen.getByText("System checks completed.")).toBeInTheDocument()
  })
})

function renderCenter(initialQuery: Parameters<typeof OperationsCenter>[0]["initialQuery"] = {}) {
  for (const key of [...searchParams.keys()]) searchParams.delete(key)
  for (const [key, value] of Object.entries(initialQuery)) if (value) searchParams.set(key, value)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <NoticeProvider>
        <OperationsCenter initialQuery={initialQuery} />
      </NoticeProvider>
    </QueryClientProvider>,
  )
}

function job(overrides: Partial<WorkflowJob> = {}): WorkflowJob {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    job_type: "generation.run",
    status: "queued",
    origin: "manual",
    priority: 0,
    pause_sensitive: false,
    scheduled_for: "2026-07-13T07:58:00Z",
    attempt_count: 1,
    max_attempts: 3,
    progress: 30,
    progress_message: "Generating article",
    error_class: null,
    error_code: null,
    error_message: null,
    started_at: "2026-07-13T07:58:30Z",
    finished_at: null,
    created_at: "2026-07-13T07:58:00Z",
    updated_at: "2026-07-13T07:59:00Z",
    ...overrides,
  }
}
