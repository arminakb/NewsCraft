import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import {
  createArticleCollection,
  clearFeed,
  deleteArticleCollection,
  getArticle,
  getArticleCollections,
  getArticleFacets,
  getFeedSummary,
  getArticles,
  removeArticleFromCollection,
  renameArticleCollection,
  saveArticleToCollection,
} from "@/features/articles/api"
import { ArticlesPage } from "@/features/articles/articles-page"
import type { ArticleCollection, ArticleDetail, ArticlePage, ArticleSummary } from "@/features/articles/types"
import { ApiError } from "@/lib/http"

const navigation = vi.hoisted(() => ({ search: "", listeners: new Set<() => void>(), push: vi.fn() }))

vi.mock("next/navigation", async () => {
  const React = await import("react")
  return {
    usePathname: () => "/feed",
    useRouter: () => ({
      push: (url: string) => {
        navigation.push(url)
        navigation.search = url.includes("?") ? url.slice(url.indexOf("?") + 1) : ""
        navigation.listeners.forEach((listener) => listener())
      },
    }),
    useSearchParams: () => {
      const search = React.useSyncExternalStore(
        (listener) => { navigation.listeners.add(listener); return () => navigation.listeners.delete(listener) },
        () => navigation.search,
        () => navigation.search,
      )
      return new URLSearchParams(search)
    },
  }
})

vi.mock("@/features/articles/api", () => ({
  createArticleCollection: vi.fn(),
  clearFeed: vi.fn(),
  deleteArticleCollection: vi.fn(),
  getArticleCollections: vi.fn(),
  getArticle: vi.fn(),
  getArticles: vi.fn(),
  getArticleFacets: vi.fn(),
  getFeedSummary: vi.fn(),
  removeArticleFromCollection: vi.fn(),
  renameArticleCollection: vi.fn(),
  saveArticleToCollection: vi.fn(),
}))

