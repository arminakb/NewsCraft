import {
  checkSourceHealth,
  createSource,
  deleteSource,
  getSource,
  getSources,
  seedSources,
} from "@/features/operations/ingestion-api"
import { ApiError } from "@/lib/http"

describe("ingestion API", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("maps sources without inventing missing health metadata", async () => {
    stubFetch([
      {
        id: "source-1",
        platform: "rss",
        name: "OpenAI",
        feed_url: "https://example.com/rss",
      },
      {
        id: "inactive",
        platform: "rss",
        name: "Inactive",
        feed_url: "https://example.com/inactive.xml",
        active: false,
      },
      {
        id: "failing",
        platform: "rss",
        name: "Failing",
        feed_url: "https://example.com/failing.xml",
        failure_count: 5,
      },
    ])

    await expect(getSources()).resolves.toEqual([
      expect.objectContaining({
        id: "source-1",
        platform: "rss",
        status: "unknown",
      }),
      expect.objectContaining({ id: "inactive", status: "disabled" }),
      expect.objectContaining({ id: "failing", status: "broken" }),
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
  ])("maps source platform %s to %s", async (platform, expected) => {
    stubFetch([
      {
        id: `source-${platform}`,
        platform,
        name: platform,
        feed_url: "https://example.com/source",
      },
    ])

    const [source] = await getSources()

    expect(source.platform).toBe(expected)
  })

  it("keeps the calendar date when formatting source health", async () => {
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

  it("maps source details and encodes the source ID", async () => {
    const fetchSpy = stubFetch({
      id: "source-1",
      platform: "telegram_public",
      name: "DW Persian",
      telegram_username: "dw_farsi",
    })

    await expect(getSource("source/1")).resolves.toEqual(
      expect.objectContaining({
        platform: "telegram_public",
        url: "https://t.me/dw_farsi",
      }),
    )
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/sources/source%2F1",
      undefined,
    )
  })

  it("seeds sources", async () => {
    stubFetch({ upserted: 50 })

    await expect(seedSources()).resolves.toEqual({ upserted: 50 })
  })

  it("deletes a source through the persistent API", async () => {
    const fetchSpy = stubFetch(null)

    await expect(deleteSource("source/1")).resolves.toBeUndefined()
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/sources/source%2F1",
      expect.objectContaining({ method: "DELETE" }),
    )
  })

  it("creates and maps a persistent source", async () => {
    const fetchSpy = stubFetch({
      id: "source-1",
      platform: "rss",
      name: "Example Wire",
      feed_url: "https://example.com/feed.xml",
      source_group: "technology",
      language_hint: "en",
      active: true,
      health_status: "unknown",
      fetch_interval_minutes: 30,
    })

    await expect(createSource({
      platform: "rss",
      name: "Example Wire",
      url: "https://example.com/feed.xml",
      category: "technology",
      language: "en",
      fetchIntervalMinutes: 30,
    })).resolves.toEqual(expect.objectContaining({
      id: "source-1",
      name: "Example Wire",
      status: "unknown",
    }))
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/sources",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          platform: "rss",
          name: "Example Wire",
          url: "https://example.com/feed.xml",
          source_group: "technology",
          language_hint: "en",
          fetch_interval_minutes: 30,
        }),
      }),
    )
  })

  it("checks one source and maps persisted health metadata", async () => {
    const fetchSpy = stubFetch({
      source_id: "source-1",
      health_status: "broken",
      is_checking: false,
      last_checked_at: "2026-07-27T08:30:00Z",
      failure_reason: "Source returned HTTP 503.",
    })

    await expect(checkSourceHealth("source/1")).resolves.toEqual({
      sourceId: "source-1",
      status: "broken",
      isChecking: false,
      lastCheckedAt: "2026-07-27T08:30:00Z",
      failureReason: "Source returned HTTP 503.",
    })
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/sources/source%2F1/health-check",
      expect.objectContaining({ method: "POST" }),
    )
  })

  it("throws the shared typed error on failed requests", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        text: async () => "offline",
      }),
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
