import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"

import { DashboardShell } from "@/components/dashboard/dashboard-shell"
import { ContentItemsPage } from "@/components/dashboard/pages/content-items-page"
import { DiagnosticsPage } from "@/components/dashboard/pages/diagnostics-page"
import { MediaAssetsPage } from "@/components/dashboard/pages/media-assets-page"
import { RunsPage } from "@/components/dashboard/pages/runs-page"
import { SourcesPage } from "@/components/dashboard/pages/sources-page"
import { emptyDashboardSnapshot } from "@/lib/empty-data"
import {
  getContentItems,
  getDashboardSnapshot,
  getDashboardSummary,
  getDiagnostics,
  getIngestRuns,
  getMediaAssets,
  getSources,
} from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client")
  return {
    ...actual,
    getDashboardSnapshot: vi.fn(async () => emptyDashboardSnapshot),
    getDashboardSummary: vi.fn(async () => emptyDashboardSnapshot.counts),
    getContentItems: vi.fn(async () => []),
    getDiagnostics: vi.fn(async () => ({ status: "ok", checks: {}, sourceHealth: {}, problemSources: [] })),
    getIngestRuns: vi.fn(async () => []),
    getMediaAssets: vi.fn(async () => []),
    getSources: vi.fn(async () => []),
  }
})

describe("live data queries", () => {
  beforeEach(() => vi.clearAllMocks())

  it("fetches the dashboard immediately when empty data is only a placeholder", async () => {
    renderWithClient(<DashboardShell initialData={emptyDashboardSnapshot} />)

    await waitFor(() => expect(getDashboardSnapshot).toHaveBeenCalledTimes(1))
  })

  it("fetches content immediately when the route starts with an empty placeholder", async () => {
    renderWithClient(<ContentItemsPage initialItems={[]} />)

    await waitFor(() => expect(getContentItems).toHaveBeenCalledTimes(1))
    expect(getDashboardSummary).toHaveBeenCalledTimes(1)
  })

  it.each([
    ["sources", <SourcesPage initialSources={[]} />, getSources],
    ["runs", <RunsPage initialRuns={[]} />, getIngestRuns],
    ["media", <MediaAssetsPage initialMedia={[]} />, getMediaAssets],
    ["diagnostics", <DiagnosticsPage />, getDiagnostics],
  ])("fetches %s immediately when the route starts empty", async (_name, page, request) => {
    renderWithClient(page)

    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
  })

  it("keeps the dashboard mounted when its placeholder-backed query rejects", async () => {
    vi.mocked(getDashboardSnapshot).mockRejectedValueOnce(new Error("offline"))
    const { queryClient } = renderWithClient(<DashboardShell initialData={emptyDashboardSnapshot} />)

    await waitFor(() => expect(queryClient.getQueryState(queryKeys.dashboardSnapshot)?.status).toBe("error"))

    expect(screen.getByRole("alert")).toHaveTextContent("Backend data unavailable")
    expect(screen.getByText("No sources found")).toBeInTheDocument()
  })

  it("keeps the operations frame mounted when its counts placeholder query rejects", async () => {
    vi.mocked(getDashboardSummary).mockRejectedValueOnce(new Error("offline"))
    const { queryClient } = renderWithClient(<RunsPage initialRuns={[]} />)

    await waitFor(() => expect(queryClient.getQueryState(queryKeys.dashboardSummary)?.status).toBe("error"))

    expect(screen.getByRole("heading", { name: "Ingestion Runs" })).toBeInTheDocument()
  })

  it.each([
    ["sources", <SourcesPage initialSources={[]} />, getSources, queryKeys.sources, "Sources"],
    ["runs", <RunsPage initialRuns={[]} />, getIngestRuns, queryKeys.runs, "Ingestion Runs"],
    ["content", <ContentItemsPage initialItems={[]} />, getContentItems, queryKeys.contentItems, "Content Items"],
    ["media", <MediaAssetsPage initialMedia={[]} />, getMediaAssets, queryKeys.media, "Media Assets"],
  ])(
    "keeps the %s page mounted when its placeholder-backed list query rejects",
    async (_name, page, request, queryKey, heading) => {
      vi.mocked(request).mockRejectedValueOnce(new Error("offline"))
      const { queryClient } = renderWithClient(page)

      await waitFor(() =>
        expect(queryClient.getQueryCache().find({ queryKey, exact: false })?.state.status).toBe("error")
      )

      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument()
    }
  )
})

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 10_000 } },
  })
  return {
    queryClient,
    ...render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>),
  }
}