describe("Feed page", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    setSearch("")
    const pushState = window.history.pushState.bind(window.history)
    vi.spyOn(window.history, "pushState").mockImplementation((state, unused, url) => {
      pushState(state, unused, url)
      const value = String(url ?? "")
      navigation.search = value.includes("?") ? value.slice(value.indexOf("?") + 1) : ""
      navigation.listeners.forEach((listener) => listener())
    })
    vi.mocked(getArticleCollections).mockResolvedValue([])
    vi.mocked(getArticleFacets).mockResolvedValue(facets())
    vi.mocked(getFeedSummary).mockResolvedValue({ articleCount: 0 })
    vi.mocked(clearFeed).mockResolvedValue({ clearedCount: 0 })
    vi.mocked(removeArticleFromCollection).mockResolvedValue()
    vi.mocked(deleteArticleCollection).mockResolvedValue()
    vi.mocked(renameArticleCollection).mockImplementation(async (_, name) => collection({ name }))
    vi.mocked(saveArticleToCollection).mockResolvedValue()
  })

  afterEach(() => vi.restoreAllMocks())

  it("renders an image-first English and Persian card grid with truthful metadata and bidi boundaries", async () => {
    vi.mocked(getArticles).mockResolvedValue({
      items: [
        article({
          id: "english",
          title: "English report",
          summary: "English summary",
          image: image(),
          hasImage: true,
          dateBasis: "published",
        }),
        article({
          id: "persian",
          title: "گزارش فارسی",
          summary: null,
          excerpt: "خلاصه جایگزین",
          language: "fa",
          direction: "rtl",
          source: { id: null, name: "خبرگزاری نمونه", platform: "rss", homepageUrl: null },
          image: null,
          hasImage: false,
          dateBasis: "collected",
          coverage: { state: "ungrouped", stories: [] },
        }),
      ],
      nextCursor: null,
      resultCount: 2,
    })
    renderArticles()

    expect(screen.getByRole("heading", { name: "Feed", level: 1 })).toBeInTheDocument()
    expect(await screen.findByText("2 articles · source monitoring and saved collections")).toBeInTheDocument()
    expect(screen.getByText("English report").closest("[data-testid='direction-boundary']"))
      .toHaveAttribute("dir", "ltr")
    expect(screen.getByText("گزارش فارسی").closest("[data-testid='direction-boundary']"))
      .toHaveAttribute("dir", "rtl")
    expect(screen.getByText("گزارش فارسی").closest("[data-testid='direction-boundary']"))
      .toHaveAttribute("lang", "fa")
    expect(screen.getByText("خبرگزاری نمونه").closest("bdi")).toHaveAttribute("dir", "auto")
    expect(screen.queryByText("خلاصه جایگزین")).not.toBeInTheDocument()
    const publishedTime = screen.getByTitle(/^Published /)
    const collectedTime = screen.getByTitle(/^Collected /)
    expect(publishedTime).toHaveTextContent(/ago|just now|^in /)
    expect(publishedTime).toHaveAccessibleName(/Exact publication time:/)
    expect(collectedTime).toHaveTextContent(/ago|just now|^in /)
    expect(collectedTime).toHaveAccessibleName(/Exact collection time:.*publication time unavailable/)
    expect(collectedTime).toHaveAttribute("dir", "ltr")
    expect(screen.queryByText(/Jul 21, 2026/)).not.toBeInTheDocument()
    expect(screen.getAllByLabelText("Editorial score: 64")).toHaveLength(2)
    expect(screen.queryByText("Score 64")).not.toBeInTheDocument()
    expect(screen.getByRole("img", { name: "No article image" })).toBeInTheDocument()
    const sourceLink = screen.getByRole("link", { name: "Open original article: English report" })
    expect(sourceLink).toHaveAttribute("href", "https://example.com/article")
    expect(sourceLink).toHaveAttribute("rel", "noreferrer noopener")
    expect(sourceLink).toHaveTextContent("Source")
    expect(sourceLink).toHaveClass("text-xs")
    expect(screen.getAllByRole("article")).toHaveLength(2)
    expect(screen.getByLabelText("Feed results")).toHaveClass("feed-card-grid")
    for (const card of screen.getAllByRole("article")) expect(card).toHaveClass("h-full")
    fireEvent.error(screen.getByRole("img", { name: "Editorial image" }))
    expect(screen.getByRole("img", { name: "Image unavailable for English report" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Automation action — not configured yet" })).not.toBeInTheDocument()
    expect(saveArticleToCollection).not.toHaveBeenCalled()
    expect(removeArticleFromCollection).not.toHaveBeenCalled()
  })

  it("clears the whole Feed while preserving collection navigation", async () => {
    let cleared = false
    vi.mocked(getFeedSummary).mockResolvedValue({ articleCount: 2 })
    vi.mocked(getArticleCollections).mockResolvedValue([collection({ articleCount: 1 })])
    vi.mocked(getArticles).mockImplementation(async () => cleared
      ? { items: [], nextCursor: null, resultCount: 0 }
      : { items: [article()], nextCursor: null, resultCount: 2 })
    vi.mocked(clearFeed).mockImplementation(async () => {
      cleared = true
      return { clearedCount: 2 }
    })
    renderArticles()

    fireEvent.click(await findEnabledClearFeedButton())
    const dialog = await screen.findByRole("dialog", { name: "Clear Feed?" })
    expect(dialog).toHaveTextContent("This will remove 2 collected articles from the Feed.")
    expect(dialog).toHaveTextContent("Your Sources, Source Collections, and ingestion settings will remain unchanged.")
    fireEvent.click(within(dialog).getByRole("button", { name: "Clear Feed" }))

    await waitFor(() => expect(clearFeed).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Clear Feed?" })).not.toBeInTheDocument())
    expect(await screen.findByText("0 articles · source monitoring and saved collections")).toBeInTheDocument()
    expect(screen.queryByRole("article")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Research.*1 article/ })).toBeInTheDocument()
    expect(screen.getByText("Feed cleared. 2 articles removed.")).toBeInTheDocument()
  })

  it("keeps the clear dialog recoverable after a backend failure", async () => {
    vi.mocked(getFeedSummary).mockResolvedValue({ articleCount: 1 })
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    vi.mocked(clearFeed)
      .mockRejectedValueOnce(new ApiError("Unavailable", 503, JSON.stringify({ detail: "Feed could not be cleared right now. Try again." })))
      .mockResolvedValueOnce({ clearedCount: 1 })
    renderArticles()

    fireEvent.click(await findEnabledClearFeedButton())
    const dialog = await screen.findByRole("dialog", { name: "Clear Feed?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Clear Feed" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Feed could not be cleared right now. Try again.")
    expect(screen.getByRole("dialog", { name: "Clear Feed?" })).toBeInTheDocument()

    fireEvent.click(within(dialog).getByRole("button", { name: "Retry clear" }))
    await waitFor(() => expect(clearFeed).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Clear Feed?" })).not.toBeInTheDocument())
  })

  it("loads article details only after opening, renders plain full content, caches, and restores focus", async () => {
    const request = deferred<ArticleDetail>()
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    vi.mocked(getArticle).mockReturnValue(request.promise)
    const { container } = renderArticles()

    const trigger = await screen.findByRole("button", { name: "View article details: Article title" })
    expect(getArticle).not.toHaveBeenCalled()
    trigger.focus()
    fireEvent.click(trigger)

    let dialog = screen.getByRole("dialog", { name: "Article title" })
    expect(within(dialog).getByRole("status", { name: "Loading article details" })).toBeInTheDocument()
    expect(getArticle).toHaveBeenCalledWith("article")
    request.resolve(articleDetail({
      contentText: "Complete first paragraph.\n\n<script>window.__article_attack = true</script>",
      contentOrigin: "source_provided",
    }))

    expect(await within(dialog).findByText("Complete first paragraph.")).toBeInTheDocument()
    expect(within(dialog).getByText("Source-provided content")).toBeInTheDocument()
    expect(within(dialog).getByText("<script>window.__article_attack = true</script>")).toBeInTheDocument()
    expect(container.querySelector("script")).not.toBeInTheDocument()
    expect(within(dialog).getByRole("link", { name: "Open original source" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    )

    fireEvent.click(within(dialog).getByRole("button", { name: "Close article details" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Article title" })).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())

    fireEvent.click(trigger)
    dialog = screen.getByRole("dialog", { name: "Article title" })
    expect(within(dialog).getByText("Complete first paragraph.")).toBeInTheDocument()
    expect(getArticle).toHaveBeenCalledTimes(1)
  })

  it("renders the article source's resolved stored icon in the detail popup", async () => {
    const source = {
      id: "source-1",
      name: "Hacker News",
      platform: "rss",
      homepageUrl: "https://news.ycombinator.com",
      iconUrl: "/sources/source-1/icon.svg",
      iconStatus: "resolved",
      iconUpdatedAt: "2026-08-12T10:00:00Z",
    }
    vi.mocked(getArticles).mockResolvedValue({
      items: [article({ source: source as ArticleSummary["source"] })],
      nextCursor: null,
      resultCount: 1,
    })
    vi.mocked(getArticle).mockResolvedValue(
      articleDetail({ source: source as ArticleDetail["source"] }),
    )
    renderArticles()

    fireEvent.click(await screen.findByRole("button", { name: "View article details: Article title" }))
    const dialog = await screen.findByRole("dialog", { name: "Article title" })
    const sourceIcon = await waitFor(() => {
      const image = dialog.querySelector<HTMLImageElement>("img")
      expect(image).toBeInTheDocument()
      return image
    })

    expect(sourceIcon).toHaveAttribute(
      "src",
      "/api/backend/sources/source-1/icon.svg?v=2026-08-12T10%3A00%3A00Z",
    )
    expect(sourceIcon).toHaveClass("object-contain")
    expect(within(dialog).getByText("Hacker News", { selector: "bdi" })).toBeInTheDocument()
    expect(getArticle).toHaveBeenCalledTimes(1)
  })

  it("keeps nested card actions independent from article details", async () => {
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    renderArticles()

    fireEvent.click(await screen.findByRole("button", { name: "Save article to collection" }))

    expect(screen.getByRole("dialog", { name: "Save to Collection" })).toBeInTheDocument()
    expect(screen.queryByRole("dialog", { name: "Article title" })).not.toBeInTheDocument()
    expect(getArticle).not.toHaveBeenCalled()
  })

  it("debounces normalized title search, preserves URL state, paginates, and clears", async () => {
    setSearch("language=en&cursor=stale")
    vi.mocked(getArticles).mockResolvedValue({
      items: [article({ title: "Climate report" })], nextCursor: "search-page-2", resultCount: 100,
    })
    renderArticles()
    await screen.findByText("Climate report")

    const input = screen.getByRole("searchbox", { name: "Search articles" })
    expect(input.parentElement).toHaveClass("has-[:focus-visible]:border-ring")
    expect(input.parentElement).not.toHaveClass("focus-within:ring-2", "focus-within:ring-ring")
    fireEvent.change(input, { target: { value: "  Climate  " } })
    expect(navigation.push).not.toHaveBeenCalled()
    await waitFor(() => expect(window.history.pushState).toHaveBeenLastCalledWith(null, "", "/feed?language=en&q=Climate"))
    expect(getArticles).toHaveBeenLastCalledWith({
      sort: "newest", query: "Climate", filters: { ...emptyFilters(), languages: ["en"] }, cursor: null, limit: 50,
    }, expect.any(AbortSignal))

    fireEvent.click(screen.getByRole("button", { name: "Go to page 2" }))
    await waitFor(() => expect(navigation.search).toContain("page=2"))
    expect(navigation.search).toContain("cursor=search-page-2")
    expect(screen.getByText("Climate report")).toBeInTheDocument()

    const callsBeforeEquivalentInput = vi.mocked(getArticles).mock.calls.length
    fireEvent.change(input, { target: { value: " Climate " } })
    await new Promise((resolve) => setTimeout(resolve, 350))
    expect(vi.mocked(getArticles).mock.calls).toHaveLength(callsBeforeEquivalentInput)

    fireEvent.click(screen.getByRole("button", { name: "Clear search input" }))
    await waitFor(() => expect(window.history.pushState).toHaveBeenLastCalledWith(null, "", "/feed?language=en"))
    expect(getArticles).toHaveBeenLastCalledWith({
      sort: "newest", filters: { ...emptyFilters(), languages: ["en"] }, cursor: null, limit: 50,
    }, expect.any(AbortSignal))
  })

  it("restores article search from URL and shows the query empty state", async () => {
    setSearch("q=%DA%AF%D8%B2%D8%A7%D8%B1%D8%B4&topic=Tech")
    vi.mocked(getArticles).mockResolvedValue({ items: [], nextCursor: null, resultCount: 0 })
    renderArticles()

    expect(await screen.findByText("No articles match “گزارش”")).toBeInTheDocument()
    expect(screen.getByRole("searchbox", { name: "Search articles" })).toHaveValue("گزارش")
    expect(getArticles).toHaveBeenLastCalledWith({
      sort: "newest", query: "گزارش", filters: { ...emptyFilters(), topics: ["Tech"] }, cursor: null, limit: 50,
    }, expect.any(AbortSignal))
    fireEvent.click(screen.getByRole("button", { name: "Clear article search" }))
    await waitFor(() => expect(window.history.pushState).toHaveBeenLastCalledWith(null, "", "/feed?topic=Tech"))
  })

  it("replaces page dataset and unmounts previous article cards", async () => {
    const nextPage = deferred<ArticlePage>()
    vi.mocked(getArticles).mockImplementation(({ cursor }) => cursor === null
      ? Promise.resolve({ items: [article({ id: "first", title: "First" })], nextCursor: "page-2", resultCount: 100 })
      : nextPage.promise)
    renderArticles()

    expect(await screen.findByText("First")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Go to page 2" }))
    await waitFor(() => expect(navigation.search).toContain("page=2"))
    expect(screen.queryByText("First")).not.toBeInTheDocument()
    expect(screen.getByRole("status", { name: "Loading articles" })).toBeInTheDocument()

    nextPage.resolve({
      items: [article({ id: "second", title: "Second" })],
      nextCursor: null,
      resultCount: 100,
    })
    expect(await screen.findByText("Second")).toBeInTheDocument()
    expect(screen.queryByText("First")).not.toBeInTheDocument()
    expect(screen.getAllByRole("article")).toHaveLength(1)
  })

  it("resets pagination when sort changes", async () => {
    vi.mocked(getArticles).mockImplementation(async ({ sort }) => ({
      items: [article({ id: sort, title: sort === "newest" ? "Newest item" : "Highest score" })],
      nextCursor: sort === "newest" ? "old-cursor" : null,
      resultCount: 1,
    }))
    renderArticles()

    expect(await screen.findByText("Newest item")).toBeInTheDocument()
    fireEvent.change(screen.getByRole("combobox", { name: "Sort articles" }), { target: { value: "score" } })
    expect(await screen.findByText("Highest score")).toBeInTheDocument()
    expect(getArticles).toHaveBeenLastCalledWith({ sort: "score", filters: emptyFilters(), cursor: null, limit: 50 }, expect.any(AbortSignal))
    expect(screen.queryByText("Newest item")).not.toBeInTheDocument()
  })

  it("shows initial loading, retryable error, and empty state", async () => {
    const first = deferred<ArticlePage>()
    vi.mocked(getArticles).mockReturnValueOnce(first.promise).mockResolvedValueOnce({ items: [], nextCursor: null, resultCount: 0 })
    renderArticles()

    expect(screen.getByRole("status", { name: "Loading articles" })).toBeInTheDocument()
    first.reject(new Error("articles offline"))
    expect(await screen.findByRole("alert")).toHaveTextContent("articles offline")
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByText("No articles collected")).toBeInTheDocument()
  })

  it("renders a safe relative-time fallback for an invalid display timestamp", async () => {
    vi.mocked(getArticles).mockResolvedValue({
      items: [article({ displayAt: "not-a-date" })],
      nextCursor: null,
      resultCount: 1,
    })
    renderArticles()

    const time = await screen.findByText("Time unavailable")
    expect(time).toHaveAccessibleName("Published time unavailable")
    expect(time).not.toHaveAttribute("datetime")
  })

  it("keeps primary controls at least 44px on mobile", async () => {
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: "next", resultCount: 100 })
    const { container } = renderArticles()
    await screen.findByRole("article")

    expect(screen.getByRole("combobox", { name: "Sort articles" })).toHaveClass("min-h-11")
    expect(screen.getByRole("button", { name: "Filter articles" })).toHaveClass("min-h-11")
    expect(screen.getByTestId("feed-pagination")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Next page" })).toHaveClass("min-h-11")
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument()
    expect(screen.getByRole("complementary", { name: "Collections" })).toHaveClass("overflow-x-auto")
    expect(screen.getByRole("button", { name: "All articles" })).toHaveClass("min-h-11", "min-w-32")
    const row = screen.getByRole("article")
    expect(within(row).getByRole("link", { name: /Open original article/ })).toHaveClass("min-h-11")
    expect(container.querySelector("section")).toHaveClass("w-full")
  })

  it("combines facet selections, writes URL state, and shows removable chips", async () => {
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    renderArticles()
    await screen.findByRole("article")

    fireEvent.click(screen.getByRole("button", { name: "Filter articles" }))
    fireEvent.click(screen.getByRole("checkbox", { name: /en/i }))
    fireEvent.click(screen.getByRole("checkbox", { name: /AI/ }))
    fireEvent.click(screen.getByRole("checkbox", { name: /Tech/ }))
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }))

    await waitFor(() => expect(getArticles).toHaveBeenLastCalledWith({
      sort: "newest",
      filters: { ...emptyFilters(), languages: ["en"], topics: ["AI", "Tech"] },
      cursor: null,
      limit: 50,
    }, expect.any(AbortSignal)))
    expect(navigation.push).toHaveBeenLastCalledWith("/feed?language=en&topic=AI&topic=Tech")
    expect(screen.getByRole("button", { name: "Filter articles, 3 active" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Remove filter EN" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Remove filter AI" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Remove filter Tech" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Remove filter AI" }))
    await waitFor(() => expect(screen.queryByRole("button", { name: "Remove filter AI" })).not.toBeInTheDocument())
    expect(navigation.push).toHaveBeenLastCalledWith("/feed?language=en&topic=Tech")

    fireEvent.click(screen.getByRole("button", { name: "Clear all" }))
    expect(navigation.push).toHaveBeenLastCalledWith("/feed")
  })

  it("applies sources, coverage, image, score, and date bounds together", async () => {
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    renderArticles()
    await screen.findByRole("article")
    fireEvent.click(screen.getByRole("button", { name: "Filter articles" }))
    fireEvent.click(screen.getByRole("checkbox", { name: /Alpha Wire/ }))
    fireEvent.click(screen.getByRole("checkbox", { name: /Beta Wire/ }))
    fireEvent.click(screen.getByRole("checkbox", { name: /Complete/ }))
    fireEvent.change(screen.getByRole("combobox", { name: "Has image" }), { target: { value: "true" } })
    fireEvent.change(screen.getByLabelText("Minimum score"), { target: { value: "20" } })
    fireEvent.change(screen.getByLabelText("Maximum score"), { target: { value: "80" } })
    fireEvent.change(screen.getByLabelText("Date from"), { target: { value: "2026-07-01" } })
    fireEvent.change(screen.getByLabelText("Date to"), { target: { value: "2026-07-21" } })
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }))

    await waitFor(() => expect(getArticles).toHaveBeenLastCalledWith({
      sort: "newest",
      filters: {
        ...emptyFilters(), sourceIds: [sourceA, sourceB], coverage: ["complete"], hasImage: true,
        scoreMin: 20, scoreMax: 80, dateFrom: "2026-07-01", dateTo: "2026-07-21",
      },
      cursor: null,
      limit: 50,
    }, expect.any(AbortSignal)))
    expect(navigation.search).toContain(`source_id=${sourceA}`)
    expect(navigation.search).toContain(`source_id=${sourceB}`)
    expect(screen.getByRole("button", { name: "Filter articles, 8 active" })).toBeInTheDocument()
  })

  it("restores sort and filters from URL changes and ignores invalid URL values", async () => {
    setSearch("sort=invalid&source_id=not-a-uuid&coverage=wrong&has_image=maybe&score_min=x&date_from=bad&language=en")
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    renderArticles()

    await waitFor(() => expect(getArticles).toHaveBeenLastCalledWith({
      sort: "newest", filters: { ...emptyFilters(), languages: ["en"] }, cursor: null, limit: 50,
    }, expect.any(AbortSignal)))
    setSearch("sort=score&topic=AI&topic=Tech")
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Sort articles" })).toHaveValue("score"))
    expect(screen.getByRole("button", { name: "Filter articles, 2 active" })).toBeInTheDocument()
    expect(getArticles).toHaveBeenLastCalledWith({
      sort: "score", filters: { ...emptyFilters(), topics: ["AI", "Tech"] }, cursor: null, limit: 50,
    }, expect.any(AbortSignal))
  })

  it("resets page and cursor after a filter change", async () => {
    setSearch("language=en&page=2&cursor=en-page-2")
    vi.mocked(getArticles).mockImplementation(async ({ filters }) => filters?.topics.includes("Tech")
      ? { items: [article({ id: "tech", title: "Tech" })], nextCursor: null, resultCount: 1 }
      : { items: [article({ id: "second", title: "Second" })], nextCursor: null, resultCount: 100, }
    )
    renderArticles()
    expect(await screen.findByText("Second")).toBeInTheDocument()
    setSearch("language=en&topic=Tech")
    await screen.findByText("Tech")
    expect(getArticles).toHaveBeenLastCalledWith({
      sort: "newest", filters: { ...emptyFilters(), languages: ["en"], topics: ["Tech"] }, cursor: null, limit: 50,
    }, expect.any(AbortSignal))
    expect(screen.queryByText("Second")).not.toBeInTheDocument()
  })

  it("shows filtered empty state and clears all filters", async () => {
    setSearch("language=en")
    vi.mocked(getArticles).mockResolvedValue({ items: [], nextCursor: null, resultCount: 0 })
    renderArticles()
    expect(await screen.findByText("No articles match these filters")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }))
    expect(navigation.push).toHaveBeenLastCalledWith("/feed")
  })

  it("loads facets once and exposes retry, Escape close, and focus restoration", async () => {
    const options = deferred<ReturnType<typeof facets>>()
    vi.mocked(getArticleFacets).mockReturnValue(options.promise)
    vi.mocked(getArticles).mockResolvedValue({ items: [], nextCursor: null, resultCount: 0 })
    renderArticles()
    const trigger = screen.getByRole("button", { name: "Filter articles" })
    trigger.focus()
    fireEvent.click(trigger)
    expect(screen.getByRole("status", { name: "Loading filter options" })).toBeInTheDocument()
    options.reject(new Error("facets offline"))
    expect(await screen.findByRole("alert")).toHaveTextContent("facets offline")
    expect(getArticleFacets).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Filter articles" })).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it("selects collections through URL state while preserving filters and resets pagination", async () => {
    setSearch("language=en")
    vi.mocked(getArticleCollections).mockResolvedValue([collection({ articleCount: 2 })])
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    renderArticles()

    const collectionButton = await screen.findByRole("button", { name: /Research.*2 articles/ })
    expect(collectionButton).toHaveAccessibleName(/2 articles/)
    fireEvent.click(collectionButton)

    await waitFor(() => expect(getArticles).toHaveBeenLastCalledWith({
      sort: "newest",
      filters: { ...emptyFilters(), languages: ["en"] },
      collectionId,
      cursor: null,
      limit: 50,
    }, expect.any(AbortSignal)))
    expect(navigation.push).toHaveBeenLastCalledWith(`/feed?language=en&collection_id=${collectionId}`)
    expect(collectionButton).toHaveAttribute("aria-current", "page")

    fireEvent.click(screen.getByRole("button", { name: "All articles" }))
    expect(navigation.push).toHaveBeenLastCalledWith("/feed?language=en")
    expect(getArticles).toHaveBeenLastCalledWith({
      sort: "newest",
      filters: { ...emptyFilters(), languages: ["en"] },
      cursor: null,
      limit: 50,
    }, expect.any(AbortSignal))
  })

  it("creates, refreshes, selects, and announces a trimmed collection", async () => {
    const created = deferred<ArticleCollection>()
    const createdCollection = collection({ name: "Reading Queue", articleCount: 0 })
    vi.mocked(getArticleCollections)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([createdCollection])
    vi.mocked(getArticles).mockResolvedValue({ items: [], nextCursor: null, resultCount: 0 })
    vi.mocked(createArticleCollection).mockReturnValue(created.promise)
    renderArticles()

    const trigger = await screen.findByRole("button", { name: "Create new collection" })
    await waitFor(() => expect(trigger).toBeEnabled())
    fireEvent.click(trigger)
    const input = screen.getByRole("textbox", { name: "Collection name" })
    await waitFor(() => expect(input).toHaveFocus())
    fireEvent.change(input, { target: { value: "  Reading Queue  " } })
    fireEvent.click(screen.getByRole("button", { name: "Create collection" }))

    const pendingButton = screen.getByRole("button", { name: "Creating…" })
    expect(pendingButton).toBeDisabled()
    fireEvent.click(pendingButton)
    expect(createArticleCollection).toHaveBeenCalledTimes(1)
    created.resolve(createdCollection)
    await waitFor(() => expect(createArticleCollection).toHaveBeenCalledWith("Reading Queue"))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "New Collection" })).not.toBeInTheDocument())
    expect(navigation.push).toHaveBeenLastCalledWith(`/feed?collection_id=${collectionId}`)
    expect(await screen.findByText("Collection Reading Queue created and selected.")).toBeInTheDocument()
    expect(getArticleCollections).toHaveBeenCalledTimes(2)
  })

  it("cancels New Collection once without validation and resets every dismissal path", async () => {
    vi.mocked(getArticles).mockResolvedValue({ items: [], nextCursor: null, resultCount: 0 })
    renderArticles()
    const trigger = await screen.findByRole("button", { name: "Create new collection" })
    await waitFor(() => expect(trigger).toBeEnabled())

    trigger.focus()
    fireEvent.click(trigger)
    let dialog = screen.getByRole("dialog", { name: "New Collection" })
    let input = within(dialog).getByRole("textbox", { name: "Collection name" })
    let cancel = within(dialog).getByRole("button", { name: "Cancel" })
    expect(cancel).toHaveAttribute("type", "button")
    fireEvent.blur(input, { relatedTarget: cancel })
    cancel.focus()
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument()
    fireEvent.click(cancel)
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())

    fireEvent.click(trigger)
    dialog = screen.getByRole("dialog", { name: "New Collection" })
    input = within(dialog).getByRole("textbox", { name: "Collection name" })
    expect(input).toHaveValue("")
    fireEvent.submit(input.closest("form")!)
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Enter a collection name.")
    cancel = within(dialog).getByRole("button", { name: "Cancel" })
    fireEvent.click(cancel)
    await waitFor(() => expect(dialog).not.toBeInTheDocument())

    fireEvent.click(trigger)
    dialog = screen.getByRole("dialog", { name: "New Collection" })
    input = within(dialog).getByRole("textbox", { name: "Collection name" })
    expect(input).toHaveValue("")
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument()
    fireEvent.change(input, { target: { value: "Escape draft" } })
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())

    fireEvent.click(trigger)
    dialog = screen.getByRole("dialog", { name: "New Collection" })
    input = within(dialog).getByRole("textbox", { name: "Collection name" })
    expect(input).toHaveValue("")
    fireEvent.change(input, { target: { value: "Backdrop draft" } })
    fireEvent.mouseDown(dialog)
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())

    fireEvent.click(trigger)
    expect(screen.getByRole("textbox", { name: "Collection name" })).toHaveValue("")
    expect(createArticleCollection).not.toHaveBeenCalled()
  })

  it("shows inline name validation and duplicate-name server errors", async () => {
    vi.mocked(getArticles).mockResolvedValue({ items: [], nextCursor: null, resultCount: 0 })
    vi.mocked(createArticleCollection).mockRejectedValue(new ApiError(
      "Conflict",
      409,
      JSON.stringify({ detail: "article collection name already exists" }),
    ))
    renderArticles()
    const trigger = await screen.findByRole("button", { name: "Create new collection" })
    await waitFor(() => expect(trigger).toBeEnabled())
    trigger.focus()
    fireEvent.click(trigger)
    const input = screen.getByRole("textbox", { name: "Collection name" })

    fireEvent.blur(input)
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a collection name.")
    fireEvent.change(input, { target: { value: "x".repeat(61) } })
    expect(screen.getByRole("alert")).toHaveTextContent("60 characters or fewer")
    fireEvent.change(input, { target: { value: "Research" } })
    fireEvent.click(screen.getByRole("button", { name: "Create collection" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("article collection name already exists")
    expect(screen.getByRole("dialog", { name: "New Collection" })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "New Collection" })).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())
    fireEvent.click(trigger)
    const reopened = screen.getByRole("dialog", { name: "New Collection" })
    expect(within(reopened).getByRole("textbox", { name: "Collection name" })).toHaveValue("")
    expect(within(reopened).queryByRole("alert")).not.toBeInTheDocument()
    fireEvent.click(within(reopened).getByRole("button", { name: "Cancel" }))
  })

  it("recovers from unknown collection IDs and explains empty collections", async () => {
    setSearch(`collection_id=${collectionId}`)
    vi.mocked(getArticleCollections).mockResolvedValue([])
    const firstRender = renderArticles()

    expect(await screen.findByText("Collection no longer available")).toBeInTheDocument()
    expect(getArticles).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole("button", { name: "Return to all articles" }))
    expect(navigation.push).toHaveBeenLastCalledWith("/feed")
    firstRender.unmount()

    setSearch(`collection_id=${collectionId}`)
    vi.mocked(getArticleCollections).mockResolvedValue([collection({ articleCount: 0 })])
    vi.mocked(getArticles).mockResolvedValue({ items: [], nextCursor: null, resultCount: 0 })
    renderArticles()
    expect(await screen.findByText("Research is empty")).toBeInTheDocument()
    expect(screen.getByText(/Use Save to Collection/)).toBeInTheDocument()
  })

  it("retries collection-list failures and recovers when a selected collection is deleted remotely", async () => {
    vi.mocked(getArticleCollections)
      .mockRejectedValueOnce(new Error("collections offline"))
      .mockResolvedValueOnce([])
    vi.mocked(getArticles).mockResolvedValue({ items: [], nextCursor: null, resultCount: 0 })
    const firstRender = renderArticles()

    expect(await screen.findByRole("alert")).toHaveTextContent("collections offline")
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByText("No collections yet.")).toBeInTheDocument()
    expect(getArticleCollections).toHaveBeenCalledTimes(2)
    firstRender.unmount()

    setSearch(`collection_id=${collectionId}`)
    vi.mocked(getArticleCollections).mockResolvedValue([collection()])
    vi.mocked(getArticles).mockRejectedValue(new ApiError(
      "Not Found",
      404,
      JSON.stringify({ detail: "article collection not found" }),
    ))
    renderArticles()
    expect(await screen.findByText("Collection no longer available")).toBeInTheDocument()
  })

  it("prechecks memberships, applies only the diff, reconciles counts, and restores focus", async () => {
    const archive = collection({ id: secondCollectionId, name: "Archive", articleCount: 4 })
    vi.mocked(getArticleCollections)
      .mockResolvedValueOnce([collection(), archive])
      .mockResolvedValueOnce([collection({ articleCount: 2 }), archive])
    vi.mocked(getArticles)
      .mockResolvedValueOnce({
        items: [article({ saved: true, savedCollectionIds: [collectionId] })],
        nextCursor: null,
        resultCount: 1,
      })
      .mockResolvedValueOnce({
        items: [article({ saved: true, savedCollectionIds: [secondCollectionId] })],
        nextCursor: null,
        resultCount: 1,
      })
    renderArticles()

    const trigger = await screen.findByRole("button", { name: "Save article to collection" })
    trigger.focus()
    fireEvent.click(trigger)
    const dialog = screen.getByRole("dialog", { name: "Save to Collection" })
    const research = within(dialog).getByRole("checkbox", { name: /Research.*3 articles/ })
    const archiveCheckbox = within(dialog).getByRole("checkbox", { name: /Archive.*4 articles/ })
    await waitFor(() => expect(research).toHaveFocus())
    expect(research).toBeChecked()
    expect(archiveCheckbox).not.toBeChecked()

    fireEvent.click(research)
    fireEvent.click(archiveCheckbox)
    fireEvent.click(within(dialog).getByRole("button", { name: "Apply" }))

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Save to Collection" })).not.toBeInTheDocument())
    expect(removeArticleFromCollection).toHaveBeenCalledWith(collectionId, "article")
    expect(saveArticleToCollection).toHaveBeenCalledWith(secondCollectionId, "article")
    expect(removeArticleFromCollection).toHaveBeenCalledTimes(1)
    expect(saveArticleToCollection).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(trigger).toHaveFocus())
    expect(screen.getByText("Article saved to 1 collection.")).toBeInTheDocument()
  })

  it("keeps partial failures open, reloads confirmed truth, and retries without duplicate mutations", async () => {
    const archive = collection({ id: secondCollectionId, name: "Archive", articleCount: 0 })
    vi.mocked(getArticleCollections).mockResolvedValue([collection(), archive])
    vi.mocked(getArticles)
      .mockResolvedValueOnce({
        items: [article({ saved: true, savedCollectionIds: [collectionId] })], nextCursor: null, resultCount: 1,
      })
      .mockResolvedValueOnce({ items: [article()], nextCursor: null, resultCount: 1 })
      .mockResolvedValueOnce({
        items: [article({ saved: true, savedCollectionIds: [secondCollectionId] })], nextCursor: null, resultCount: 1,
      })
    vi.mocked(saveArticleToCollection)
      .mockRejectedValueOnce(new ApiError("Not Found", 404, JSON.stringify({ detail: "collection was deleted" })))
      .mockResolvedValueOnce()
    renderArticles()

    fireEvent.click(await screen.findByRole("button", { name: "Save article to collection" }))
    const dialog = screen.getByRole("dialog", { name: "Save to Collection" })
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Research/ }))
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Archive/ }))
    fireEvent.click(within(dialog).getByRole("button", { name: "Apply" }))

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Confirmed memberships were reloaded")
    expect(within(dialog).getByRole("checkbox", { name: /Research/ })).not.toBeChecked()
    expect(within(dialog).getByRole("checkbox", { name: /Archive/ })).not.toBeChecked()
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Archive/ }))
    fireEvent.click(within(dialog).getByRole("button", { name: "Apply" }))

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Save to Collection" })).not.toBeInTheDocument())
    expect(removeArticleFromCollection).toHaveBeenCalledTimes(1)
    expect(saveArticleToCollection).toHaveBeenCalledTimes(2)
  })

  it("creates and selects a trimmed collection inline while preserving the dialog", async () => {
    const createdCollection = collection({ id: secondCollectionId, name: "Reading Queue", articleCount: 0 })
    vi.mocked(getArticleCollections)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([createdCollection])
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    vi.mocked(createArticleCollection)
      .mockRejectedValueOnce(new ApiError(
        "Conflict",
        409,
        JSON.stringify({ detail: "article collection name already exists" }),
      ))
      .mockResolvedValueOnce(createdCollection)
    renderArticles()

    const trigger = await screen.findByRole("button", { name: "Save article to collection" })
    fireEvent.click(trigger)
    const dialog = screen.getByRole("dialog", { name: "Save to Collection" })
    expect(within(dialog).getByText("No collections yet")).toBeInTheDocument()
    const input = within(dialog).getByRole("textbox", { name: "Create a collection" })
    fireEvent.change(input, { target: { value: "Research" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Create" }))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("article collection name already exists")
    fireEvent.change(input, { target: { value: "  Reading Queue  " } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Create" }))

    await waitFor(() => expect(createArticleCollection).toHaveBeenCalledWith("Reading Queue"))
    expect(screen.getByRole("dialog", { name: "Save to Collection" })).toBeInTheDocument()
    expect(await within(dialog).findByRole("checkbox", { name: /Reading Queue.*0 articles/ })).toBeChecked()
  })

  it("drops a collection deleted while the Save dialog is open and keeps confirmed truth", async () => {
    const archive = collection({ id: secondCollectionId, name: "Archive", articleCount: 0 })
    vi.mocked(getArticleCollections)
      .mockResolvedValueOnce([collection(), archive])
      .mockResolvedValueOnce([collection()])
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    vi.mocked(saveArticleToCollection).mockRejectedValue(new ApiError(
      "Not Found",
      404,
      JSON.stringify({ detail: "article collection not found" }),
    ))
    renderArticles()

    fireEvent.click(await screen.findByRole("button", { name: "Save article to collection" }))
    const dialog = screen.getByRole("dialog", { name: "Save to Collection" })
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Archive/ }))
    fireEvent.click(within(dialog).getByRole("button", { name: "Apply" }))

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("article collection not found")
    await waitFor(() => expect(within(dialog).queryByRole("checkbox", { name: /Archive/ })).not.toBeInTheDocument())
    expect(within(dialog).getByRole("checkbox", { name: /Research/ })).not.toBeChecked()
  })

  it("loads and retries collections inside the Save dialog", async () => {
    const first = deferred<ArticleCollection[]>()
    vi.mocked(getArticleCollections)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce([collection()])
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    renderArticles()

    fireEvent.click(await screen.findByRole("button", { name: "Save article to collection" }))
    const dialog = screen.getByRole("dialog", { name: "Save to Collection" })
    expect(within(dialog).getByRole("status", { name: "Loading collections for article" })).toBeInTheDocument()
    first.reject(new Error("collections offline"))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("collections offline")
    fireEvent.click(within(dialog).getByRole("button", { name: "Retry" }))
    expect(await within(dialog).findByRole("checkbox", { name: /Research/ })).toBeInTheDocument()
  })

  it("traps focus and closes the Save dialog with Escape or backdrop", async () => {
    vi.mocked(getArticleCollections).mockResolvedValue([collection()])
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    renderArticles()

    const trigger = await screen.findByRole("button", { name: "Save article to collection" })
    trigger.focus()
    fireEvent.click(trigger)
    let dialog = screen.getByRole("dialog", { name: "Save to Collection" })
    await waitFor(() => expect(within(dialog).getByRole("checkbox", { name: /Research/ })).toHaveFocus())
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())

    fireEvent.click(trigger)
    dialog = screen.getByRole("dialog", { name: "Save to Collection" })
    fireEvent.mouseDown(dialog)
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it("blocks duplicate Apply and closing while a membership mutation is pending", async () => {
    const mutation = deferred<void>()
    vi.mocked(getArticleCollections).mockResolvedValue([collection()])
    vi.mocked(getArticles)
      .mockResolvedValueOnce({ items: [article()], nextCursor: null, resultCount: 1 })
      .mockResolvedValueOnce({
        items: [article({ saved: true, savedCollectionIds: [collectionId] })], nextCursor: null, resultCount: 1,
      })
    vi.mocked(saveArticleToCollection).mockReturnValue(mutation.promise)
    renderArticles()

    fireEvent.click(await screen.findByRole("button", { name: "Save article to collection" }))
    const dialog = screen.getByRole("dialog", { name: "Save to Collection" })
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Research/ }))
    fireEvent.click(within(dialog).getByRole("button", { name: "Apply" }))
    const applying = within(dialog).getByRole("button", { name: "Applying…" })
    expect(applying).toBeDisabled()
    fireEvent.click(applying)
    fireEvent.keyDown(document, { key: "Escape" })
    expect(dialog).toBeInTheDocument()
    expect(saveArticleToCollection).toHaveBeenCalledTimes(1)

    mutation.resolve()
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(saveArticleToCollection).toHaveBeenCalledTimes(1)
  })

  it("opens Collection context actions by pointer and keyboard without affecting All Feed", async () => {
    vi.mocked(getArticleCollections).mockResolvedValue([collection()])
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    renderArticles()

    const allFeed = await screen.findByRole("button", { name: "All articles" })
    const browserMenuEvent = createEvent.contextMenu(allFeed, { clientX: 20, clientY: 20 })
    fireEvent(allFeed, browserMenuEvent)
    expect(browserMenuEvent.defaultPrevented).toBe(false)
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()

    const collectionRow = await screen.findByRole("button", { name: /Research.*3 articles/ })
    const customMenuEvent = createEvent.contextMenu(collectionRow, { clientX: 100, clientY: 80 })
    fireEvent(collectionRow, customMenuEvent)
    expect(customMenuEvent.defaultPrevented).toBe(true)
    let menu = screen.getByRole("menu", { name: "Manage Research" })
    await waitFor(() => expect(within(menu).getByRole("menuitem", { name: "Rename" })).toHaveFocus())
    fireEvent.keyDown(menu, { key: "ArrowDown" })
    expect(within(menu).getByRole("menuitem", { name: "Delete" })).toHaveFocus()
    fireEvent.keyDown(menu, { key: "ArrowDown" })
    expect(within(menu).getByRole("menuitem", { name: "Rename" })).toHaveFocus()
    fireEvent.keyDown(menu, { key: "Escape" })
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
    await waitFor(() => expect(collectionRow).toHaveFocus())

    fireEvent.keyDown(collectionRow, { key: "F10", shiftKey: true })
    menu = screen.getByRole("menu", { name: "Manage Research" })
    await waitFor(() => expect(within(menu).getByRole("menuitem", { name: "Rename" })).toHaveFocus())
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()

    collectionRow.focus()
    fireEvent.keyDown(collectionRow, { key: "ContextMenu" })
    menu = screen.getByRole("menu", { name: "Manage Research" })
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Rename" }))
    const dialog = screen.getByRole("dialog", { name: "Rename Collection" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(collectionRow).toHaveFocus())
  })

  it("renames a collection with validation, reconciliation, URL preservation, and focus restoration", async () => {
    setSearch(`language=en&collection_id=${collectionId}&sort=score`)
    const renamed = collection({ name: "Archive" })
    vi.mocked(getArticleCollections)
      .mockResolvedValueOnce([collection()])
      .mockResolvedValueOnce([renamed])
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    vi.mocked(renameArticleCollection).mockResolvedValue(renamed)
    renderArticles()

    const manage = await screen.findByRole("button", { name: /Research.*3 articles/ })
    manage.focus()
    fireEvent.contextMenu(manage, { clientX: 120, clientY: 90 })
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }))
    const dialog = screen.getByRole("dialog", { name: "Rename Collection" })
    const input = within(dialog).getByRole("textbox", { name: "Collection name" })
    await waitFor(() => expect(input).toHaveFocus())
    expect(input).toHaveValue("Research")
    expect(within(dialog).getByRole("button", { name: "Rename" })).toBeDisabled()
    fireEvent.change(input, { target: { value: "  Archive  " } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Rename" }))

    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(renameArticleCollection).toHaveBeenCalledWith(collectionId, "Archive")
    expect(screen.getByRole("button", { name: /Archive.*3 articles/ })).toHaveAttribute("aria-current", "page")
    expect(navigation.search).toBe(`language=en&collection_id=${collectionId}&sort=score`)
    await waitFor(() => expect(document.activeElement).toHaveAccessibleName(/Archive.*3 articles/))
    expect(screen.getByText("Collection renamed to Archive.")).toBeInTheDocument()
  })

  it("keeps the rename dialog open for duplicate-name errors and prevents duplicate submission", async () => {
    const rename = deferred<ArticleCollection>()
    vi.mocked(getArticleCollections).mockResolvedValue([collection()])
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    vi.mocked(renameArticleCollection)
      .mockReturnValueOnce(rename.promise)
      .mockRejectedValueOnce(new ApiError(
        "Conflict", 409, JSON.stringify({ detail: "article collection name already exists" }),
      ))
    renderArticles()

    const manage = await screen.findByRole("button", { name: /Research.*3 articles/ })
    fireEvent.contextMenu(manage, { clientX: 120, clientY: 90 })
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }))
    const dialog = screen.getByRole("dialog", { name: "Rename Collection" })
    const input = within(dialog).getByRole("textbox", { name: "Collection name" })
    fireEvent.change(input, { target: { value: "Archive" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "Rename" }))
    expect(within(dialog).getByRole("button", { name: "Renaming…" })).toBeDisabled()
    fireEvent.click(within(dialog).getByRole("button", { name: "Renaming…" }))
    expect(renameArticleCollection).toHaveBeenCalledTimes(1)
    rename.reject(new ApiError(
      "Conflict", 409, JSON.stringify({ detail: "article collection name already exists" }),
    ))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("article collection name already exists")
    expect(dialog).toBeInTheDocument()
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    await waitFor(() => expect(manage).toHaveFocus())
  })

  it("deletes a non-selected empty collection after explicit confirmation and preserves selection", async () => {
    setSearch(`language=en&collection_id=${collectionId}&sort=score`)
    const empty = collection({ id: secondCollectionId, name: "Empty", articleCount: 0 })
    vi.mocked(getArticleCollections)
      .mockResolvedValueOnce([collection(), empty])
      .mockResolvedValueOnce([collection()])
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    renderArticles()

    fireEvent.contextMenu(await screen.findByRole("button", { name: /Empty.*0 articles/ }), { clientX: 120, clientY: 90 })
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }))
    const dialog = screen.getByRole("dialog", { name: "Delete Collection?" })
    expect(dialog).toHaveTextContent("Empty contains 0 saved articles")
    expect(dialog).toHaveTextContent("Articles themselves are not deleted from NewsCraft")
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Collection" }))

    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(deleteArticleCollection).toHaveBeenCalledWith(secondCollectionId)
    expect(navigation.search).toBe(`language=en&collection_id=${collectionId}&sort=score`)
    expect(screen.getByRole("button", { name: /Research.*3 articles/ })).toHaveAttribute("aria-current", "page")
    expect(screen.queryByText("Empty")).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole("button", { name: "All articles" })).toHaveFocus())
  })

  it("keeps delete confirmation open after failure and prevents duplicate submission", async () => {
    const deletion = deferred<void>()
    const empty = collection({ id: secondCollectionId, name: "Empty", articleCount: 0 })
    vi.mocked(getArticleCollections)
      .mockResolvedValueOnce([collection(), empty])
      .mockResolvedValueOnce([collection()])
    vi.mocked(getArticles).mockResolvedValue({ items: [article()], nextCursor: null, resultCount: 1 })
    vi.mocked(deleteArticleCollection)
      .mockReturnValueOnce(deletion.promise)
      .mockResolvedValueOnce()
    renderArticles()

    fireEvent.contextMenu(await screen.findByRole("button", { name: /Empty.*0 articles/ }), { clientX: 120, clientY: 90 })
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }))
    const dialog = screen.getByRole("dialog", { name: "Delete Collection?" })
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Collection" }))
    const deleting = within(dialog).getByRole("button", { name: "Deleting…" })
    expect(deleting).toBeDisabled()
    fireEvent.click(deleting)
    expect(deleteArticleCollection).toHaveBeenCalledTimes(1)

    deletion.reject(new ApiError("Unavailable", 503, JSON.stringify({ detail: "temporary delete failure" })))
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("temporary delete failure")
    expect(dialog).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Collection" }))

    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(deleteArticleCollection).toHaveBeenCalledTimes(2)
    expect(screen.queryByText("Empty")).not.toBeInTheDocument()
  })

  it("deletes the selected collection, removes only collection URL state, and returns to All Feed", async () => {
    setSearch(`language=en&collection_id=${collectionId}&sort=score&cursor=old`)
    vi.mocked(getArticleCollections)
      .mockResolvedValueOnce([collection({ articleCount: 1 })])
      .mockResolvedValueOnce([])
    vi.mocked(getArticles)
      .mockResolvedValueOnce({ items: [article()], nextCursor: null, resultCount: 1 })
      .mockResolvedValueOnce({ items: [article()], nextCursor: null, resultCount: 1 })
    renderArticles()

    fireEvent.contextMenu(await screen.findByRole("button", { name: /Research.*1 article/ }), { clientX: 120, clientY: 90 })
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }))
    const dialog = screen.getByRole("dialog", { name: "Delete Collection?" })
    expect(dialog).toHaveTextContent("Research contains 1 saved article")
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Collection" }))

    await waitFor(() => expect(navigation.push).toHaveBeenLastCalledWith("/feed?language=en&sort=score"))
    expect(screen.getByRole("button", { name: "All articles" })).toHaveAttribute("aria-current", "page")
    expect(await screen.findByRole("article")).toBeInTheDocument()
    expect(screen.getByText("Collection Research deleted. Articles remain in NewsCraft.")).toBeInTheDocument()
  })

  it("directly removes only the current membership and reconciles the last-card empty state", async () => {
    setSearch(`language=en&collection_id=${collectionId}&sort=score`)
    const otherId = secondCollectionId
    vi.mocked(getArticleCollections)
      .mockResolvedValueOnce([collection({ articleCount: 1 }), collection({ id: otherId, name: "Archive", articleCount: 1 })])
      .mockResolvedValueOnce([collection({ articleCount: 0 }), collection({ id: otherId, name: "Archive", articleCount: 1 })])
    vi.mocked(getArticles)
      .mockResolvedValueOnce({
        items: [article({ saved: true, savedCollectionIds: [collectionId, otherId] })], nextCursor: null, resultCount: 1,
      })
      .mockResolvedValueOnce({ items: [], nextCursor: null, resultCount: 0 })
    renderArticles()

    const remove = await screen.findByRole("button", { name: "Remove article from Research" })
    fireEvent.click(remove)
    expect(screen.queryByRole("dialog", { name: "Save to Collection" })).not.toBeInTheDocument()
    await waitFor(() => expect(removeArticleFromCollection).toHaveBeenCalledWith(collectionId, "article"))
    expect(removeArticleFromCollection).toHaveBeenCalledTimes(1)
    expect(await screen.findByText("Research is empty")).toBeInTheDocument()
    expect(screen.getByText("0 articles · source monitoring and saved collections")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Research.*0 articles/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Archive.*1 article/ })).toBeInTheDocument()
    expect(navigation.search).toBe(`language=en&collection_id=${collectionId}&sort=score`)
    expect(screen.getByText("Article removed from Research.")).toBeInTheDocument()
  })

  it("keeps a card visible after direct-removal failure and exposes a retry", async () => {
    setSearch(`collection_id=${collectionId}`)
    const savedArticle = article({ saved: true, savedCollectionIds: [collectionId] })
    vi.mocked(getArticleCollections)
      .mockResolvedValueOnce([collection({ articleCount: 1 })])
      .mockResolvedValueOnce([collection({ articleCount: 1 })])
      .mockResolvedValueOnce([collection({ articleCount: 0 })])
    vi.mocked(getArticles)
      .mockResolvedValueOnce({ items: [savedArticle], nextCursor: null, resultCount: 1 })
      .mockResolvedValueOnce({ items: [savedArticle], nextCursor: null, resultCount: 1 })
      .mockResolvedValueOnce({ items: [], nextCursor: null, resultCount: 0 })
    vi.mocked(removeArticleFromCollection)
      .mockRejectedValueOnce(new ApiError("Offline", 503, JSON.stringify({ detail: "temporary removal failure" })))
      .mockResolvedValueOnce()
    renderArticles()

    fireEvent.click(await screen.findByRole("button", { name: "Remove article from Research" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("temporary removal failure")
    expect(screen.getByRole("article")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Retry removal" }))
    expect(await screen.findByText("Research is empty")).toBeInTheDocument()
    expect(removeArticleFromCollection).toHaveBeenCalledTimes(2)
  })
})

function renderArticles() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ArticlesPage />
    </QueryClientProvider>,
  )
}

