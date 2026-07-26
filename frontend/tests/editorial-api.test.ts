import {
  getAIProviderOptions,
  getContentPackRequests,
  getResearchRuns,
  getStoryCompleteness,
  getStoryEvidence,
} from "@/features/editorial/api"

describe("editorial feature API", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("loads only the story projection needed by automation research status", async () => {
    const fetchSpy = stubFetch({
      completeness: { complete: false, score: 40, reasons: ["More sources needed"] },
    })

    await expect(getStoryCompleteness("story/1")).resolves.toEqual({
      complete: false,
      score: 40,
      reasons: ["More sources needed"],
    })
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/stories/story%2F1", undefined)
  })

  it("rejects fractional completeness scores instead of masking them", async () => {
    stubFetch({ completeness: { complete: false, score: 0.4, reasons: [] } })

    await expect(getStoryCompleteness("story-1")).rejects.toThrow(
      "Invalid completeness score",
    )
  })

  it("maps exact evidence snapshots", async () => {
    stubFetch([
      {
        id: "evidence-1",
        evidence_key: "source-1",
        title: "Report",
        content_text: "Exact captured text",
        content_sha256: "a".repeat(64),
        source_url: "https://example.com/report",
        authors: ["Reporter"],
        published_at: "2026-07-12T07:00:00Z",
        captured_at: "2026-07-12T08:00:00Z",
      },
    ])

    await expect(getStoryEvidence("story-1")).resolves.toEqual([
      {
        id: "evidence-1",
        evidenceKey: "source-1",
        title: "Report",
        contentText: "Exact captured text",
        contentSha256: "a".repeat(64),
        sourceUrl: "https://example.com/report",
        authors: ["Reporter"],
        publishedAt: "2026-07-12T07:00:00Z",
        capturedAt: "2026-07-12T08:00:00Z",
      },
    ])
  })

  it("maps durable research runs and provider identity", async () => {
    stubFetch({
      items: [
        {
          id: "run-1",
          story_id: "story-1",
          requested_mode: "manual",
          status: "succeeded",
          provider: { id: "provider-1", name: "Codex", provider_type: "codex" },
          budget: { max_queries: 4, max_pages: 8, max_elapsed_seconds: 120 },
          resolved_model: "gpt-5.4",
          completeness: { complete: true, score: 100, reasons: [] },
          attempts: [
            {
              id: "attempt-1",
              attempt_number: 1,
              status: "succeeded",
              error_message: null,
            },
          ],
          sources: [
            {
              id: "source-1",
              url: "https://example.com",
              content_sha256: "b".repeat(64),
            },
          ],
          result_revision_id: "revision-1",
        },
      ],
    })

    await expect(getResearchRuns("story-1")).resolves.toEqual([
      expect.objectContaining({
        id: "run-1",
        storyId: "story-1",
        provider: { id: "provider-1", name: "Codex", providerType: "codex" },
        budget: { maxQueries: 4, maxPages: 8, maxElapsedSeconds: 120 },
        resolvedModel: "gpt-5.4",
        resultStoryRevisionId: "revision-1",
      }),
    ])
  })

  it("uses the generated provider response contract", async () => {
    stubFetch([
      {
        id: "provider-1",
        name: "OpenRouter",
        provider_type: "openrouter",
        default_model: "openrouter/free",
        settings: {},
        enabled: true,
        configured: true,
        capabilities: { generation: true, research: false },
        capability_states: {},
        unavailability_codes: ["research_unavailable"],
      },
    ])

    await expect(getAIProviderOptions()).resolves.toEqual([
      {
        id: "provider-1",
        name: "OpenRouter",
        providerType: "openrouter",
        defaultModel: "openrouter/free",
        capabilities: { generation: true, research: false },
        unavailableReason: "research unavailable",
      },
    ])
  })

  it("maps durable generation requests without inventing a pack", async () => {
    stubFetch([
      {
        id: "request-1",
        job_id: "job-1",
        story_id: "story-1",
        status: "needs_review",
        last_failure: "Provider validation failed",
        created_at: "2026-07-12T08:00:00Z",
        updated_at: "2026-07-12T08:01:00Z",
        pack: null,
      },
    ])

    await expect(getContentPackRequests()).resolves.toEqual([
      {
        id: "request-1",
        jobId: "job-1",
        storyId: "story-1",
        status: "needs_review",
        lastFailure: "Provider validation failed",
        createdAt: "2026-07-12T08:00:00Z",
        updatedAt: "2026-07-12T08:01:00Z",
        pack: null,
      },
    ])
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
