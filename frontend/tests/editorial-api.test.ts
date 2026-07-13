import {
  bulkSetStoryEditorialState,
  createManualStory,
  getBrandOptions,
  getStories,
  getPromptVersionOptions,
  groupPendingStories,
  requestContentPack,
  requestResearch,
  setStoryEditorialState,
} from "@/lib/editorial-api"

describe("editorial API", () => {
  beforeEach(() => vi.restoreAllMocks())

  it("submits manual intake and maps durable jobs", async () => {
    const fetchSpy = stubFetch({ job_id: "job-1", status: "queued", deduplicated: false }, 202)
    await expect(createManualStory({ kind: "url", url: "https://example.com/report", title: null })).resolves.toMatchObject({ jobId: "job-1" })
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/stories/manual", expect.objectContaining({ method: "POST" }))
  })

  it("queues grouping rather than grouping historical content in the browser", async () => {
    const fetchSpy = stubFetch({ job_id: "job-group", status: "queued", deduplicated: false }, 202)
    await expect(groupPendingStories({ limit: 500 })).resolves.toMatchObject({ jobId: "job-group" })
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/stories/group-pending", expect.objectContaining({ method: "POST", body: JSON.stringify({ limit: 500 }) }))
  })

  it("sends provider profile UUID and never provider type", async () => {
    const fetchSpy = stubFetch({ disposition: "enqueued", run_id: "run-1", job_id: "job-1", completeness: { complete: false, score: 40, reasons: [] } }, 202)
    await requestResearch("story-1", { mode: "manual", depth: "deep", providerProfileId: "profile-1", queryHint: "Verify" })
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/stories/story-1/research-runs", expect.objectContaining({ body: JSON.stringify({ mode: "manual", depth: "deep", provider_profile_id: "profile-1", query_hint: "Verify" }) }))
  })

  it("supports exact single and bulk state mutations", async () => {
    stubFetchOnce(summary({ status: "shortlisted" }))
    await setStoryEditorialState("story-1", "shortlisted")
    stubFetchOnce({ items: [summary({ id: "story-1", status: "rejected" }), summary({ id: "story-2", status: "rejected" })] })
    await bulkSetStoryEditorialState(["story-1", "story-2"], "rejected")
    expect(fetch).toHaveBeenNthCalledWith(1, "/api/backend/stories/story-1/editorial-state", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ state: "shortlisted" }) }))
    expect(fetch).toHaveBeenNthCalledWith(2, "/api/backend/stories/bulk-editorial-state", expect.objectContaining({ method: "POST", body: JSON.stringify({ story_ids: ["story-1", "story-2"], state: "rejected" }) }))
  })

  it("submits both immutable prompt version IDs", async () => {
    const fetchSpy = stubFetch({ job_id: "job-pack", status: "queued", deduplicated: false }, 202)
    await requestContentPack("story-1", { brandProfileId: "brand-1", generationProviderProfileId: "provider-1", canonicalPromptTemplateVersionId: "canonical-1", platformPromptTemplateVersionId: "platform-1" })
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/stories/story-1/content-packs", expect.objectContaining({ body: JSON.stringify({ brand_profile_id: "brand-1", platform: "telegram", generation_provider_profile_id: "provider-1", canonical_prompt_template_version_id: "canonical-1", platform_prompt_template_version_id: "platform-1", research_mode: "off", research_provider_profile_id: null }) }))
  })

  it("maps brand and immutable prompt options from generation settings", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "brand-1", name: "News desk", is_default: true }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([
        { id: "template-c", purpose_key: "canonical_story" },
        { id: "template-t", purpose_key: "telegram_pack" },
        { id: "ignored", purpose_key: "legacy" },
      ]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "canonical-1", version: 2, checksum_sha256: "a".repeat(64), is_active: true }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "telegram-1", version: 3, checksum_sha256: "b".repeat(64), is_active: true }]), { status: 200 }))

    await expect(getBrandOptions()).resolves.toEqual([{ id: "brand-1", name: "News desk", isDefault: true }])
    await expect(getPromptVersionOptions()).resolves.toEqual([
      { id: "canonical-1", purpose: "canonical_story", version: 2, checksumSha256: "a".repeat(64), active: true },
      { id: "telegram-1", purpose: "telegram_pack", version: 3, checksumSha256: "b".repeat(64), active: true },
    ])
  })

  it("rejects fractional completeness scores instead of masking them as percentages", async () => {
    stubFetch({ items: [summary({ completeness: { complete: false, score: 0.4, reasons: [] } })], next_cursor: null })
    await expect(getStories()).rejects.toThrow("Invalid completeness score")
  })
})

function stubFetch(body: unknown, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }))
}
function stubFetchOnce(body: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify(body), { status: 200 }))
}
function summary(overrides: Record<string, unknown> = {}) {
  return { id: "story-1", title: "Story", status: "inbox", primary_language: "en", superseded_by_id: null, evidence_count: 2, latest_evidence_at: "2026-07-12T08:00:00Z", completeness: { complete: false, score: 40, reasons: ["More sources needed"] }, evidence_set_hash: "a".repeat(64), created_at: "2026-07-12T07:00:00Z", updated_at: "2026-07-12T08:00:00Z", ...overrides }
}
