import {
  approvePlatformRevision,
  decodeContentPackage,
  decodePlatformRevision,
  getRenderedRevisionHtml,
  rejectPlatformRevision,
  saveManualPlatformRevision,
} from "@/features/packages/api"
import {
  regeneratePlatformVariant,
  saveTelegramPlatformRevision,
} from "@/features/packages/telegram-api"
import type {
  BlogPayload,
  CitationRef,
  InstagramPayload,
  ManualPlatformEditRequest,
  XPayload,
} from "@/features/packages/types"

const ids = {
  revision: "11111111-1111-4111-8111-111111111111",
  variant: "22222222-2222-4222-8222-222222222222",
  pack: "33333333-3333-4333-8333-333333333333",
  story: "44444444-4444-4444-8444-444444444444",
  evidence: "55555555-5555-4555-8555-555555555555",
  media: "66666666-6666-4666-8666-666666666666",
  brand: "77777777-7777-4777-8777-777777777777",
  storyRevision: "88888888-8888-4888-8888-888888888888",
}

const citationWire = {
  evidence_snapshot_id: ids.evidence,
  evidence_key: "evidence:one",
  source_url: "https://example.com/report",
  locator: "chars:0-8",
  excerpt_sha256: "a".repeat(64),
}

const citation: CitationRef = {
  evidenceSnapshotId: ids.evidence,
  evidenceKey: "evidence:one",
  sourceUrl: "https://example.com/report",
  locator: "chars:0-8",
  excerptSha256: "a".repeat(64),
}

const mediaWire = {
  media_asset_id: ids.media,
  role: "slide",
  order: 1,
  alt_text: "A grounded chart",
  manual_brief: null,
  image_prompt: null,
}

const manualPayloads = {
  instagram: {
    hook: "Grounded hook",
    caption: "Grounded caption",
    cta: "Read more",
    hashtags: ["#news"],
    alt_text: "A carousel about the report",
    carousel: [{ order: 1, headline: "What changed", body: "Verified details", media: mediaWire }],
    citations: [citationWire],
    manual_checklist: ["Verify copy"],
  },
  x: {
    mode: "thread",
    posts: [{ order: 1, text: "Grounded post", media: [{ ...mediaWire, role: "post" }], citations: [citationWire] }],
    link_strategy: "last_post",
    manual_checklist: ["Verify thread"],
  },
  blog: {
    title: "Grounded report",
    slug: "grounded-report",
    excerpt: "A grounded summary",
    body_markdown: "# Grounded report\n\nA sufficiently complete grounded article.",
    headings: ["Grounded report"],
    citations: [citationWire],
    tags: ["news"],
    seo_description: "A grounded description of the verified report for readers.",
    hero_media: { ...mediaWire, role: "hero" },
    canonical_sources: ["https://example.com/report"],
    manual_checklist: ["Verify links"],
  },
} as const

