import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { getArticles } from "@/features/articles/api"
import type { ArticleSummary } from "@/features/articles/types"
import { getAutomations } from "@/features/automations/automation-api"
import { getJobSummary } from "@/features/jobs/api"
import { fetchOperationsDiagnostics } from "@/features/operations/api"
import { getIngestRuns, getSourceCollections, getSourcePage } from "@/features/operations/ingestion-api"
import { TodayPage } from "@/features/today/today-page"

vi.mock("@/features/articles/api", () => ({
  getArticles: vi.fn(),
}))
vi.mock("@/features/automations/automation-api", () => ({
  getAutomations: vi.fn(),
}))
vi.mock("@/features/jobs/api", () => ({
  getJobSummary: vi.fn(),
}))
vi.mock("@/features/operations/api", () => ({
  fetchOperationsDiagnostics: vi.fn(),
}))
vi.mock("@/features/operations/ingestion-api", () => ({
  getIngestRuns: vi.fn(),
  getSourceCollections: vi.fn(),
  getSourcePage: vi.fn(),
}))

const firstArticle = article({
  id: "11111111-1111-4111-8111-111111111111",
  title: "English editorial report 1",
  summary: "Source-grounded summary from NewsCraft.",
  topic: "AI",
  source: { id: "source-1", name: "Example Journal", platform: "rss", homepageUrl: "https://example.com" },
  canonicalUrl: "https://example.com/articles/1",
})
const secondArticle = article({
  id: "22222222-2222-4222-8222-222222222222",
  title: "Collected story without an image",
  summary: null,
  excerpt: "Source excerpt available for this story.",
  topic: "World",
  image: null,
  hasImage: false,
})

describe("TodayPage", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getArticles).mockResolvedValue({
      items: [firstArticle, secondArticle],
      nextCursor: null,
      resultCount: 2,
    })
    vi.mocked(getAutomations).mockResolvedValue({ items: [], nextCursor: null })
    vi.mocked(getJobSummary).mockResolvedValue({ attention: 0, queued: 0, running: 0, succeeded_today: 0 })
    vi.mocked(fetchOperationsDiagnostics).mockResolvedValue({
      attention: [],
      components: {},
      dry_run: false,
      generated_at: "2026-08-08T00:00:00Z",
      global_paused: false,
      outbound_proxy: {} as Awaited<ReturnType<typeof fetchOperationsDiagnostics>>["outbound_proxy"],
      queue_counts: {},
    })
    vi.mocked(getIngestRuns).mockResolvedValue([])
    vi.mocked(getSourceCollections).mockResolvedValue([])
    vi.mocked(getSourcePage).mockResolvedValue({ items: [], total: 0, limit: 1, offset: 0, hasMore: false })
  })

  it("renders localized loading skeletons while article summaries load", () => {
    vi.mocked(getArticles).mockImplementation(() => new Promise(() => undefined))
    renderToday()

    expect(screen.getByRole("heading", { name: "Today" })).toBeInTheDocument()
    expect(screen.getByRole("status", { name: "Loading Today" })).toBeInTheDocument()
  })

  it("renders real article summaries and opens the reference modal interaction", async () => {
    renderToday()

    expect(await screen.findByRole("heading", { name: "English editorial report 1" })).toBeInTheDocument()

    const card = screen.getByRole("button", { name: "Open story: English editorial report 1" })
    fireEvent.click(card)
    const dialog = await screen.findByRole("dialog", { name: "English editorial report 1" })
    expect(within(dialog).getByText("Source-grounded summary from NewsCraft.")).toBeInTheDocument()
    expect(within(dialog).getByRole("link", { name: "Open original at Example Journal" })).toHaveAttribute(
      "href",
      "https://example.com/articles/1",
    )
    fireEvent.click(within(dialog).getByRole("button", { name: "Close story" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
  })

  it("shows a real empty state without demo stories", async () => {
    vi.mocked(getArticles).mockResolvedValue({ items: [], nextCursor: null, resultCount: 0 })
    renderToday()

    expect(await screen.findByText("No articles collected yet")).toBeInTheDocument()
    expect(screen.queryByText(/RFK Jr|Climate Summit|EU signs off/)).not.toBeInTheDocument()
  })

  it("shows local error and retries only the Today article query", async () => {
    vi.mocked(getArticles).mockRejectedValueOnce(new Error("articles offline"))
    renderToday()

    expect(await screen.findByRole("alert")).toHaveTextContent("articles offline")
    fireEvent.click(screen.getByRole("button", { name: "Retry Today" }))
    await waitFor(() => expect(getArticles).toHaveBeenCalledTimes(2))
    expect(getArticles).toHaveBeenLastCalledWith({ sort: "newest", limit: 9 }, expect.anything())
  })

  it("keeps application chrome and reference-only demo content out of Today", async () => {
    renderToday()

    await screen.findByRole("heading", { name: "English editorial report 1" })

    expect(screen.queryByRole("complementary", { name: "Dashboard navigation" })).not.toBeInTheDocument()
    expect(screen.queryByRole("navigation", { name: "Dashboard sections" })).not.toBeInTheDocument()
    expect(screen.queryByText("Ava Morgan")).not.toBeInTheDocument()
    expect(screen.queryByText("Global Newsroom")).not.toBeInTheDocument()
    expect(screen.queryByText("Quick Action")).not.toBeInTheDocument()
    expect(screen.queryByText("Climate Summit 2025: Key Takeaways")).not.toBeInTheDocument()
    expect(screen.queryByText("Central Banks Signal Caution as Inflation Eases")).not.toBeInTheDocument()
  })
})

function renderToday() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <TodayPage />
    </QueryClientProvider>,
  )
}

function article(overrides: Partial<ArticleSummary> = {}): ArticleSummary {
  return {
    id: "00000000-0000-4000-8000-000000000000",
    title: "Untitled article",
    summary: "A source-grounded summary.",
    excerpt: null,
    source: { id: "source-0", name: "Source", platform: "rss", homepageUrl: null },
    canonicalUrl: null,
    publishedAt: "2026-07-12T08:00:00Z",
    sortAt: "2026-07-12T08:00:00Z",
    displayAt: "2026-07-12T08:00:00Z",
    dateBasis: "published",
    score: 60,
    contentType: "news",
    topic: "News",
    domain: "example.com",
    language: "en",
    direction: "ltr",
    coverage: { state: "ungrouped", stories: [] },
    image: {
      id: "image-0",
      url: "https://cdn.example.com/article.jpg",
      kind: "image",
      width: 1200,
      height: 675,
      altText: "Article image",
      fetchStatus: "available",
    },
    hasImage: true,
    saved: false,
    savedCollectionIds: [],
    articleReadiness: { ready: false },
    ...overrides,
  }
}
