import {
  bulkSetStoryEditorialState,
  createManualStory,
  getBrandOptions,
  getContentPacks,
  getStories,
  getPromptVersionOptions,
  groupPendingStories,
  requestContentPack,
  requestResearch,
  saveVariantRevision,
  approveVariantRevision,
  rejectVariantRevision,
  regenerateVariant,
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
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/stories/story-1/content-packs", expect.objectContaining({ body: JSON.stringify({ brand_profile_id: "brand-1", platform: "telegram", generation_provider_profile_id: "provider-1", canonical_prompt_template_version_id: "canonical-1", platform_prompt_template_version_id: "platform-1", research_mode: "off", research_provider_profile_id: null, research_run_id: null }) }))
  })

  it("submits ordered multi-platform generation for server-side prompt resolution", async () => {
    const fetchSpy = stubFetch({ job_id: "job-pack", status: "queued", deduplicated: false }, 202)
    await requestContentPack("story-1", {
      brandProfileId: "brand-1",
      generationProviderProfileId: "provider-1",
      platforms: ["telegram", "instagram", "x", "blog"],
    })
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/stories/story-1/content-packs", expect.objectContaining({
      body: JSON.stringify({
        brand_profile_id: "brand-1",
        platforms: ["telegram", "instagram", "x", "blog"],
        generation_provider_profile_id: "provider-1",
        research_mode: "off",
        research_provider_profile_id: null,
        research_run_id: null,
      }),
    }))
  })

  it("maps content-pack variants for all supported platforms", async () => {
    stubFetch([{
      id: "pack-1",
      story_id: "story-1",
      story_revision_id: "story-revision-1",
      brand_profile_id: "brand-1",
      status: "draft",
      created_at: "2026-07-12T07:00:00Z",
      updated_at: "2026-07-12T08:00:00Z",
      variants: ["telegram", "instagram", "x", "blog"].map((platform) => ({ id: `variant-${platform}`, platform })),
    }])

    await expect(getContentPacks()).resolves.toEqual([
      expect.objectContaining({ variants: [
        { id: "variant-telegram", platform: "telegram" },
        { id: "variant-instagram", platform: "instagram" },
        { id: "variant-x", platform: "x" },
        { id: "variant-blog", platform: "blog" },
      ] }),
    ])
  })

  it("submits a selected succeeded research run identity without a result revision ID", async () => {
    const fetchSpy = stubFetch({ job_id: "job-pack", status: "queued", deduplicated: false }, 202)
    await requestContentPack("story-1", { brandProfileId: "brand-1", generationProviderProfileId: "provider-1", canonicalPromptTemplateVersionId: "canonical-1", platformPromptTemplateVersionId: "platform-1", researchRunId: "run-1" })
    const body = JSON.parse(String((fetchSpy.mock.calls[0][1] as RequestInit).body))
    expect(body).toMatchObject({ research_run_id: "run-1", research_mode: "off" })
    expect(body).not.toHaveProperty("research_result_story_revision_id")
  })

  it("binds edit and approval mutations to exact revision IDs and hashes", async () => {
    const revision = backendRevision()
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(revision), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...revision, approval_state: "approved" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...revision, approval_state: "rejected" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ job_id: "job-1", status: "queued", deduplicated: false }), { status: 202 }))
    const hash = "a".repeat(64)
    await saveVariantRevision("variant-1", { baseRevisionId: "revision-1", baseContentHash: hash, content: { body: "Edited", parseMode: "HTML", buttons: [] }, mediaAssetIds: ["media-1"], editNote: "Corrected wording" })
    await approveVariantRevision("revision-1", { expectedContentHash: hash, note: null })
    await rejectVariantRevision("revision-1", { reason: "Unsupported claim" }, hash)
    await regenerateVariant("variant-1", { providerProfileId: "provider-uuid", platformPromptTemplateVersionId: "prompt-uuid", instruction: null })
    expect(fetchSpy).toHaveBeenNthCalledWith(1, "/api/backend/platform-variants/variant-1/revisions", expect.objectContaining({ body: JSON.stringify({ base_revision_id: "revision-1", base_content_hash: hash, content: { body: "Edited", parse_mode: "HTML", buttons: [] }, media_asset_ids: ["media-1"], edit_note: "Corrected wording" }) }))
    expect(fetchSpy).toHaveBeenNthCalledWith(2, "/api/backend/platform-variant-revisions/revision-1/approve", expect.objectContaining({ body: JSON.stringify({ expected_content_hash: hash, note: null }) }))
    expect(fetchSpy).toHaveBeenNthCalledWith(3, "/api/backend/platform-variant-revisions/revision-1/reject", expect.objectContaining({ body: JSON.stringify({ expected_content_hash: hash, note: "Unsupported claim" }) }))
    expect(fetchSpy).toHaveBeenNthCalledWith(4, "/api/backend/platform-variants/variant-1/regenerate", expect.objectContaining({ body: JSON.stringify({ generation_provider_profile_id: "provider-uuid", platform_prompt_template_version_id: "prompt-uuid", instruction: null }) }))
    expect(JSON.stringify(vi.mocked(fetchSpy).mock.calls)).not.toContain("provider_type")
  })

  it("rejects malformed persisted validation gates instead of treating them as approval-safe", async () => {
    stubFetch([{ ...backendRevision(), validation_results: [{ gate: "media", valid: false, message: "wrong shape" }] }])
    const { getVariantRevisions } = await import("@/lib/editorial-api")
    await expect(getVariantRevisions("variant-1")).rejects.toThrow("Invalid revision validation result")
  })

  it.each([
    ["content", { content: { ...backendRevision().content, parse_mode: "Markdown" } }, "Invalid revision content"],
    ["evidence", { evidence_map: [] }, "Invalid revision evidence map"],
    ["gates", { validation_results: [] }, "Invalid revision validation result"],
  ])("rejects malformed revision %s instead of coercing it", async (_field, change, message) => {
    stubFetch([{ ...backendRevision(), ...change }])
    const { getVariantRevisions } = await import("@/lib/editorial-api")
    await expect(getVariantRevisions("variant-1")).rejects.toThrow(message)
  })

  it("normalizes only the historical missing validation reason to null", async () => {
    stubFetch([{ ...backendRevision(), validation_results: [{ gate: "telegram_schema", ok: true }] }])
    const { getVariantRevisions } = await import("@/lib/editorial-api")
    await expect(getVariantRevisions("variant-1")).resolves.toEqual([
      expect.objectContaining({ validationResults: [{ gate: "telegram_schema", ok: true, reason: null }] }),
    ])
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

  it("includes immutable prompt options for every Release 4 platform", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify([
        { id: "template-i", purpose_key: "instagram_pack" },
        { id: "template-x", purpose_key: "x_pack" },
        { id: "template-b", purpose_key: "blog_pack" },
      ]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "instagram-1", version: 1, checksum_sha256: "a".repeat(64), is_active: true }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "x-1", version: 1, checksum_sha256: "b".repeat(64), is_active: true }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "blog-1", version: 1, checksum_sha256: "c".repeat(64), is_active: true }]), { status: 200 }))

    await expect(getPromptVersionOptions()).resolves.toEqual([
      { id: "instagram-1", purpose: "instagram_pack", version: 1, checksumSha256: "a".repeat(64), active: true },
      { id: "x-1", purpose: "x_pack", version: 1, checksumSha256: "b".repeat(64), active: true },
      { id: "blog-1", purpose: "blog_pack", version: 1, checksumSha256: "c".repeat(64), active: true },
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
function backendRevision() {
  return { id: "revision-1", platform_variant_id: "variant-1", content_pack_id: "pack-1", story_id: "story-1", parent_revision_id: null, generation_attempt_id: null, revision_number: 1, content: { body: "Edited", parse_mode: "HTML", buttons: [], source_item_id: null, media_asset_ids: [], source_url: null, media_policy: "preserve", direction: "ltr", dry_run: false }, content_hash: "a".repeat(64), evidence_map: [{ evidence_snapshot_id: "51111111-1111-4111-8111-111111111111", evidence_key: "operator-1", source_url: null, locator: "chars:0-6", excerpt_sha256: "b".repeat(64) }], validation_results: [{ gate: "telegram_schema", ok: true, reason: null }], approval_state: "pending_review", approval_note: null, approved_at: null, created_by: "operator", origin: "operator", provider_profile: null, resolved_model: null, created_at: "2026-07-12T08:00:00Z" }
}