describe("multi-platform package API", () => {
  beforeEach(() => vi.restoreAllMocks())

  it("decodes the exact nine-key Telegram payload and keeps review evidence adjacent", () => {
    const result = decodePlatformRevision(revisionWire("telegram"))

    expect(result.platform).toBe("telegram")
    if (result.platform !== "telegram") throw new Error("expected Telegram")
    expect(result.payload).toEqual({
      body: "Grounded",
      parseMode: "HTML",
      buttons: [],
      sourceItemId: null,
      sourceUrl: null,
      mediaPolicy: "omit",
      mediaAssetIds: [],
      direction: "rtl",
      dryRun: false,
    })
    expect(Object.keys(result.payload)).toHaveLength(9)
    expect(result.evidenceCitations).toEqual([citation])
    expect(result.manualChecklist).toEqual([])
    expect(result.payload).not.toHaveProperty("evidenceCitations")
    expect(result.payload).not.toHaveProperty("manualChecklist")
  })

  it.each(["instagram", "x", "blog"] as const)("strictly decodes a %s revision", (platform) => {
    const result = decodePlatformRevision(revisionWire(platform))

    expect(result.platform).toBe(platform)
    expect(result.evidenceCitations).toEqual([citation])
    expect(result.manualChecklist).toEqual([platform === "instagram" ? "Verify copy" : platform === "x" ? "Verify thread" : "Verify links"])
    expect(result.sourceMedia).toEqual([
      expect.objectContaining({ id: ids.media, mimeType: "image/jpeg", available: true, role: "hero", order: 1 }),
    ])
  })

  it("rejects unknown persisted payload fields rather than silently dropping them", () => {
    const wire = revisionWire("instagram")
    wire.content = { ...wire.content, provider_commentary: "do not persist" }

    expect(() => decodePlatformRevision(wire)).toThrow("Invalid instagram revision content")
  })

  it("normalizes only the historical missing validation reason to null", () => {
    const wire = revisionWire("telegram")
    wire.validation_results = [{ gate: "telegram_schema", ok: true }]

    expect(decodePlatformRevision(wire).validationResults).toEqual([
      { gate: "telegram_schema", ok: true, reason: null },
    ])
  })

  it("preserves schema-valid empty strings so backend validation issues remain visible", () => {
    const wire = revisionWire("instagram")
    wire.content.manual_checklist = [""]
    wire.manual_checklist = [""]
    wire.content.hashtags = [""]
    wire.content.carousel[0].media.manual_brief = ""
    wire.media_plan[0].manual_brief = ""
    wire.validation_results = [{ gate: "manual_review", ok: false, reason: "" }]
    wire.validation_issues = [{ code: "instagram_empty_checklist_item", path: "manual_checklist.0", message: "Manual checklist items must not be empty", severity: "error" }]

    const result = decodePlatformRevision(wire)
    if (result.platform !== "instagram") throw new Error("expected Instagram")
    expect(result.payload.manualChecklist).toEqual([""])
    expect(result.payload.hashtags).toEqual([""])
    expect(result.payload.carousel[0].media.manualBrief).toBe("")
    expect(result.validationResults[0].reason).toBe("")
    expect(result.validation[0].code).toBe("instagram_empty_checklist_item")
  })

  it("accepts the backend's zero-based source-media order", () => {
    const wire = revisionWire("x")
    wire.source_media[0].order = 0

    expect(decodePlatformRevision(wire).sourceMedia[0].order).toBe(0)
  })

  it("decodes content-pack variants for every supported platform", () => {
    const platforms = ["telegram", "instagram", "x", "blog"] as const
    const result = decodeContentPackage({
      id: ids.pack,
      story_id: ids.story,
      story_revision_id: ids.storyRevision,
      brand_profile_id: ids.brand,
      status: "draft",
      created_at: "2026-07-13T08:00:00Z",
      updated_at: "2026-07-13T08:00:00Z",
      variants: platforms.map((platform, index) => ({
        id: `${index + 1}9999999-9999-4999-8999-999999999999`,
        platform,
        current_revision: { ...revisionWire(platform), platform_variant_id: `${index + 1}9999999-9999-4999-8999-999999999999` },
      })),
    })

    expect(result.variants.map((item) => item.platform)).toEqual(platforms)
    expect(result.variants.map((item) => item.currentRevision?.platform)).toEqual(platforms)
  })

  it("posts the exact immutable manual edit contract", async () => {
    const response = revisionWire("instagram")
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(response), { status: 201, headers: { "content-type": "application/json" } }),
    )
    const content = decodePlatformRevision(response).payload as InstagramPayload
    const input: ManualPlatformEditRequest<"instagram"> = {
      baseRevisionId: ids.revision,
      baseContentHash: "b".repeat(64),
      payload: { platform: "instagram", content },
      evidenceMap: [citation],
      editNote: "Shortened the caption",
    }

    await expect(saveManualPlatformRevision(ids.variant, input)).resolves.toMatchObject({ platform: "instagram" })
    const request = fetchSpy.mock.calls[0][1] as RequestInit
    expect(fetchSpy.mock.calls[0][0]).toBe(`/api/backend/platform-variants/${ids.variant}/revisions`)
    expect(JSON.parse(String(request.body))).toEqual({
      base_revision_id: ids.revision,
      base_content_hash: "b".repeat(64),
      payload: { platform: "instagram", content: manualPayloads.instagram },
      evidence_map: [citationWire],
      edit_note: "Shortened the caption",
    })
  })

  it("posts Telegram edits through the shared package decoder", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(revisionWire("telegram")), {
        status: 201,
        headers: { "content-type": "application/json" },
      }),
    )

    await expect(saveTelegramPlatformRevision(ids.variant, {
      baseRevisionId: ids.revision,
      baseContentHash: "b".repeat(64),
      content: { body: "Edited", parseMode: "HTML", buttons: [] },
      mediaAssetIds: [ids.media],
      editNote: "Corrected wording",
    })).resolves.toMatchObject({ platform: "telegram", variantId: ids.variant })

    expect(fetchSpy).toHaveBeenCalledWith(
      `/api/backend/platform-variants/${ids.variant}/revisions`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          base_revision_id: ids.revision,
          base_content_hash: "b".repeat(64),
          content: { body: "Edited", parse_mode: "HTML", buttons: [] },
          media_asset_ids: [ids.media],
          edit_note: "Corrected wording",
        }),
      }),
    )
  })

  it("queues regeneration without a discarded prompt choice", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        job_id: "99999999-9999-4999-8999-999999999999",
        status: "queued",
        deduplicated: false,
      }), { status: 202, headers: { "content-type": "application/json" } }),
    )

    await expect(regeneratePlatformVariant(ids.variant, {
      providerProfileId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      instruction: null,
    })).resolves.toEqual({
      job_id: "99999999-9999-4999-8999-999999999999",
      status: "queued",
      deduplicated: false,
    })
    expect(fetchSpy).toHaveBeenCalledWith(
      `/api/backend/platform-variants/${ids.variant}/regenerate`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          generation_provider_profile_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          instruction: null,
        }),
      }),
    )
  })

  it("rejects a manual edit whose evidence map differs from ordered content citations", async () => {
    const response = revisionWire("instagram")
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(response), { status: 201 }))
    const content = decodePlatformRevision(response).payload as InstagramPayload

    await expect(saveManualPlatformRevision(ids.variant, {
      baseRevisionId: ids.revision,
      baseContentHash: "b".repeat(64),
      payload: { platform: "instagram", content },
      evidenceMap: [{ ...citation, evidenceKey: "different:evidence" }],
      editNote: "Shortened the caption",
    })).rejects.toThrow("Manual edit evidence map does not match content citations")
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it("rejects a manual edit response for a different immutable variant", async () => {
    const response = { ...revisionWire("instagram"), platform_variant_id: "99999999-9999-4999-8999-999999999999" }
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(response), { status: 201 }))
    const content = decodePlatformRevision(revisionWire("instagram")).payload as InstagramPayload

    await expect(saveManualPlatformRevision(ids.variant, {
      baseRevisionId: ids.revision,
      baseContentHash: "b".repeat(64),
      payload: { platform: "instagram", content },
      evidenceMap: [citation],
      editNote: "Shortened the caption",
    })).rejects.toThrow("Manual edit response identity mismatch")
  })

  it("binds manual approval and rejection to the exact revision hash", async () => {
    const response = revisionWire("blog")
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...response, approval_state: "approved" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...response, approval_state: "rejected" }), { status: 200 }))

    await approvePlatformRevision(ids.revision, { expectedContentHash: "b".repeat(64), note: "Reviewed" })
    await rejectPlatformRevision(ids.revision, { expectedContentHash: "b".repeat(64), reason: "Citation needs correction" })

    expect(fetchSpy).toHaveBeenNthCalledWith(1, `/api/backend/platform-variant-revisions/${ids.revision}/approve`, expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ expected_content_hash: "b".repeat(64), note: "Reviewed" }),
    }))
    expect(fetchSpy).toHaveBeenNthCalledWith(2, `/api/backend/platform-variant-revisions/${ids.revision}/reject`, expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ expected_content_hash: "b".repeat(64), note: "Citation needs correction" }),
    }))
  })

  it("strictly decodes sanitized blog HTML bound to the requested immutable revision and hash", async () => {
    const html = '<h1>Grounded report</h1>\n<p><a href="https://example.com/report">Source</a></p>'
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      revision_id: ids.revision,
      content_hash: "b".repeat(64),
      platform: "blog",
      html,
    }), { status: 200, headers: { "content-type": "application/json" } }))

    await expect(getRenderedRevisionHtml(ids.revision, "b".repeat(64))).resolves.toBe(html)
    expect(fetchSpy).toHaveBeenCalledWith(
      `/api/backend/platform-variant-revisions/${ids.revision}/rendered-html`,
      undefined,
    )
  })

  it.each([
    [{ revision_id: "99999999-9999-4999-8999-999999999999", content_hash: "b".repeat(64), platform: "blog", html: "<h1>Wrong revision</h1>" }, "identity mismatch"],
    [{ revision_id: ids.revision, content_hash: "c".repeat(64), platform: "blog", html: "<h1>Wrong hash</h1>" }, "identity mismatch"],
    [{ revision_id: ids.revision, content_hash: "b".repeat(64), platform: "blog", html: "<h1>Extra</h1>", extra: true }, "Invalid rendered revision HTML"],
  ])("rejects a rendered HTML response that is not the exact requested projection", async (response, error) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200,
      headers: { "content-type": "application/json" },
    }))

    await expect(getRenderedRevisionHtml(ids.revision, "b".repeat(64))).rejects.toThrow(error)
  })

  it("keeps the three manual request payloads discriminated at compile time", () => {
    const instagram: InstagramPayload = decodePlatformRevision(revisionWire("instagram")).payload as InstagramPayload
    const x: XPayload = decodePlatformRevision(revisionWire("x")).payload as XPayload
    const blog: BlogPayload = decodePlatformRevision(revisionWire("blog")).payload as BlogPayload
    expect([instagram.caption, x.posts[0].text, blog.title]).toEqual(["Grounded caption", "Grounded post", "Grounded report"])
  })
})

