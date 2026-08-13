import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"

import { SourcesPage } from "@/components/dashboard/pages/sources-page"
import { NoticeProvider } from "@/components/providers/notice-provider"
import { getSources } from "@/features/operations/ingestion-api"
import { queryKeys } from "@/lib/query-keys"

vi.mock("@/features/operations/ingestion-api", async () => {
  const actual = await vi.importActual<
    typeof import("@/features/operations/ingestion-api")
  >("@/features/operations/ingestion-api")
  return {
    ...actual,
    getSources: vi.fn(async () => []),
  }
})

describe("live data queries", () => {
  beforeEach(() => vi.clearAllMocks())

  it("fetches sources immediately when the route starts empty", async () => {
    renderWithClient(<SourcesPage initialSources={[]} />)

    await waitFor(() => expect(getSources).toHaveBeenCalledTimes(1))
  })

  it("keeps Sources mounted when its placeholder-backed list query rejects", async () => {
    vi.mocked(getSources).mockRejectedValueOnce(new Error("offline"))
    const { queryClient } = renderWithClient(<SourcesPage initialSources={[]} />)

    await waitFor(() =>
      expect(queryClient.getQueryCache().find({ queryKey: queryKeys.sources, exact: false })?.state.status).toBe("error")
    )

    expect(screen.getByRole("heading", { name: "Sources" })).toBeInTheDocument()
  })
})

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 10_000 } },
  })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <NoticeProvider>{ui}</NoticeProvider>
      </QueryClientProvider>
    ),
  }
}
