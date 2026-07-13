import { apiRequest } from "@/lib/http"
import type {
  BlogPayload,
  CitationRef,
  ContentPackage,
  InstagramPayload,
  ManualPlatformEditPayload,
  ManualPlatformEditRequest,
  MediaAssignment,
  Platform,
  PlatformRevision,
  SourceMedia,
  TelegramButton,
  TelegramPayload,
  ValidationIssue,
  ValidationResult,
  XPayload,
} from "./types"

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256_PATTERN = /^[0-9a-f]{64}$/
const LOCATOR_PATTERN = /^chars:(0|[1-9]\d*)-(0|[1-9]\d*)$/
const PLATFORMS = ["telegram", "instagram", "x", "blog"] as const

const REVISION_KEYS = [
  "id",
  "platform",
  "platform_variant_id",
  "content_pack_id",
  "story_id",
  "parent_revision_id",
  "generation_attempt_id",
  "revision_number",
  "content",
  "content_hash",
  "evidence_map",
  "manual_checklist",
  "validation_results",
  "validation_issues",
  "media_plan",
  "source_media",
  "approval_state",
  "approval_note",
  "approved_at",
  "created_by",
  "origin",
  "provider_profile",
  "resolved_model",
  "prompt_version",
  "created_at",
] as const

export async function getPackage(packId: string): Promise<ContentPackage> {
  return decodeContentPackage(await apiRequest<unknown>(`/content-packs/${packId}`))
}

export async function getPlatformRevisions(variantId: string): Promise<PlatformRevision[]> {
  const value = await apiRequest<unknown>(`/platform-variants/${variantId}/revisions`)
  if (!Array.isArray(value)) throw new Error("Invalid platform revision list")
  const revisions = value.map(decodePlatformRevision)
  if (revisions.some((revision) => revision.variantId !== variantId)) throw new Error("Platform revision list identity mismatch")
  return revisions
}

export async function getPlatformRevision(revisionId: string): Promise<PlatformRevision> {
  const revision = decodePlatformRevision(await apiRequest<unknown>(`/platform-variant-revisions/${revisionId}`))
  if (revision.id !== revisionId) throw new Error("Platform revision identity mismatch")
  return revision
}

export async function saveManualPlatformRevision<P extends "instagram" | "x" | "blog">(
  variantId: string,
  input: ManualPlatformEditRequest<P>,
): Promise<PlatformRevision> {
  const expectedEvidence = orderedDistinctContentCitations(input.payload as ManualPlatformEditPayload)
  if (!sameCitationArray(input.evidenceMap, expectedEvidence)) {
    throw new Error("Manual edit evidence map does not match content citations")
  }
  const response = await apiRequest<unknown>(
    `/platform-variants/${variantId}/revisions`,
    jsonInit("POST", {
      base_revision_id: input.baseRevisionId,
      base_content_hash: input.baseContentHash,
      payload: encodeManualEditPayload(input.payload as ManualPlatformEditPayload),
      evidence_map: input.evidenceMap.map(encodeCitation),
      edit_note: input.editNote,
    }),
  )
  const revision = decodePlatformRevision(response)
  if (revision.variantId !== variantId || revision.platform !== input.payload.platform) {
    throw new Error("Manual edit response identity mismatch")
  }
  return revision
}

export async function approvePlatformRevision(
  revisionId: string,
  input: { expectedContentHash: string; note: string | null },
): Promise<PlatformRevision> {
  const response = await apiRequest<unknown>(
    `/platform-variant-revisions/${revisionId}/approve`,
    jsonInit("POST", { expected_content_hash: input.expectedContentHash, note: input.note }),
  )
  const revision = decodePlatformRevision(response)
  if (revision.id !== revisionId || revision.approvalState !== "approved") throw new Error("Approval response identity mismatch")
  return revision
}

export async function rejectPlatformRevision(
  revisionId: string,
  input: { expectedContentHash: string; reason: string },
): Promise<PlatformRevision> {
  const response = await apiRequest<unknown>(
    `/platform-variant-revisions/${revisionId}/reject`,
    jsonInit("POST", { expected_content_hash: input.expectedContentHash, note: input.reason }),
  )
  const revision = decodePlatformRevision(response)
  if (revision.id !== revisionId || revision.approvalState !== "rejected") throw new Error("Rejection response identity mismatch")
  return revision
}

