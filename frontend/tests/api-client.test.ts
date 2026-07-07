import {
  ApiError,
  approveContentItem,
  getContentItems,
  getDashboardSnapshot,
  getDiagnostics,
  getSources,
  runIngest,
  seedSources,
} from "@/lib/api-client"

describe("api-client", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("maps GET /sources to dashboard source summaries", async () => {
    stubFetch([{ id: "source-1", platform: "rss", name: "OpenAI", feed_url: "https://example.com/rss" }])

    await expect(getSources()).resolves.toEqual([
      expect.objectContaining({
        id: "source-1",
        platform: "rss",
        name: "OpenAI",
        status: "healthy",
      }),
    ])
  })

  it("maps POST /sources/seed response", async () => {
    stubFetch({ upserted: 50 })

    await expect(seedSources()).resolves.toEqual({ upserted: 50 })
  })

  it("maps GET /diagnostics response", async () => {
    stubFetch({
      status: "ok",
      checks: { database: "ok", sources: "ok" },
      source_health: { healthy: 3, partial: 1, failed: 0, unknown: 2 },
      problem_sources: [{ id: "source-1", name: "Reuters", status: "partial" }],
    })

    await expect(getDiagnostics()).resolves.toEqual(
      expect.objectContaining({
        status: "ok",
        checks: { database: "ok", sources: "ok" },
        sourceHealth: { healthy: 3, partial: 1, failed: 0, unknown: 2 },
        problemSources: [expect.objectContaining({ id: "source-1", name: "Reuters", status: "partial" })],
      })
    )
  })

  it("sends run ingest payload", async () => {
    const fetchSpy = stubFetch({ status: "succeeded", items: 12 })

    await runIngest({ platforms: ["rss"], source_ids: ["source-1"] })

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/ingest/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ platforms: ["rss"], source_ids: ["source-1"] }),
      })
    )
  })

  it("sends approve content item payload", async () => {
    const fetchSpy = stubFetch({ id: "item-1", status: "approved", metrics: { approval_notes: "ready" } })

    await approveContentItem("item-1", { notes: "ready" })

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/content-items/item-1/approve",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ notes: "ready" }),
      })
    )
  })

  it("maps GET /content-items to queue items", async () => {
    stubFetch([
      {
        id: "item-1",
        title: "AI Story",
        language_code: "en",
        status: "new",
        sort_at: "2026-07-06T08:00:00Z",
        primary_media: { normalized_url: "https://example.com/image.jpg" },
      },
    ])

    await expect(getContentItems()).resolves.toEqual([
      expect.objectContaining({
        id: "item-1",
        title: "AI Story",
        language: "en",
        status: "new",
      }),
    ])
  })

  it("maps content intelligence fields from GET /content-items", async () => {
    stubFetch([
      {
        id: "item-2",
        title: "Deep AI Story",
        summary: "Long-form source summary",
        canonical_url: "https://example.com/deep-ai",
        language_code: "en",
        status: "approved",
        score: 87,
        tags: ["ai", "chips"],
        sort_at: "2026-07-06T08:00:00Z",
        primary_media: {
          normalized_url: "https://example.com/deep-ai.jpg",
          media_quality: "high",
          fetch_status: "downloaded",
        },
        metrics: { classification: { category: "AI Infrastructure" } },
        content_type: "article",
        rewrite_bucket: "ready",
        is_rewrite_ready: true,
        rewrite_ready_reason: "has summary and image",
        rewrite_blockers: ["needs Persian angle"],
        classification_reasons: ["AI infrastructure topic"],
        source_tier: "tier_1",
        freshness_bucket: "breaking",
        quality_status: "strong",
        score_breakdown: { media: 12, source: 25 },
      },
    ])

    await expect(getContentItems()).resolves.toEqual([
      expect.objectContaining({
        id: "item-2",
        title: "Deep AI Story",
        summary: "Long-form source summary",
        canonicalUrl: "https://example.com/deep-ai",
        score: 87,
        tags: ["ai", "chips"],
        status: "approved",
        category: "AI Infrastructure",
        contentType: "article",
        rewriteBucket: "ready",
        isRewriteReady: true,
        rewriteReadyReason: "has summary and image",
        rewriteBlockers: ["needs Persian angle"],
        classificationReasons: ["AI infrastructure topic"],
        sourceTier: "tier_1",
        freshnessBucket: "breaking",
        qualityStatus: "strong",
        scoreBreakdown: { media: 12, source: 25 },
        primaryMedia: expect.objectContaining({
          src: "https://example.com/deep-ai.jpg",
          quality: "high",
          fetchStatus: "downloaded",
        }),
      }),
    ])
  })

  it("sends content item filter query params", async () => {
    const fetchSpy = stubFetch([])

    await getContentItems({ status: "approved", sort: "score", limit: 25, isRewriteReady: true })

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/content-items?limit=25&status=approved&is_rewrite_ready=true&sort=score",
      undefined
    )
  })

  it("uses backend dashboard summary counts without replacing zeroes with mock data", async () => {
    const fetchSpy = vi.fn((url: string) => {
      const payloads: Record<string, unknown> = {
        "/api/backend/dashboard/summary": {
          rss_feeds: 0,
          telegram_channels: 0,
          content_items: 0,
          media_assets: 0,
          warnings: 0,
        },
        "/api/backend/sources": [],
        "/api/backend/content-items?limit=50": [],
        "/api/backend/ingest/runs": [],
        "/api/backend/media-assets": [],
      }

      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        json: async () => payloads[url],
        text: async () => JSON.stringify(payloads[url]),
      })
    })
    vi.stubGlobal("fetch", fetchSpy)

    await expect(getDashboardSnapshot()).resolves.toEqual(
      expect.objectContaining({
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
      })
    )
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/dashboard/summary", undefined)
  })

  it("throws typed ApiError on network failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        text: async () => "offline",
      })
    )

    await expect(getSources()).rejects.toBeInstanceOf(ApiError)
  })
})

function stubFetch(payload: unknown) {
  const fetchSpy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  })
  vi.stubGlobal("fetch", fetchSpy)
  return fetchSpy
}
