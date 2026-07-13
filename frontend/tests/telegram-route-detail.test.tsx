import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import {
  backfillTelegramRoute,
  dryRunTelegramRoute,
  getTelegramAutomationOptions,
  getTelegramDispatches,
  getTelegramRoute,
  pauseTelegramRoute,
  resumeTelegramRoute,
} from "@/features/automations/telegram-api"
import { RouteDetail } from "@/features/automations/route-detail"

vi.mock("@/features/automations/telegram-api", () => ({
  backfillTelegramRoute: vi.fn(),
  dryRunTelegramRoute: vi.fn(),
  getTelegramAutomationOptions: vi.fn(),
  getTelegramDispatches: vi.fn(),
  getTelegramRoute: vi.fn(),
  pauseTelegramRoute: vi.fn(),
  resumeTelegramRoute: vi.fn(),
}))

const route = {
  id: "route-1",
  name: "Persian wire",
  sourceId: "source-1",
  destinationId: "destination-1",
  brandProfileId: "brand-1",
  promptTemplateVersionId: "prompt-1",
  aiProviderProfileId: "provider-1",
  accessMode: "public_html",
  researchMode: "off",
  contentFilters: { includeTerms: ["ایران"], excludeTerms: [] },
  mediaPolicy: "preserve",
  attributionPolicy: "preserve",
  customFooter: null,
  publishingPolicy: "review_required",
  pollIntervalSeconds: 300,
  quietHours: {},
  retryPolicy: { maxAttempts: 3, baseDelaySeconds: 30, maxDelaySeconds: 1800 },
  cursorState: { status: "ready", activationMessageId: 90, lastMessageId: 91 },
  enabled: true,
  pausedAt: null,
  lastPolledAt: "2026-07-12T08:00:00Z",
  nextPollAt: "2026-07-12T08:05:00Z",
  createdAt: "2026-07-12T07:00:00Z",
  updatedAt: "2026-07-12T08:00:00Z",
}