export function decodeContentPackage(value: unknown): ContentPackage {
  const row = exactObject(value, [
    "id",
    "story_id",
    "story_revision_id",
    "brand_profile_id",
    "status",
    "created_at",
    "updated_at",
    "variants",
  ], "Invalid content package")
  const id = uuid(row.id, "Invalid content package id")
  const storyId = uuid(row.story_id, "Invalid content package story id")
  const variants = array(row.variants, "Invalid content package variants").map((value) => {
    const variant = exactObject(value, ["id", "platform", "current_revision"], "Invalid content package variant")
    const variantId = uuid(variant.id, "Invalid content package variant id")
    const platform = decodePlatform(variant.platform)
    const currentRevision = variant.current_revision === null ? null : decodePlatformRevision(variant.current_revision)
    if (
      currentRevision !== null
      && (currentRevision.platform !== platform || currentRevision.variantId !== variantId || currentRevision.contentPackId !== id || currentRevision.storyId !== storyId)
    ) {
      throw new Error("Content package current revision identity mismatch")
    }
    return { id: variantId, platform, currentRevision }
  })
  return {
    id,
    storyId,
    storyRevisionId: uuid(row.story_revision_id, "Invalid content package story revision id"),
    brandProfileId: uuid(row.brand_profile_id, "Invalid content package brand id"),
    status: string(row.status, "Invalid content package status"),
    createdAt: string(row.created_at, "Invalid content package creation time"),
    updatedAt: string(row.updated_at, "Invalid content package update time"),
    variants,
  }
}

export function decodePlatformRevision(value: unknown): PlatformRevision {
  const row = exactObject(value, REVISION_KEYS, "Invalid platform revision")
  const platform = decodePlatform(row.platform)
  const payload = decodePlatformPayload(platform, row.content)
  const evidenceCitations = array(row.evidence_map, "Invalid revision evidence map").map(decodeCitation)
  const manualChecklist = stringArray(row.manual_checklist, "Invalid revision manual checklist", true)
  const validationResults = array(row.validation_results, "Invalid revision validation results").map(decodeValidationResult)
  const validation = array(row.validation_issues, "Invalid revision validation issues").map(decodeValidationIssue)
  const sourceMedia = array(row.source_media, "Invalid revision source media").map(decodeSourceMedia)
  const common = {
    id: uuid(row.id, "Invalid revision id"),
    variantId: uuid(row.platform_variant_id, "Invalid revision variant id"),
    contentPackId: uuid(row.content_pack_id, "Invalid revision content pack id"),
    storyId: uuid(row.story_id, "Invalid revision story id"),
    parentRevisionId: nullableUuid(row.parent_revision_id, "Invalid parent revision id"),
    generationAttemptId: nullableUuid(row.generation_attempt_id, "Invalid generation attempt id"),
    revisionNumber: positiveInteger(row.revision_number, "Invalid revision number"),
    contentHash: sha256(row.content_hash, "Invalid revision content hash"),
    evidenceCitations,
    manualChecklist,
    validationResults,
    validation,
    sourceMedia,
    approvalState: oneOf(row.approval_state, ["draft", "pending_review", "approved", "rejected"] as const, "Invalid revision approval state"),
    approvalNote: nullableString(row.approval_note, "Invalid revision approval note", true),
    approvedAt: nullableString(row.approved_at, "Invalid revision approval time"),
    createdBy: string(row.created_by, "Invalid revision creator"),
    origin: oneOf(row.origin, ["operator", "generation", "automation"] as const, "Invalid revision origin"),
    providerProfile: decodeProvider(row.provider_profile),
    resolvedModel: nullableString(row.resolved_model, "Invalid resolved model"),
    promptVersion: decodePromptVersion(row.prompt_version),
    createdAt: string(row.created_at, "Invalid revision creation time"),
  }

  if (platform === "telegram") {
    if (manualChecklist.length !== 0) throw new Error("Invalid Telegram manual checklist projection")
    return {
      ...common,
      platform,
      payload: payload as TelegramPayload,
      mediaPlan: array(row.media_plan, "Invalid Telegram media plan").map((item) => uuid(item, "Invalid Telegram media plan asset")),
    }
  }

  const manualPayload = payload as InstagramPayload | XPayload | BlogPayload
  if (!sameStringArray(manualChecklist, manualPayload.manualChecklist)) {
    throw new Error(`Invalid ${platform} manual checklist projection`)
  }
  const mediaPlan = array(row.media_plan, `Invalid ${platform} media plan`).map(decodeMediaAssignment)
  if (platform === "instagram") return { ...common, platform, payload: payload as InstagramPayload, mediaPlan }
  if (platform === "x") return { ...common, platform, payload: payload as XPayload, mediaPlan }
  return { ...common, platform, payload: payload as BlogPayload, mediaPlan }
}