async function findEnabledClearFeedButton() {
  // The trigger stays disabled until the Feed count query settles, as the desktop e2e run asserts.
  const button = await screen.findByRole("button", { name: "Clear Feed" })
  await waitFor(() => expect(button).toBeEnabled())
  return button
}

function article(overrides: Partial<ArticleSummary> = {}): ArticleSummary {
  return {
    id: "article",
    title: "Article title",
    summary: "Article summary",
    excerpt: null,
    source: { id: null, name: "Wire", platform: "rss", homepageUrl: null },
    canonicalUrl: "https://example.com/article",
    publishedAt: "2026-07-21T08:00:00Z",
    sortAt: "2026-07-21T08:01:00Z",
    displayAt: "2026-07-21T08:00:00Z",
    dateBasis: "published",
    score: 64,
    contentType: "news",
    topic: "AI",
    domain: "example.com",
    language: "en",
    direction: "ltr",
    coverage: { state: "complete", stories: [] },
    articleReadiness: { ready: true },
    image: null,
    hasImage: false,
    saved: false,
    savedCollectionIds: [],
    ...overrides,
  }
}

function articleDetail(overrides: Partial<ArticleDetail> = {}): ArticleDetail {
  return {
    ...article(),
    articleReadiness: { ready: true, reason: "Ready for rewrite", blockers: [] },
    contentText: "Complete normalized article body.",
    contentOrigin: "source_provided",
    sanitizedHtml: null,
    authors: ["Reporter"],
    tags: ["AI"],
    media: [],
    storyLinks: [],
    evidenceReferences: [],
    advanced: {
      itemType: "article",
      status: "new",
      rewriteBucket: "technical_article",
      classificationReasons: [],
      sourceTier: "A",
      freshnessBucket: "fresh",
      qualityStatus: "good",
      titleQuality: "meaningful",
      titleWasGenerated: false,
      contentIntent: null,
      duplicateOfId: null,
      dateSource: "source",
      dateParseStatus: "parsed",
      createdAt: "2026-07-21T08:01:00Z",
      updatedAt: "2026-07-21T08:01:00Z",
      rawClassification: { contentType: "news", topic: "AI", language: "en" },
    },
    ...overrides,
  }
}

