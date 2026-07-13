import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import { fetchOperationsHistory } from "@/features/operations/api"
import { HistoryTimeline } from "@/features/operations/history-timeline"

vi.mock("@/features/operations/api", () => ({
  fetchOperationsHistory: vi.fn(),
}))

const routeId = "11111111-1111-4111-8111-111111111111"

describe("HistoryTimeline", () => {
  beforeEach(() => vi.resetAllMocks())

  it("filters by route, uses only pageParam as cursor, and appends durable history", async () => {
    vi.mocked(fetchOperationsHistory)
      .mockResolvedValueOnce({
        items: [
          {
            id: "event-2",
            occurredAt: "2026-07-11T08:02:00Z",
            category: "reconcile",
            status: "needs_review",
            title: "Telegram verification required",
            summary: "ارسال تلگرام باید توسط اپراتور بررسی شود",
            jobId: "22222222-2222-4222-8222-222222222222",
            subjectUrl: `/inbox?story_id=33333333-3333-4333-8333-333333333333`,
            sanitizedMetadata: {
              operation_keys: ["telegram:publish:0"],
              audit: { attempt: 2 },
            },
          },
        ],
        nextCursor: "opaque+cursor/with=query?",
      })
      .mockResolvedValueOnce({
        items: [
          {
            id: "event-1",
            occurredAt: "2026-07-11T07:30:00Z",
            category: "collection",
            status: "captured",
            title: "Route poll captured an item",
            summary: "One durable source item was captured.",
            jobId: null,
            subjectUrl: `/automations/${routeId}`,
            sanitizedMetadata: { item_count: 1 },
          },
        ],
        nextCursor: null,
      })

    renderTimeline()

    expect(await screen.findByText("Telegram verification required")).toBeInTheDocument()
    expect(fetchOperationsHistory).toHaveBeenNthCalledWith(1, {
      subjectType: "automation_route",
      subjectId: routeId,
      limit: 50,
    })
    expect(screen.getByText("Jul 11, 2026, 11:32 AM")).toBeInTheDocument()
    expect(screen.getByText(/telegram:publish:0/)).toBeInTheDocument()
    expect(screen.getByText(/"attempt": 2/)).toBeInTheDocument()
    expect(screen.getByText("ارسال تلگرام باید توسط اپراتور بررسی شود").closest("[dir]"))
      .toHaveAttribute("dir", "auto")
    expect(screen.getByRole("link", { name: "Open related record" })).toHaveAttribute(
      "href",
      "/inbox?story_id=33333333-3333-4333-8333-333333333333",
    )

    fireEvent.click(screen.getByRole("button", { name: "Load more history" }))

    expect(await screen.findByText("Route poll captured an item")).toBeInTheDocument()
    expect(screen.getByText("Telegram verification required")).toBeInTheDocument()
    expect(fetchOperationsHistory).toHaveBeenNthCalledWith(2, {
      subjectType: "automation_route",
      subjectId: routeId,
      limit: 50,
      cursor: "opaque+cursor/with=query?",
    })
    expect(screen.queryByRole("button", { name: "Load more history" })).not.toBeInTheDocument()
  })

  it("renders truthful empty and retryable error states", async () => {
    vi.mocked(fetchOperationsHistory).mockRejectedValueOnce(new Error("History storage unavailable"))
    const first = renderTimeline()

    expect(await screen.findByRole("alert")).toHaveTextContent("History storage unavailable")
    expect(screen.getByRole("alert")).toHaveAttribute("dir", "auto")
    first.unmount()

    vi.mocked(fetchOperationsHistory).mockResolvedValueOnce({ items: [], nextCursor: null })
    renderTimeline()
    expect(await screen.findByText("No durable history has been recorded for this route.")).toBeInTheDocument()
  })
})

function renderTimeline() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <HistoryTimeline routeId={routeId} />
    </QueryClientProvider>,
  )
}