function decodePlatformPayload(platform: Platform, value: unknown) {
  if (platform === "telegram") return decodeTelegramPayload(value)
  if (platform === "instagram") return decodeInstagramPayload(value)
  if (platform === "x") return decodeXPayload(value)
  return decodeBlogPayload(value)
}

function decodeTelegramPayload(value: unknown): TelegramPayload {
  const row = exactObject(value, [
    "body",
    "parse_mode",
    "buttons",
    "source_item_id",
    "source_url",
    "media_policy",
    "media_asset_ids",
    "direction",
    "dry_run",
  ], "Invalid telegram revision content")
  return {
    body: string(row.body, "Invalid telegram revision content"),
    parseMode: oneOf(row.parse_mode, ["HTML"] as const, "Invalid telegram revision content"),
    buttons: array(row.buttons, "Invalid telegram revision content").map(decodeTelegramButton),
    sourceItemId: nullableUuid(row.source_item_id, "Invalid telegram revision content"),
    sourceUrl: nullableHttpUrl(row.source_url, "Invalid telegram revision content"),
    mediaPolicy: oneOf(row.media_policy, ["preserve", "omit", "replace_manually"] as const, "Invalid telegram revision content"),
    mediaAssetIds: array(row.media_asset_ids, "Invalid telegram revision content").map((item) => uuid(item, "Invalid telegram revision content")),
    direction: oneOf(row.direction, ["ltr", "rtl"] as const, "Invalid telegram revision content"),
    dryRun: boolean(row.dry_run, "Invalid telegram revision content"),
  }
}

function decodeInstagramPayload(value: unknown): InstagramPayload {
  const row = exactObject(value, [
    "hook",
    "caption",
    "cta",
    "hashtags",
    "alt_text",
    "carousel",
    "citations",
    "manual_checklist",
  ], "Invalid instagram revision content")
  return {
    hook: string(row.hook, "Invalid instagram revision content"),
    caption: string(row.caption, "Invalid instagram revision content"),
    cta: string(row.cta, "Invalid instagram revision content"),
    hashtags: stringArray(row.hashtags, "Invalid instagram revision content", true),
    altText: string(row.alt_text, "Invalid instagram revision content"),
    carousel: array(row.carousel, "Invalid instagram revision content").map((value) => {
      const slide = exactObject(value, ["order", "headline", "body", "media"], "Invalid instagram revision content")
      return {
        order: positiveInteger(slide.order, "Invalid instagram revision content"),
        headline: string(slide.headline, "Invalid instagram revision content"),
        body: string(slide.body, "Invalid instagram revision content"),
        media: decodeMediaAssignment(slide.media),
      }
    }),
    citations: array(row.citations, "Invalid instagram revision content").map(decodeCitation),
    manualChecklist: stringArray(row.manual_checklist, "Invalid instagram revision content", true),
  }
}

function decodeXPayload(value: unknown): XPayload {
  const row = exactObject(value, ["mode", "posts", "link_strategy", "manual_checklist"], "Invalid x revision content")
  return {
    mode: oneOf(row.mode, ["single", "thread"] as const, "Invalid x revision content"),
    posts: array(row.posts, "Invalid x revision content").map((value) => {
      const post = exactObject(value, ["order", "text", "media", "citations"], "Invalid x revision content")
      return {
        order: positiveInteger(post.order, "Invalid x revision content"),
        text: string(post.text, "Invalid x revision content"),
        media: array(post.media, "Invalid x revision content").map(decodeMediaAssignment),
        citations: array(post.citations, "Invalid x revision content").map(decodeCitation),
      }
    }),
    linkStrategy: oneOf(row.link_strategy, ["first_post", "last_post", "each_post", "no_link"] as const, "Invalid x revision content"),
    manualChecklist: stringArray(row.manual_checklist, "Invalid x revision content", true),
  }
}

