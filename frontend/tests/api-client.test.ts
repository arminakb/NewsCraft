import {
  ApiError,
  approveContentItem,
  getContentItem,
  getContentItems,
  getDashboardSnapshot,
  getDiagnostics,
  getIngestRuns,
  getMediaAssets,
  getSource,
  getSources,
  runIngest,
  seedSources,
} from "@/lib/api-client"

describe("api-client", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("maps GET /sources to dashboard source summaries", async () => {
    stubFetch([{ id: "source-1", platform: "rss", name: "OpenAI", feed_url: "https://example.com/rss" }])

    await expect(getSources()).resolves.toEqual([
      expect.objectContaining({
        id: "source-1",
        platform: "rss",
        name: "OpenAI",
        status: "unknown",
      }),
    ])
  })

  it("keeps missing source health unknown while honoring disabled and failure-count states", async () => {
    stubFetch([
      { id: "absent", platform: "rss", name: "Absent", feed_url: "https://example.com/absent.xml" },
      { id: "null", platform: "rss", name: "Null", feed_url: "https://example.com/null.xml", health_status: null },
      { id: "inactive", platform: "rss", name: "Inactive", feed_url: "https://example.com/inactive.xml", active: false },
      { id: "one-failure", platform: "rss", name: "One failure", feed_url: "https://example.com/one.xml", failure_count: 1 },
      { id: "five-failures", platform: "rss", name: "Five failures", feed_url: "https://example.com/five.xml", failure_count: 5 },
    ])

    await expect(getSources()).resolves.toEqual([
      expect.objectContaining({ id: "absent", status: "unknown" }),
      expect.objectContaining({ id: "null", status: "unknown" }),
      expect.objectContaining({ id: "inactive", status: "disabled" }),
      expect.objectContaining({ id: "one-failure", status: "degraded" }),
      expect.objectContaining({ id: "five-failures", status: "broken" }),
    ])
  })

  it.each([
    ["rss", "rss"],
    ["atom", "atom"],
    ["telegram_public", "telegram_public"],
    ["google_news", "google_news"],
    ["gdelt", "gdelt"],
    ["hackernews", "hackernews"],
    ["unsupported-platform", "unknown"],
  ])("maps source platform %s to %s without relabeling it", async (platform, expected) => {
    stubFetch([{ id: `source-${platform}`, platform, name: platform, feed_url: "https://example.com/source" }])

    const [source] = await getSources()

    expect(source.platform).toBe(expected)
  })

  it("does not invent parser or deduplication metadata for sources", async () => {
    stubFetch([{ id: "source-1", platform: "rss", name: "Feed", feed_url: "https://example.com/rss" }])

    const [source] = await getSources()

    expect(source).not.toHaveProperty("parser")
    expect(source).not.toHaveProperty("deduplication")
  })

  it("does not invent a next run before the scheduler exists", async () => {
    stubFetch([
      {
        id: "source-1",
        platform: "rss",
        name: "Feed",
        feed_url: "https://example.com/rss",
        fetch_interval_minutes: 1440,
      },
    ])

    const [source] = await getSources()

    expect(source).toEqual(expect.objectContaining({ fetchIntervalMinutes: 1440 }))
    expect(source).not.toHaveProperty("nextRun")
  })

  it("retains the calendar date when formatting a source last success", async () => {
    stubFetch([
      {
        id: "source-1",
        platform: "rss",
        name: "Feed",
        feed_url: "https://example.com/rss",
        last_success_at: "2026-07-11T08:00:00Z",
      },
    ])

    const [source] = await getSources()

    expect(source.lastSuccess).toContain("2026-07-11")
  })

  it("maps backend source health statuses without compressing them", async () => {
    stubFetch([
      { id: "healthy", platform: "rss", name: "Healthy", feed_url: "https://example.com/healthy.xml", health_status: "healthy" },
      { id: "degraded", platform: "rss", name: "Degraded", feed_url: "https://example.com/degraded.xml", health_status: "degraded" },
      { id: "broken", platform: "rss", name: "Broken", feed_url: "https://example.com/broken.xml", health_status: "broken" },
      { id: "disabled", platform: "rss", name: "Disabled", feed_url: "https://example.com/disabled.xml", health_status: "disabled" },
      { id: "unknown", platform: "rss", name: "Unknown", feed_url: "https://example.com/unknown.xml", health_status: "unknown" },
    ])

    await expect(getSources()).resolves.toEqual([
      expect.objectContaining({ id: "healthy", status: "healthy" }),
      expect.objectContaining({ id: "degraded", status: "degraded" }),
      expect.objectContaining({ id: "broken", status: "broken" }),
      expect.objectContaining({ id: "disabled", status: "disabled" }),
      expect.objectContaining({ id: "unknown", status: "unknown" }),
    ])
  })

  it("maps GET /sources/{id} to source details", async () => {
    const fetchSpy = stubFetch({ id: "source-1", platform: "telegram_public", name: "DW Persian", telegram_username: "dw_farsi" })

    await expect(getSource("source-1")).resolves.toEqual(
      expect.objectContaining({
        id: "source-1",
        platform: "telegram_public",
        name: "DW Persian",
        url: "https://t.me/dw_farsi",
      })
    )
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/sources/source-1", undefined)
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

  it("uses the typed ingest client with a generated request UUID", async () => {
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn(() => "44444444-4444-4444-8444-444444444444"),
    })
    const fetchSpy = stubFetch({ job_id: "job-1", status: "queued", deduplicated: false })

    await runIngest({ platforms: ["rss"], source_ids: ["source-1"] })

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/ingest/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          request_id: "44444444-4444-4444-8444-444444444444",
          platforms: ["rss"],
          source_ids: ["source-1"],
        }),
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

  it("maps real source provenance and complete content without inventing RSS", async () => {
    stubFetch([
      {
        id: "item-telegram-42",
        item_type: "telegram_post",
        title: "Source post",
        summary: "Short summary",
        content_text: "Complete source post body",
        canonical_url: "https://t.me/source/42",
        language_code: "fa",
        direction: "rtl",
        authors: ["Source Channel"],
        published_at: "2026-07-11T08:00:00Z",
        status: "new",
        sort_at: "2026-07-11T08:00:00Z",
        classification_metadata: {
          source_name: "Source Channel",
          source_platform: "telegram_public",
        },
      },
    ])

    await expect(getContentItems()).resolves.toEqual([
      expect.objectContaining({
        sourceName: "Source Channel",
        sourcePlatform: "telegram_public",
        contentText: "Complete source post body",
        direction: "rtl",
        authors: ["Source Channel"],
        publishedAt: "2026-07-11T08:00:00Z",
      }),
    ])
  })

  it("uses an ingestion run's actual formatted date", async () => {
    stubFetch([
      {
        id: "run-1",
        started_at: "2026-07-11T08:00:00Z",
        finished_at: "2026-07-11T08:01:00Z",
        status: "succeeded",
        trigger: "manual",
      },
    ])

    const [run] = await getIngestRuns()

    expect(run.label).toContain("2026-07-11")
    expect(run.label).not.toMatch(/^Today/)
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

  it("maps GET /content-items/{id} to content details", async () => {
    const fetchSpy = stubFetch({
      id: "item-2",
      title: "Deep AI Story",
      summary: "Long-form source summary",
      canonical_url: "https://example.com/deep-ai",
      language_code: "en",
      status: "new",
      score: 87,
      sort_at: "2026-07-06T08:00:00Z",
    })

    await expect(getContentItem("item-2")).resolves.toEqual(
      expect.objectContaining({
        id: "item-2",
        summary: "Long-form source summary",
        canonicalUrl: "https://example.com/deep-ai",
        score: 87,
      })
    )
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/content-items/item-2", undefined)
  })

  it("sends content item filter query params", async () => {
    const fetchSpy = stubFetch([])

    await getContentItems({ status: "approved", sort: "score", limit: 25, isRewriteReady: true })

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/content-items?limit=25&status=approved&is_rewrite_ready=true&sort=score",
      undefined
    )
  })

  it("maps GET /media-assets metadata", async () => {
    stubFetch([
      {
        id: "media-1",
        normalized_url: "https://example.com/image.jpg",
        kind: "image",
        mime_type: "image/jpeg",
        width: 1200,
        height: 800,
        storage_path: "/data/media/image.jpg",
        fetch_status: "downloaded",
        media_quality: "high",
        media_confidence: "0.92",
        is_primary_candidate: true,
        is_primary: false,
        media_source_type: "article_body",
        asset_role: "hero",
        byte_length: 2048,
        created_at: "2026-07-06T08:00:00Z",
      },
    ])

    await expect(getMediaAssets()).resolves.toEqual([
      expect.objectContaining({
        id: "media-1",
        src: "https://example.com/image.jpg",
        fetchStatus: "downloaded",
        quality: "high",
        confidence: "0.92",
        isPrimaryCandidate: true,
        isPrimary: false,
        sourceType: "article_body",
        role: "hero",
      }),
    ])
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

  it("does not replace failed dashboard subrequests with mock data", async () => {
    const fetchSpy = vi.fn((url: string) => {
      if (url === "/api/backend/ingest/runs") {
        return Promise.resolve({
          ok: false,
          status: 503,
          statusText: "Service Unavailable",
          text: async () => "offline",
        })
      }

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

    await expect(getDashboardSnapshot()).rejects.toBeInstanceOf(ApiError)
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
