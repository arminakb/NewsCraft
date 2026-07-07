import { ApiError, getContentItems, getSources, runIngest, seedSources } from "@/lib/api-client"

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