function decodeBlogPayload(value: unknown): BlogPayload {
  const row = exactObject(value, [
    "title",
    "slug",
    "excerpt",
    "body_markdown",
    "headings",
    "citations",
    "tags",
    "seo_description",
    "hero_media",
    "canonical_sources",
    "manual_checklist",
  ], "Invalid blog revision content")
  return {
    title: string(row.title, "Invalid blog revision content"),
    slug: string(row.slug, "Invalid blog revision content"),
    excerpt: string(row.excerpt, "Invalid blog revision content"),
    bodyMarkdown: string(row.body_markdown, "Invalid blog revision content"),
    headings: stringArray(row.headings, "Invalid blog revision content", true),
    citations: array(row.citations, "Invalid blog revision content").map(decodeCitation),
    tags: stringArray(row.tags, "Invalid blog revision content", true),
    seoDescription: string(row.seo_description, "Invalid blog revision content"),
    heroMedia: row.hero_media === null ? null : decodeMediaAssignment(row.hero_media),
    canonicalSources: array(row.canonical_sources, "Invalid blog revision content").map((item) => httpUrl(item, "Invalid blog revision content")),
    manualChecklist: stringArray(row.manual_checklist, "Invalid blog revision content", true),
  }
}

function decodeTelegramButton(value: unknown): TelegramButton {
  const row = exactObject(value, ["text", "url"], "Invalid Telegram button")
  return { text: string(row.text, "Invalid Telegram button"), url: httpUrl(row.url, "Invalid Telegram button") }
}

function decodeCitation(value: unknown): CitationRef {
  const row = exactObject(value, ["evidence_snapshot_id", "evidence_key", "source_url", "locator", "excerpt_sha256"], "Invalid evidence citation")
  const locator = string(row.locator, "Invalid evidence citation")
  if (!LOCATOR_PATTERN.test(locator)) throw new Error("Invalid evidence citation")
  return {
    evidenceSnapshotId: uuid(row.evidence_snapshot_id, "Invalid evidence citation"),
    evidenceKey: string(row.evidence_key, "Invalid evidence citation"),
    sourceUrl: nullableHttpUrl(row.source_url, "Invalid evidence citation"),
    locator,
    excerptSha256: sha256(row.excerpt_sha256, "Invalid evidence citation"),
  }
}

function decodeMediaAssignment(value: unknown): MediaAssignment {
  const row = exactObject(value, ["media_asset_id", "role", "order", "alt_text", "manual_brief", "image_prompt"], "Invalid media assignment")
  return {
    mediaAssetId: nullableUuid(row.media_asset_id, "Invalid media assignment"),
    role: oneOf(row.role, ["hero", "slide", "post", "inline"] as const, "Invalid media assignment"),
    order: positiveInteger(row.order, "Invalid media assignment"),
    altText: string(row.alt_text, "Invalid media assignment"),
    manualBrief: nullableString(row.manual_brief, "Invalid media assignment", true),
    imagePrompt: nullableString(row.image_prompt, "Invalid media assignment", true),
  }
}

function decodeSourceMedia(value: unknown): SourceMedia {
  const row = exactObject(value, [
    "id",
    "kind",
    "mime_type",
    "width",
    "height",
    "duration_seconds",
    "byte_length",
    "checksum_sha256",
    "fetch_status",
    "available",
    "role",
    "order",
  ], "Invalid source media")
  return {
    id: uuid(row.id, "Invalid source media"),
    kind: string(row.kind, "Invalid source media"),
    mimeType: nullableString(row.mime_type, "Invalid source media"),
    width: nullableNonNegativeInteger(row.width, "Invalid source media"),
    height: nullableNonNegativeInteger(row.height, "Invalid source media"),
    durationSeconds: nullableString(row.duration_seconds, "Invalid source media"),
    byteLength: nullableNonNegativeInteger(row.byte_length, "Invalid source media"),
    checksumSha256: row.checksum_sha256 === null ? null : sha256(row.checksum_sha256, "Invalid source media"),
    fetchStatus: string(row.fetch_status, "Invalid source media"),
    available: boolean(row.available, "Invalid source media"),
    role: string(row.role, "Invalid source media"),
    order: nonNegativeInteger(row.order, "Invalid source media"),
  }
}

