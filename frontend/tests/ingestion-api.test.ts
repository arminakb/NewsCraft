import {
  checkSourceHealth,
  createSource,
  createSourceCollection,
  addSourcesToCollection,
  deleteSource,
  getSourceCollectionRun,
  getSourceCollectionContinuous,
  getSourceCollections,
  getSourcePage,
  getSource,
  getSources,
  getIngestRuns,
  startSourceCollectionIngest,
  stopSourceCollectionContinuous,
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

  it("creates a Source Collection with the JSON create contract", async () => {
    const fetchSpy = stubFetch({
      id: "collection-1",
      name: "AI Sources",
      description: null,
      source_count: 0,
      maximum_sources: 100,
      created_at: "2026-08-07T08:00:00Z",
      updated_at: "2026-08-07T08:00:00Z",
      active_ingest_run_id: null,
      active_ingest_status: null,
      active_ingest_source_count: null,
      active_ingest_processed_count: null,
      active_ingest_success_count: null,
      active_ingest_failure_count: null,
    })

    await expect(createSourceCollection({ name: " AI Sources ", description: "  " })).resolves.toEqual(
      expect.objectContaining({ id: "collection-1", name: "AI Sources", sourceCount: 0 }),
    )
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/source-collections",
      expect.objectContaining({
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: "AI Sources" }),
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

  it("maps paged source collections and collection run progress", async () => {
    const fetchSpy = stubFetch([
      {
        id: "collection-1",
        name: "Morning News",
        description: "Early run",
        source_count: 2,
        maximum_sources: 100,
        created_at: "2026-08-06T08:00:00Z",
        updated_at: "2026-08-06T08:00:00Z",
        active_ingest_run_id: "run-1",
        active_ingest_status: "running",
        active_ingest_source_count: 2,
        active_ingest_processed_count: 1,
        active_ingest_success_count: 1,
        active_ingest_failure_count: 0,
      },
    ])

    await expect(getSourceCollections()).resolves.toEqual([
      expect.objectContaining({ id: "collection-1", sourceCount: 2, activeIngestProcessedCount: 1 }),
    ])
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/source-collections", undefined)

    stubFetch({
      items: [],
      total: 0,
      limit: 25,
      offset: 0,
      has_more: false,
    })
    await expect(getSourcePage({ excludeCollectionId: "collection-1", search: "tech", limit: 25 })).resolves.toEqual({
      items: [],
      total: 0,
      limit: 25,
      offset: 0,
      hasMore: false,
    })

    const addSpy = stubFetch({
      collection_id: "collection-1",
      added_source_ids: ["source-1"],
      removed_source_ids: [],
      already_member_source_ids: [],
      missing_source_ids: [],
      source_count: 1,
      maximum_sources: 100,
    })
    await expect(addSourcesToCollection("collection-1", ["source-1"])).resolves.toEqual(
      expect.objectContaining({ collectionId: "collection-1", addedSourceIds: ["source-1"] }),
    )
    expect(addSpy).toHaveBeenCalledWith(
      "/api/backend/source-collections/collection-1/sources",
      expect.objectContaining({ method: "POST" }),
    )

    const acceptedSpy = stubFetch({
      job_id: "job-1",
      run_id: "run-1",
      source_collection_id: "collection-1",
      source_collection_name: "Morning News",
      source_count: 2,
      status: "queued",
      deduplicated: false,
    })
    await startSourceCollectionIngest("collection-1", "request-1")
    expect(acceptedSpy).toHaveBeenCalledWith(
      "/api/backend/source-collections/collection-1/ingest",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ mode: "once", request_id: "request-1" }) }),
    )

    stubFetch({
      id: "run-1",
      source_collection_id: "collection-1",
      source_collection_name_at_start: "Morning News",
      source_count: 2,
      processed_count: 1,
      success_count: 1,
      failure_count: 0,
      started_at: "2026-08-06T08:00:00Z",
      completed_at: null,
      status: "running",
      trigger: "source_collection_manual",
      stats: {},
      error: null,
      sources: [],
    })
    await expect(getSourceCollectionRun("collection-1", "run-1")).resolves.toEqual(
      expect.objectContaining({ processedCount: 1, sourceCollectionId: "collection-1" }),
    )
  })

  it("loads a bounded recent ingest-run summary", async () => {
    const fetchSpy = stubFetch([
      {
        id: "run-1",
        started_at: "2026-08-08T08:00:00Z",
        finished_at: "2026-08-08T08:01:00Z",
        trigger: "source_collection_manual",
        status: "succeeded",
        stats: {},
        source_collection_id: "collection-1",
        source_collection_name_at_start: "Morning News",
        source_count: 2,
        processed_count: 2,
        success_count: 2,
        failure_count: 0,
      },
    ])

    await expect(getIngestRuns(6)).resolves.toEqual([
      expect.objectContaining({
        id: "run-1",
        sourceCollectionNameAtStart: "Morning News",
        successCount: 2,
        failureCount: 0,
      }),
    ])
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/ingest/runs?limit=6", undefined)
  })

  it("uses explicit continuous mode and maps durable subscription actions", async () => {
    const startSpy = stubFetch({
      job_id: null,
      run_id: null,
      source_collection_id: "collection-1",
      source_collection_name: "Morning News",
      source_count: 0,
      status: "starting",
      deduplicated: false,
      mode: "continuous",
      subscription_id: "subscription-1",
      interval_minutes: 15,
      next_cycle_at: "2026-08-07T08:15:00Z",
    })

    await expect(startSourceCollectionIngest("collection-1", "request-2", "continuous")).resolves.toEqual(
      expect.objectContaining({
        mode: "continuous",
        subscriptionId: "subscription-1",
        sourceCount: 0,
      }),
    )
    expect(startSpy).toHaveBeenCalledWith(
      "/api/backend/source-collections/collection-1/ingest",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ mode: "continuous", request_id: "request-2" }),
      }),
    )

    const statusSpy = stubFetch({
      id: "subscription-1",
      source_collection_id: "collection-1",
      source_collection_name: "Morning News",
      mode: "continuous",
      status: "running",
      created_at: "2026-08-07T08:00:00Z",
      started_at: "2026-08-07T08:00:00Z",
      stopped_at: null,
      last_cycle_at: null,
      next_cycle_at: "2026-08-07T08:15:00Z",
      last_success_at: null,
      cycle_count: 0,
      interval_minutes: 15,
      created_by: "operator",
      last_cycle_status: null,
      last_error: null,
      current_cycle_job_id: null,
      current_cycle_run_id: null,
    })
    await expect(getSourceCollectionContinuous("collection-1")).resolves.toEqual(
      expect.objectContaining({ status: "running", intervalMinutes: 15 }),
    )
    expect(statusSpy).toHaveBeenCalledWith("/api/backend/source-collections/collection-1/continuous", undefined)

    const stopSpy = stubFetch({
      id: "subscription-1",
      source_collection_id: "collection-1",
      source_collection_name: "Morning News",
      mode: "continuous",
      status: "stopped",
      created_at: "2026-08-07T08:00:00Z",
      started_at: "2026-08-07T08:00:00Z",
      stopped_at: "2026-08-07T08:01:00Z",
      last_cycle_at: null,
      next_cycle_at: null,
      last_success_at: null,
      cycle_count: 0,
      interval_minutes: 15,
      created_by: "operator",
      last_cycle_status: "stopped",
      last_error: "Stopped by operator.",
      current_cycle_job_id: null,
      current_cycle_run_id: null,
    })
    await expect(stopSourceCollectionContinuous("collection-1")).resolves.toEqual(
      expect.objectContaining({ status: "stopped" }),
    )
    expect(stopSpy).toHaveBeenCalledWith(
      "/api/backend/source-collections/collection-1/continuous/stop",
      expect.objectContaining({ method: "POST", body: JSON.stringify({}) }),
    )
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
