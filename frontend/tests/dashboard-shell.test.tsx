import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"

import { DashboardShell } from "@/components/dashboard/dashboard-shell"
import { QueryProvider } from "@/components/providers/query-provider"
import { getDashboardSnapshot, runIngest } from "@/lib/api-client"
import { dashboardMock } from "@/lib/mock-data"
import type { DashboardSnapshot } from "@/lib/types"

vi.mock("@/lib/api-client", () => ({
  getDashboardSnapshot: vi.fn(),
  runIngest: vi.fn(),
}))

const emptyDashboard: DashboardSnapshot = {
  counts: {
    rssFeeds: 0,
    telegramChannels: 0,
    contentItems: 0,
    mediaAssets: 0,
    warnings: 0,
  },
  sources: [],
  runs: [],
  queue: [],
  media: [],
}

describe("DashboardShell", () => {
  beforeEach(() => {
    vi.mocked(getDashboardSnapshot).mockResolvedValue(dashboardMock)
    vi.mocked(runIngest).mockResolvedValue({})
  })

  it("renders the operational dashboard frame", () => {
    render(
      <QueryProvider>
        <DashboardShell initialData={dashboardMock} />
      </QueryProvider>
    )

    expect(screen.getByRole("navigation", { name: /dashboard navigation/i })).toBeInTheDocument()
    expect(screen.getByText("PostgreSQL")).toBeInTheDocument()
    expect(screen.getByText("Proxy")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /run ingest/i })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: /source details/i })).toBeInTheDocument()
  })

  it("renders empty dashboard states without mock source data", () => {
    render(
      <QueryProvider>
        <DashboardShell initialData={emptyDashboard} />
      </QueryProvider>
    )

    expect(screen.getByText("No sources found")).toBeInTheDocument()
    expect(screen.getByText("No ingestion runs yet")).toBeInTheDocument()
    expect(screen.getByText("No content items yet")).toBeInTheDocument()
    expect(screen.getByText("No media assets yet")).toBeInTheDocument()
    expect(screen.queryByText("TechCrunch")).not.toBeInTheDocument()
  })

  it("renders an error state when the backend dashboard request fails", async () => {
    vi.mocked(getDashboardSnapshot).mockRejectedValue(new Error("offline"))

    renderWithQueryClient(<DashboardShell initialData={emptyDashboard} enableQueries />)

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend data unavailable")
  })

  it("renders a loading state while the empty dashboard fetch is pending", () => {
    vi.mocked(getDashboardSnapshot).mockImplementation(() => new Promise(() => undefined))

    renderWithQueryClient(<DashboardShell initialData={emptyDashboard} enableQueries />)

    expect(screen.getByRole("status")).toHaveTextContent("Loading dashboard data")
  })
})

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}