function decodeValidationResult(value: unknown): ValidationResult {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid revision validation result")
  const row = value as Record<string, unknown>
  const keys = Object.keys(row)
  if (!keys.includes("gate") || !keys.includes("ok") || keys.some((key) => !["gate", "ok", "reason"].includes(key))) {
    throw new Error("Invalid revision validation result")
  }
  return {
    gate: string(row.gate, "Invalid revision validation result"),
    ok: boolean(row.ok, "Invalid revision validation result"),
    reason: "reason" in row ? nullableString(row.reason, "Invalid revision validation result", true) : null,
  }
}

function decodeValidationIssue(value: unknown): ValidationIssue {
  const row = exactObject(value, ["code", "path", "message", "severity"], "Invalid revision validation issue")
  return {
    code: string(row.code, "Invalid revision validation issue"),
    path: string(row.path, "Invalid revision validation issue", true),
    message: string(row.message, "Invalid revision validation issue"),
    severity: oneOf(row.severity, ["error", "warning"] as const, "Invalid revision validation issue"),
  }
}

function decodeProvider(value: unknown) {
  if (value === null) return null
  const row = exactObject(value, ["id", "name", "provider_type"], "Invalid revision provider profile")
  return {
    id: uuid(row.id, "Invalid revision provider profile"),
    name: string(row.name, "Invalid revision provider profile"),
    providerType: string(row.provider_type, "Invalid revision provider profile"),
  }
}

function decodePromptVersion(value: unknown) {
  if (value === null) return null
  const row = exactObject(value, ["id", "version", "output_schema_version", "checksum_sha256"], "Invalid revision prompt version")
  return {
    id: uuid(row.id, "Invalid revision prompt version"),
    version: positiveInteger(row.version, "Invalid revision prompt version"),
    outputSchemaVersion: string(row.output_schema_version, "Invalid revision prompt version"),
    checksumSha256: sha256(row.checksum_sha256, "Invalid revision prompt version"),
  }
}

function encodeManualEditPayload(payload: ManualPlatformEditPayload) {
  if (payload.platform === "instagram") return { platform: payload.platform, content: encodeInstagramPayload(payload.content) }
  if (payload.platform === "x") return { platform: payload.platform, content: encodeXPayload(payload.content) }
  return { platform: payload.platform, content: encodeBlogPayload(payload.content) }
}

function encodeInstagramPayload(payload: InstagramPayload) {
  return {
    hook: payload.hook,
    caption: payload.caption,
    cta: payload.cta,
    hashtags: payload.hashtags,
    alt_text: payload.altText,
    carousel: payload.carousel.map((slide) => ({ order: slide.order, headline: slide.headline, body: slide.body, media: encodeMediaAssignment(slide.media) })),
    citations: payload.citations.map(encodeCitation),
    manual_checklist: payload.manualChecklist,
  }
}

function encodeXPayload(payload: XPayload) {
  return {
    mode: payload.mode,
    posts: payload.posts.map((post) => ({ order: post.order, text: post.text, media: post.media.map(encodeMediaAssignment), citations: post.citations.map(encodeCitation) })),
    link_strategy: payload.linkStrategy,
    manual_checklist: payload.manualChecklist,
  }
}

function encodeBlogPayload(payload: BlogPayload) {
  return {
    title: payload.title,
    slug: payload.slug,
    excerpt: payload.excerpt,
    body_markdown: payload.bodyMarkdown,
    headings: payload.headings,
    citations: payload.citations.map(encodeCitation),
    tags: payload.tags,
    seo_description: payload.seoDescription,
    hero_media: payload.heroMedia === null ? null : encodeMediaAssignment(payload.heroMedia),
    canonical_sources: payload.canonicalSources,
    manual_checklist: payload.manualChecklist,
  }
}