function revisionWire(platform: "telegram" | keyof typeof manualPayloads): Record<string, any> {
  const content = platform === "telegram"
    ? {
        body: "Grounded",
        parse_mode: "HTML",
        buttons: [],
        source_item_id: null,
        source_url: null,
        media_policy: "omit",
        media_asset_ids: [],
        direction: "rtl",
        dry_run: false,
      }
    : structuredClone(manualPayloads[platform])
  const checklist = platform === "telegram" ? [] : [...manualPayloads[platform].manual_checklist]
  return {
    id: ids.revision,
    platform,
    platform_variant_id: ids.variant,
    content_pack_id: ids.pack,
    story_id: ids.story,
    parent_revision_id: null,
    generation_attempt_id: null,
    revision_number: 1,
    content,
    content_hash: "b".repeat(64),
    evidence_map: [citationWire],
    manual_checklist: checklist,
    validation_results: [{ gate: `${platform}_schema`, ok: true, reason: null }],
    validation_issues: [],
    media_plan: structuredClone(platform === "telegram" ? [] : platform === "instagram" ? [mediaWire] : platform === "x" ? [{ ...mediaWire, role: "post" }] : [{ ...mediaWire, role: "hero" }]),
    source_media: [{
      id: ids.media,
      kind: "image",
      mime_type: "image/jpeg",
      width: 1200,
      height: 800,
      duration_seconds: null,
      byte_length: 1234,
      checksum_sha256: "c".repeat(64),
      fetch_status: "downloaded",
      available: true,
      role: "hero",
      order: 1,
    }],
    approval_state: "pending_review",
    approval_note: null,
    approved_at: null,
    created_by: "generation",
    origin: "generation",
    provider_profile: null,
    resolved_model: null,
    prompt_version: null,
    created_at: "2026-07-13T08:00:00Z",
  }
}
