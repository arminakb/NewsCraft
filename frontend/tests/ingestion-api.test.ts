import {
  getIngestRuns,
  getSource,
  getSources,
  runIngest,
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

  it("uses the typed ingest client with a generated request UUID", async () => {
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn(() => "44444444-4444-4444-8444-444444444444"),
    })
    const fetchSpy = stubFetch({
      job_id: "job-1",
      status: "queued",
      deduplicated: false,
    })

    await runIngest({ platforms: ["rss"], sourceIds: ["source-1"] })

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/ingest/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          request_id: "44444444-4444-4444-8444-444444444444",
          platforms: ["rss"],
          source_ids: ["source-1"],
        }),
      }),
    )
  })

  it("maps ingestion runs using durable timestamps and stats", async () => {
    stubFetch([
      {
        id: "run-1",
        started_at: "2026-07-11T08:00:00Z",
        finished_at: "2026-07-11T08:01:00Z",
        status: "partial",
        trigger: "daily_bundle",
        stats: { checked: 4, items: 3 },
      },
    ])

    await expect(getIngestRuns()).resolves.toEqual([
      expect.objectContaining({
        id: "run-1",
        label: expect.stringContaining("2026-07-11"),
        scope: "Daily Bundle",
        status: "partial",
        progress: 75,
        duration: "01:00",
        items: 3,
      }),
    ])
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