function encodeCitation(citation: CitationRef) {
  return {
    evidence_snapshot_id: citation.evidenceSnapshotId,
    evidence_key: citation.evidenceKey,
    source_url: citation.sourceUrl,
    locator: citation.locator,
    excerpt_sha256: citation.excerptSha256,
  }
}

function encodeMediaAssignment(media: MediaAssignment) {
  return {
    media_asset_id: media.mediaAssetId,
    role: media.role,
    order: media.order,
    alt_text: media.altText,
    manual_brief: media.manualBrief,
    image_prompt: media.imagePrompt,
  }
}

function orderedDistinctContentCitations(payload: ManualPlatformEditPayload): CitationRef[] {
  const citations = payload.platform === "x"
    ? payload.content.posts.flatMap((post) => post.citations)
    : payload.content.citations
  const seen = new Set<string>()
  return citations.filter((citation) => {
    const identity = citationIdentity(citation)
    if (seen.has(identity)) return false
    seen.add(identity)
    return true
  })
}

function sameCitationArray(left: CitationRef[], right: CitationRef[]): boolean {
  return left.length === right.length && left.every((citation, index) => citationIdentity(citation) === citationIdentity(right[index]))
}

function citationIdentity(citation: CitationRef): string {
  return JSON.stringify([
    citation.evidenceKey,
    citation.evidenceSnapshotId,
    citation.sourceUrl,
    citation.locator,
    citation.excerptSha256,
  ])
}

function decodePlatform(value: unknown): Platform {
  return oneOf(value, PLATFORMS, "Invalid platform")
}

function exactObject<const K extends string>(value: unknown, keys: readonly K[], message: string): Record<K, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(message)
  const row = value as Record<string, unknown>
  const actual = Object.keys(row)
  if (actual.length !== keys.length || actual.some((key) => !keys.includes(key as K))) throw new Error(message)
  return row as Record<K, unknown>
}

function array(value: unknown, message: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(message)
  return value
}

function string(value: unknown, message: string, allowEmpty = false): string {
  if (typeof value !== "string" || (!allowEmpty && value.trim().length === 0)) throw new Error(message)
  return value
}

function nullableString(value: unknown, message: string, allowEmpty = false): string | null {
  return value === null ? null : string(value, message, allowEmpty)
}

function stringArray(value: unknown, message: string, allowEmpty = false): string[] {
  return array(value, message).map((item) => string(item, message, allowEmpty))
}

function boolean(value: unknown, message: string): boolean {
  if (typeof value !== "boolean") throw new Error(message)
  return value
}

function positiveInteger(value: unknown, message: string): number {
  if (!Number.isInteger(value) || (value as number) < 1) throw new Error(message)
  return value as number
}

function nonNegativeInteger(value: unknown, message: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) throw new Error(message)
  return value as number
}

function nullableNonNegativeInteger(value: unknown, message: string): number | null {
  if (value === null) return null
  if (!Number.isInteger(value) || (value as number) < 0) throw new Error(message)
  return value as number
}

function uuid(value: unknown, message: string): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) throw new Error(message)
  return value
}

function nullableUuid(value: unknown, message: string): string | null {
  return value === null ? null : uuid(value, message)
}

function sha256(value: unknown, message: string): string {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) throw new Error(message)
  return value
}

function httpUrl(value: unknown, message: string): string {
  if (typeof value !== "string") throw new Error(message)
  try {
    const url = new URL(value)
    if (!(["http:", "https:"] as const).includes(url.protocol as "http:" | "https:") || url.username || url.password) throw new Error(message)
    return value
  } catch {
    throw new Error(message)
  }
}

function nullableHttpUrl(value: unknown, message: string): string | null {
  return value === null ? null : httpUrl(value, message)
}

function oneOf<const T extends readonly string[]>(value: unknown, choices: T, message: string): T[number] {
  if (typeof value !== "string" || !choices.includes(value)) throw new Error(message)
  return value as T[number]
}

function sameStringArray(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index])
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) }
}
