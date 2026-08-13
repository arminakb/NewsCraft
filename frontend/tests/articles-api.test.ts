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
import { EMPTY_ARTICLE_FILTERS } from "@/features/articles/filter-state"
import { DEFAULT_TIME_ZONE, zonedLocalDateTimeToUtc } from "@/lib/date-time"

const articleId = "11111111-1111-4111-8111-111111111111"

function emptyFilters() {
  return { ...EMPTY_ARTICLE_FILTERS }
}

describe("Articles API", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("requests only Articles endpoint with sort, limit, and cursor", async () => {
    const request = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(articlePage()), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    )
    vi.stubGlobal("fetch", request)

    await getArticles({ sort: "score", cursor: "cursor/value", limit: 25 })

    expect(request).toHaveBeenCalledWith(
      "/api/backend/articles?sort=score&limit=25&cursor=cursor%2Fvalue",
      undefined,
    )
  })

  it("forwards request cancellation when supplied", async () => {
    const request = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(articlePage()), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    )
    vi.stubGlobal("fetch", request)
    const controller = new AbortController()

    await getArticles({ sort: "newest" }, controller.signal)

    expect(request).toHaveBeenCalledWith(
      "/api/backend/articles?sort=newest&limit=50",
      { signal: controller.signal },
    )
  })

  it("loads one article detail lazily and maps content provenance", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: articleId,
      content_text: "Complete normalized article body.",
      content_origin: "source_provided",
    }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }))
    vi.stubGlobal("fetch", request)

    await expect(getArticle(articleId)).resolves.toMatchObject({
      id: articleId,
      contentText: "Complete normalized article body.",
      contentOrigin: "source_provided",
    })
    expect(request).toHaveBeenCalledWith(`/api/backend/articles/${articleId}`, undefined)
  })

  it("serializes title search with collection and cursor state", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(articlePage()), {
      status: 200, headers: { "content-type": "application/json" },
    }))
    vi.stubGlobal("fetch", request)

    await getArticles({
      sort: "newest",
      query: "گزارش فناوری",
      collectionId,
      cursor: "page-2",
      limit: 50,
    })

    expect(request).toHaveBeenCalledWith(
      `/api/backend/articles?sort=newest&limit=50&q=${new URLSearchParams({ q: "گزارش فناوری" }).toString().slice(2)}&collection_id=${collectionId}&cursor=page-2`,
      undefined,
    )
  })

  it("serializes collection selection with cursor pagination", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(articlePage()), {
      status: 200, headers: { "content-type": "application/json" },
    }))
    vi.stubGlobal("fetch", request)
    await getArticles({ sort: "newest", collectionId, cursor: "page-2", limit: 50 })
    expect(request).toHaveBeenCalledWith(
      `/api/backend/articles?sort=newest&limit=50&collection_id=${collectionId}&cursor=page-2`,
      undefined,
    )
  })

  it("serializes repeated and bounded filters for server-side filtering", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(articlePage()), {
      status: 200, headers: { "content-type": "application/json" },
    }))
    vi.stubGlobal("fetch", request)
    await getArticles({
      sort: "newest",
      filters: {
        languages: ["en"], topics: ["AI", "Tech"], contentTypes: ["news"],
        sourceIds: ["22222222-2222-4222-8222-222222222222"], coverage: ["complete", "ungrouped"],
        hasImage: true, scoreMin: 20, scoreMax: 80, dateFrom: "2026-07-01", dateTo: "2026-07-21",
      },
      limit: 50,
      timezone: "UTC",
    })
    expect(request).toHaveBeenCalledWith(
      "/api/backend/articles?sort=newest&limit=50&language=en&topic=AI&topic=Tech&content_type=news&source_id=22222222-2222-4222-8222-222222222222&coverage=complete&coverage=ungrouped&has_image=true&score_min=20&score_max=80&date_from=2026-07-01T00%3A00%3A00.000Z&date_to=2026-07-22T00%3A00%3A00.000Z",
      undefined,
    )
  })

  it("resolves calendar date bounds in the configured display timezone", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(articlePage()), {
      status: 200, headers: { "content-type": "application/json" },
    }))
    vi.stubGlobal("fetch", request)
    await getArticles({
      sort: "newest",
      filters: { ...emptyFilters(), dateFrom: "2026-07-01", dateTo: "2026-07-21" },
      limit: 50,
      timezone: "Asia/Tehran",
    })

    const url = new URL(String(vi.mocked(request).mock.calls[0]?.[0]), "https://newscraft.test")
    expect(url.searchParams.get("date_from")).toBe("2026-06-30T20:30:00.000Z")
    expect(url.searchParams.get("date_to")).toBe("2026-07-21T20:30:00.000Z")
  })

  it("defaults date bounds to the default display timezone when none is supplied", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(articlePage()), {
      status: 200, headers: { "content-type": "application/json" },
    }))
    vi.stubGlobal("fetch", request)
    await getArticles({
      sort: "newest",
      filters: { ...emptyFilters(), dateFrom: "2026-07-01", dateTo: "2026-07-01" },
      limit: 50,
    })

    const url = new URL(String(vi.mocked(request).mock.calls[0]?.[0]), "https://newscraft.test")
    const expectedFrom = zonedLocalDateTimeToUtc("2026-07-01T00:00", DEFAULT_TIME_ZONE)
    const expectedTo = zonedLocalDateTimeToUtc("2026-07-02T00:00", DEFAULT_TIME_ZONE)
    expect(url.searchParams.get("date_from")).toBe(expectedFrom)
    expect(url.searchParams.get("date_to")).toBe(expectedTo)
    expect(expectedFrom).not.toBe("2026-07-01T00:00:00.000Z")
  })

  it("crosses a daylight-saving boundary on the day the offset changes", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(articlePage()), {
      status: 200, headers: { "content-type": "application/json" },
    }))
    vi.stubGlobal("fetch", request)
    await getArticles({
      sort: "newest",
      filters: { ...emptyFilters(), dateFrom: "2026-03-07", dateTo: "2026-03-08" },
      limit: 50,
      timezone: "America/New_York",
    })

    const url = new URL(String(vi.mocked(request).mock.calls[0]?.[0]), "https://newscraft.test")
    expect(url.searchParams.get("date_from")).toBe("2026-03-07T05:00:00.000Z")
    expect(url.searchParams.get("date_to")).toBe("2026-03-09T04:00:00.000Z")
  })

  it("fetches and maps facet values", async () => {
    const payload = facetPayload()
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
      status: 200, headers: { "content-type": "application/json" },
    }))
    vi.stubGlobal("fetch", request)
    await expect(getArticleFacets()).resolves.toEqual({
      languages: [{ value: "en", count: 2 }], topics: [{ value: "AI", count: 1 }],
      contentTypes: [{ value: "news", count: 2 }],
      sources: [{ id: "22222222-2222-4222-8222-222222222222", name: "Wire Desk", platform: "rss", count: 2 }],
      coverage: [{ value: "complete", count: 1 }],
    })
    expect(request).toHaveBeenCalledWith("/api/backend/articles/facets", undefined)
  })

  it("loads the Feed summary and clears it through the dedicated endpoint", async () => {
    const request = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ article_count: 7 }), {
        status: 200, headers: { "content-type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ cleared_count: 7 }), {
        status: 200, headers: { "content-type": "application/json" },
      }))
    vi.stubGlobal("fetch", request)

    await expect(getFeedSummary()).resolves.toEqual({ articleCount: 7 })
    await expect(clearFeed()).resolves.toEqual({ clearedCount: 7 })
    expect(request).toHaveBeenNthCalledWith(1, "/api/backend/feed/summary", undefined)
    expect(request).toHaveBeenNthCalledWith(2, "/api/backend/feed/clear", { method: "POST" })
  })

  it("lists and creates article collections", async () => {
    const payload = collectionPayload()
    const request = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([payload]), {
        status: 200, headers: { "content-type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(payload), {
        status: 201, headers: { "content-type": "application/json" },
      }))
    vi.stubGlobal("fetch", request)

    await expect(getArticleCollections()).resolves.toEqual([{
      id: collectionId,
      name: "Research",
      articleCount: 3,
      createdAt: "2026-07-21T08:00:00Z",
      updatedAt: "2026-07-21T09:00:00Z",
    }])
    await expect(createArticleCollection("Research")).resolves.toMatchObject({ id: collectionId, name: "Research" })
    expect(request).toHaveBeenNthCalledWith(1, "/api/backend/article-collections", undefined)
    expect(request).toHaveBeenNthCalledWith(2, "/api/backend/article-collections", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "Research" }),
    })
  })

  it("adds and removes collection membership through idempotent 204 endpoints", async () => {
    const request = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", request)

    await saveArticleToCollection(collectionId, articleId)
    await removeArticleFromCollection(collectionId, articleId)

    expect(request).toHaveBeenNthCalledWith(
      1,
      `/api/backend/article-collections/${collectionId}/articles/${articleId}`,
      { method: "PUT" },
    )
    expect(request).toHaveBeenNthCalledWith(
      2,
      `/api/backend/article-collections/${collectionId}/articles/${articleId}`,
      { method: "DELETE" },
    )
  })

  it("renames and deletes collections through existing management endpoints", async () => {
    const payload = { ...collectionPayload(), name: "Archive" }
    const request = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(payload), {
        status: 200, headers: { "content-type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", request)

    await expect(renameArticleCollection(collectionId, "Archive")).resolves.toMatchObject({ name: "Archive" })
    await deleteArticleCollection(collectionId)

    expect(request).toHaveBeenNthCalledWith(1, `/api/backend/article-collections/${collectionId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "Archive" }),
    })
    expect(request).toHaveBeenNthCalledWith(2, `/api/backend/article-collections/${collectionId}`, {
      method: "DELETE",
    })
  })
})

const collectionId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

function collectionPayload() {
  return {
    id: collectionId,
    name: "Research",
    article_count: 3,
    created_at: "2026-07-21T08:00:00Z",
    updated_at: "2026-07-21T09:00:00Z",
  }
}

function facetPayload() {
  return {
    languages: [{ value: "en", count: 2 }],
    topics: [{ value: "AI", count: 1 }],
    content_types: [{ value: "news", count: 2 }],
    sources: [{ id: "22222222-2222-4222-8222-222222222222", name: "Wire Desk", platform: "rss", count: 2 }],
    coverage: [{ value: "complete", count: 1 }],
  }
}

function articlePage() {
  return {
    items: [{
      id: articleId,
      title: "Editorial report",
      summary: "Short summary",
      excerpt: null,
      source: {
        id: "22222222-2222-4222-8222-222222222222",
        name: "Wire Desk",
        platform: "rss",
        homepage_url: "https://wire.example",
      },
      canonical_url: "https://wire.example/report",
      published_at: "2026-07-21T08:00:00Z",
      sort_at: "2026-07-21T08:01:00Z",
      display_at: "2026-07-21T08:00:00Z",
      date_basis: "published",
      score: 72,
      content_type: "news",
      topic: "AI",
      domain: "wire.example",
      language: "en",
      direction: "ltr",
      coverage: {
        state: "complete",
        stories: [{
          id: "33333333-3333-4333-8333-333333333333",
          title: "Story",
          editorial_state: "inbox",
          complete: true,
          score: 100,
        }],
      },
      article_readiness: { ready: true },
      image: {
        id: "44444444-4444-4444-8444-444444444444",
        url: "https://media.example/image.jpg",
        kind: "image",
        width: 1200,
        height: 675,
        alt_text: "Newsroom",
        fetch_status: "remote_only",
      },
      has_image: true,
      saved: false,
      saved_collection_ids: [],
    }],
    next_cursor: "next-page",
    result_count: 12,
  }
}
