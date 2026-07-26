import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"

import { RunsPage } from "@/components/dashboard/pages/runs-page"
import { SourcesPage } from "@/components/dashboard/pages/sources-page"
import {
  getIngestRuns,
  getSources,
} from "@/features/operations/ingestion-api"
import { queryKeys } from "@/lib/query-keys"

vi.mock("@/features/operations/ingestion-api", async () => {
  const actual = await vi.importActual<
    typeof import("@/features/operations/ingestion-api")
  >("@/features/operations/ingestion-api")
  return {
    ...actual,
    getIngestRuns: vi.fn(async () => []),
    getSources: vi.fn(async () => []),
  }
})

describe("live data queries", () => {
  beforeEach(() => vi.clearAllMocks())

  it.each([
    ["sources", <SourcesPage initialSources={[]} />, getSources],
    ["runs", <RunsPage initialRuns={[]} />, getIngestRuns],
  ])("fetches %s immediately when the route starts empty", async (_name, page, request) => {
    renderWithClient(page)

    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
  })

  it.each([
    ["sources", <SourcesPage initialSources={[]} />, getSources, queryKeys.sources, "Sources"],
    ["runs", <RunsPage initialRuns={[]} />, getIngestRuns, queryKeys.runs, "Ingestion Runs"],
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