describe("RouteDetail", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getTelegramRoute).mockResolvedValue(route as never)
    vi.mocked(getTelegramAutomationOptions).mockResolvedValue({
      sources: [{ id: "source-1", name: "Wire", accessMode: "public_html" }],
      destinations: [{ id: "destination-1", name: "News", healthStatus: "healthy", allowAutoPublish: false }],
      brandProfiles: [], promptTemplateVersions: [], aiProviderProfiles: [],
    })
    vi.mocked(getTelegramDispatches).mockResolvedValue([
      { id: "dispatch-1", sourceMessageIds: [91], status: "review_required", errorMessage: "Global pause", variantRevisionId: "revision-9", publishJobId: "job-9", createdAt: "2026-07-12T08:02:00Z" },
    ] as never)
    vi.mocked(pauseTelegramRoute).mockResolvedValue({ ...route, pausedAt: "2026-07-12T08:03:00Z" } as never)
    vi.mocked(resumeTelegramRoute).mockResolvedValue(route as never)
    vi.mocked(dryRunTelegramRoute).mockResolvedValue({ route, job: { jobId: "job-dry", status: "queued", deduplicated: false } } as never)
    vi.mocked(backfillTelegramRoute).mockResolvedValue({ route, job: { jobId: "job-backfill", status: "queued", deduplicated: false } } as never)
  })

  it("shows truthful cursor, schedule, policy, health, and dispatch failure/job history", async () => {
    renderDetail()
    expect(await screen.findByRole("heading", { name: "Persian wire" })).toBeInTheDocument()
    expect(screen.getByText("Ready")).toBeInTheDocument()
    expect(screen.getByText("Last message 91")).toBeInTheDocument()
    expect(screen.getByText("Next poll")).toBeInTheDocument()
    expect(screen.getAllByText(/Review required/i)).not.toHaveLength(0)
    expect(screen.getByText("Public HTML")).toBeInTheDocument()
    expect(screen.getByText("Healthy")).toBeInTheDocument()
    expect(await screen.findByText("Global pause")).toHaveAttribute("dir", "auto")
    expect(screen.getByRole("link", { name: "Review revision revision-9" })).toHaveAttribute("href", "/review/revision-9")
    expect(screen.getByRole("link", { name: "Open durable route history" })).toHaveAttribute(
      "href",
      "/automations/route-1/history",
    )
  })

  it("pauses and resumes using server truth", async () => {
    renderDetail()
    fireEvent.click(await screen.findByRole("button", { name: "Pause route" }))
    await waitFor(() => expect(pauseTelegramRoute).toHaveBeenCalledWith("route-1"))
    expect(await screen.findByRole("button", { name: "Resume route" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Resume route" }))
    await waitFor(() => expect(resumeTelegramRoute).toHaveBeenCalledWith("route-1"))
  })

  it("queues a force-review dry run and reports its durable job", async () => {
    renderDetail()
    await screen.findByRole("heading", { name: "Persian wire" })
    fireEvent.change(screen.getByLabelText("Source message ID (optional)"), { target: { value: "91" } })
    fireEvent.click(screen.getByRole("button", { name: "Run dry run" }))
    await waitFor(() => expect(dryRunTelegramRoute).toHaveBeenCalledWith("route-1", { sourceMessageId: 91 }))
    expect(await screen.findByRole("status", { name: "Latest route action" })).toHaveTextContent("job-dry")
  })

  it("allows exactly one bounded backfill mode and sends an offset ISO timestamp", async () => {
    renderDetail()
    await screen.findByRole("heading", { name: "Persian wire" })
    expect(screen.getByLabelText("Message count")).toBeEnabled()
    expect(screen.getByLabelText("Since date and time")).toBeDisabled()
    fireEvent.click(screen.getByLabelText("Since date"))
    expect(screen.getByLabelText("Message count")).toBeDisabled()
    expect(screen.getByLabelText("Since date and time")).toBeEnabled()
    fireEvent.change(screen.getByLabelText("Since date and time"), { target: { value: "2026-07-11T12:30" } })
    fireEvent.click(screen.getByRole("button", { name: "Queue backfill" }))
    await waitFor(() => expect(backfillTelegramRoute).toHaveBeenCalled())
    const body = vi.mocked(backfillTelegramRoute).mock.calls[0][1] as { since: string }
    expect(body).toEqual({ since: expect.stringMatching(/^2026-07-11T\d{2}:\d{2}:00\.000(?:Z|[+-]\d{2}:\d{2})$/) })
  })

  it("retains action input and renders API errors accessibly", async () => {
    vi.mocked(backfillTelegramRoute).mockRejectedValue(new Error("Backfill is outside the allowed window"))
    renderDetail()
    await screen.findByRole("heading", { name: "Persian wire" })
    fireEvent.change(screen.getByLabelText("Message count"), { target: { value: "20" } })
    fireEvent.click(screen.getByRole("button", { name: "Queue backfill" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Backfill is outside the allowed window")
    expect(screen.getByLabelText("Message count")).toHaveValue(20)
  })

  it("blocks malformed dry-run and out-of-range backfill bounds before API calls", async () => {
    renderDetail()
    await screen.findByRole("heading", { name: "Persian wire" })

    fireEvent.change(screen.getByLabelText("Source message ID (optional)"), { target: { value: "1.5" } })
    expect(screen.getByRole("button", { name: "Run dry run" })).toBeDisabled()
    expect(screen.getByText("Source message ID must be a positive integer.")).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("Message count"), { target: { value: "101" } })
    expect(screen.getByRole("button", { name: "Queue backfill" })).toBeDisabled()
    expect(screen.getByText(/integer from 1 to 100/i)).toBeInTheDocument()
    expect(dryRunTelegramRoute).not.toHaveBeenCalled()
    expect(backfillTelegramRoute).not.toHaveBeenCalled()
  })

  it("shows destination request failure separately from real health truth", async () => {
    vi.mocked(getTelegramAutomationOptions).mockRejectedValue(new Error("health endpoint offline"))
    renderDetail()

    expect(await screen.findByRole("alert")).toHaveTextContent("Destination health request failed")
    expect(screen.getByRole("button", { name: "Retry destination health" })).toBeInTheDocument()
    expect(screen.queryByText("Unavailable", { exact: true })).not.toBeInTheDocument()
  })

  it("replaces an older success with the latest failed action", async () => {
    vi.mocked(backfillTelegramRoute).mockRejectedValue(new Error("latest backfill failed"))
    renderDetail()
    await screen.findByRole("heading", { name: "Persian wire" })
    fireEvent.click(screen.getByRole("button", { name: "Run dry run" }))
    expect(await screen.findByRole("status", { name: "Latest route action" })).toHaveTextContent("Dry run queued")

    fireEvent.click(screen.getByRole("button", { name: "Queue backfill" }))
    expect(await screen.findByRole("alert", { name: "Latest route action" })).toHaveTextContent("latest backfill failed")
    expect(screen.queryByText(/Dry run queued/)).not.toBeInTheDocument()
  })
})

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><RouteDetail routeId="route-1" /></QueryClientProvider>)
}