function image() {
  return {
    id: "image",
    url: "https://media.example/image.jpg",
    kind: "image" as const,
    width: 1200,
    height: 675,
    altText: "Editorial image",
    fetchStatus: "remote_only",
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

const sourceA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
const sourceB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

function facets() {
  return {
    languages: [{ value: "en", count: 3 }, { value: "fa", count: 1 }],
    topics: [{ value: "AI", count: 2 }, { value: "Tech", count: 1 }],
    contentTypes: [{ value: "news", count: 3 }],
    sources: [
      { id: sourceA, name: "Alpha Wire", platform: "rss", count: 2 },
      { id: sourceB, name: "Beta Wire", platform: "telegram_public", count: 1 },
    ],
    coverage: [
      { value: "complete" as const, count: 1 },
      { value: "incomplete" as const, count: 1 },
      { value: "ungrouped" as const, count: 1 },
    ],
  }
}

function emptyFilters() {
  return {
    languages: [], topics: [], contentTypes: [], sourceIds: [], coverage: [], hasImage: null,
    scoreMin: null, scoreMax: null, dateFrom: null, dateTo: null,
  }
}

const collectionId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
const secondCollectionId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

function collection(overrides: Partial<ArticleCollection> = {}): ArticleCollection {
  return {
    id: collectionId,
    name: "Research",
    articleCount: 3,
    createdAt: "2026-07-21T08:00:00Z",
    updatedAt: "2026-07-21T08:00:00Z",
    ...overrides,
  }
}

function setSearch(search: string) {
  window.history.replaceState(null, "", `/feed${search ? `?${search}` : ""}`)
  navigation.search = search
  navigation.listeners.forEach((listener) => listener())
}
