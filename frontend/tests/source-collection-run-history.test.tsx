import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { CollectionRunHistory } from "@/components/dashboard/source-collection-run-history"
import {
  getSourceCollectionRuns,
  type SourceCollectionRun,
} from "@/features/operations/ingestion-api"

vi.mock("@/features/operations/ingestion-api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/features/operations/ingestion-api")>()
  return { ...original, getSourceCollectionRuns: vi.fn() }
})

describe("CollectionRunHistory", () => {
  beforeEach(() => vi.resetAllMocks())

  it("keeps zero through three recent runs compact without a history action", () => {
    const empty = renderHistory([])
    expect(screen.getByText("No ingestion runs yet.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "View history" })).not.toBeInTheDocument()
    empty.unmount()

    const single = renderHistory([run(1)])
    expect(screen.getByRole("region", { name: "Recent ingestion history" }).querySelectorAll("li"))
      .toHaveLength(1)
    expect(screen.queryByRole("button", { name: "View history" })).not.toBeInTheDocument()
    single.unmount()

    renderHistory([
      run(3, { failureCount: 1, status: "partial", successCount: 6 }),
      run(2, { mode: "continuous", continuousCycleNumber: 12 }),
      run(1),
    ])

    const recent = screen.getByRole("region", { name: "Recent ingestion history" })
    expect(within(recent).getAllByRole("listitem")).toHaveLength(3)
    expect(within(recent).getByText("6 succeeded")).toHaveClass("text-success")
    expect(within(recent).getByText("1 failed")).toHaveClass("text-destructive")
    expect(within(recent).getByText("Continuous · Cycle #12")).toBeInTheDocument()
    expect(within(recent).queryByRole("button", { name: "View history" })).not.toBeInTheDocument()
  })

  it("shows all-success, all-failed, skipped, and active remaining counts truthfully", () => {
    renderHistory([
      run(4, { sourceCount: 10, processedCount: 10, successCount: 10 }),
      run(3, { sourceCount: 8, processedCount: 8, successCount: 0, failureCount: 8, status: "failed" }),
      run(2, { sourceCount: 9, processedCount: 9, successCount: 7, skippedCount: 2 }),
      run(1, {
        completedAt: null,
        sourceCount: 20,
        processedCount: 14,
        successCount: 12,
        failureCount: 2,
        status: "running",
      }),
    ], true)

    expect(screen.getByText("10 succeeded")).toBeInTheDocument()
    expect(screen.getByText("8 failed")).toBeInTheDocument()
    expect(screen.getByText("2 skipped")).toBeInTheDocument()
    expect(screen.getByText("6 remaining")).toBeInTheDocument()
  })

  it("opens history lazily and replaces server pages instead of preloading all runs", async () => {
    vi.mocked(getSourceCollectionRuns)
      .mockResolvedValueOnce({
        items: Array.from({ length: 25 }, (_, index) => run(101 - index)),
        total: 101,
        limit: 25,
        offset: 0,
        hasMore: true,
      })
      .mockResolvedValueOnce({
        items: Array.from({ length: 25 }, (_, index) => run(76 - index)),
        total: 101,
        limit: 25,
        offset: 25,
        hasMore: true,
      })

    renderHistory([run(101), run(100), run(99)], true)
    expect(getSourceCollectionRuns).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole("button", { name: "View history" }))
    const dialog = await screen.findByRole("dialog", { name: "Ingestion history · AI News" })
    await waitFor(() => expect(within(dialog).getAllByRole("listitem")).toHaveLength(25))
    expect(getSourceCollectionRuns).toHaveBeenNthCalledWith(
      1,
      "collection-1",
      { limit: 25, offset: 0 },
      expect.any(AbortSignal),
    )
    expect(within(dialog).getByText("1–25 of 101 runs")).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole("button", { name: "Next" }))
    await waitFor(() => expect(within(dialog).getByText("26–50 of 101 runs")).toBeInTheDocument())
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(25)
    expect(getSourceCollectionRuns).toHaveBeenNthCalledWith(
      2,
      "collection-1",
      { limit: 25, offset: 25 },
      expect.any(AbortSignal),
    )
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Previous" })).toBeEnabled())

    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(within(screen.getByRole("region", { name: "Recent ingestion history" })).getAllByRole("listitem"))
      .toHaveLength(3)
  })
})

function renderHistory(runs: SourceCollectionRun[], hasMore = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <CollectionRunHistory
        collectionId="collection-1"
        collectionName="AI News"
        hasMore={hasMore}
        runs={runs}
      />
    </QueryClientProvider>,
  )
}

function run(index: number, overrides: Partial<SourceCollectionRun> = {}): SourceCollectionRun {
  return {
    id: `run-${index}`,
    sourceCollectionId: "collection-1",
    sourceCollectionNameAtStart: "AI News",
    sourceCount: 7,
    processedCount: 7,
    successCount: 7,
    failureCount: 0,
    skippedCount: 0,
    startedAt: `2026-08-12T${String(Math.max(0, 11 - (index % 10))).padStart(2, "0")}:00:00Z`,
    completedAt: "2026-08-12T11:56:00Z",
    status: "succeeded",
    trigger: "source_collection_manual",
    mode: "once",
    continuousSubscriptionId: null,
    continuousCycleNumber: null,
    error: null,
    sources: [],
    ...overrides,
  }
}
