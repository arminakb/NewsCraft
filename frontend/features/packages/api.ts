import { ApiError, apiRequest } from "@/lib/http"
import type {
  BlogPayload,
  CitationRef,
  CompleteExportArtifact,
  ContentPackage,
  ExportArtifact,
  ExportFileIdentity,
  ExportJobAccepted,
  ExportJobStatus,
  ExportManifest,
  ExportOutcome,
  ExportRequest,
  ExportVariantIdentity,
  ExpiredExportArtifact,
  InstagramPayload,
  ManualPublicationPlan,
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
const EXPORT_FORMATS = ["json", "markdown", "html", "zip"] as const
const EXPORT_JOB_STATUSES = ["queued", "running", "succeeded", "failed", "needs_review", "cancelled"] as const
const MANUAL_PLAN_STATUSES = ["planned", "ready", "manual_published", "cancelled"] as const
const MANUAL_CHECKLIST_IDS = {
  instagram: ["copy_reviewed", "citations_verified", "media_and_alt_text_ready", "platform_requirements_rechecked"],
  x: ["thread_order_reviewed", "citations_and_links_verified", "media_and_alt_text_ready", "platform_requirements_rechecked"],
  blog: ["article_reviewed", "citations_and_links_verified", "seo_fields_reviewed", "media_and_alt_text_ready"],
} as const

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

export async function getRenderedRevisionHtml(
  revisionId: string,
  expectedContentHash: string,
): Promise<string> {
  const expectedHash = sha256(expectedContentHash, "Invalid rendered revision HTML content hash")
  const row = exactObject(
    await apiRequest<unknown>(`/platform-variant-revisions/${revisionId}/rendered-html`),
    ["revision_id", "content_hash", "platform", "html"],
    "Invalid rendered revision HTML",
  )
  const returnedRevisionId = uuid(row.revision_id, "Invalid rendered revision HTML")
  const returnedContentHash = sha256(row.content_hash, "Invalid rendered revision HTML")
  const platform = oneOf(row.platform, ["blog"] as const, "Invalid rendered revision HTML")
  const html = string(row.html, "Invalid rendered revision HTML")
  if (
    returnedRevisionId !== revisionId
    || returnedContentHash !== expectedHash
    || platform !== "blog"
  ) throw new Error("Rendered revision HTML identity mismatch")
  return html
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

export async function createContentPackageExport(
  packId: string,
  input: ExportRequest,
): Promise<ExportJobAccepted> {
  if (!input.formats.length || new Set(input.formats).size !== input.formats.length) {
    throw new Error("Export formats must be non-empty and unique")
  }
  if (input.formats.some((format) => !EXPORT_FORMATS.includes(format))) {
    throw new Error("Invalid export format")
  }
  if (input.revisionIds !== null && (!input.revisionIds.length || new Set(input.revisionIds).size !== input.revisionIds.length)) {
    throw new Error("Export revision IDs must be non-empty and unique")
  }
  const response = decodeExportJobAccepted(await apiRequest<unknown>(
    `/content-packs/${packId}/exports`,
    jsonInit("POST", {
      content_pack_id: packId,
      revision_ids: input.revisionIds,
      formats: input.formats,
      include_media: input.includeMedia,
    }),
  ))
  return response
}

export async function getExportOutcome(exportId: string): Promise<ExportOutcome> {
  const outcome = decodeExportOutcome(await apiRequest<unknown>(`/exports/${exportId}`))
  if (outcome.exportId !== exportId) throw new Error("Export response identity mismatch")
  return outcome
}

export async function createManualPublicationPlan(
  revisionId: string,
  scheduledFor: string,
  displayTimezone: string,
): Promise<ManualPublicationPlan> {
  const requestedSchedule = timestamp(scheduledFor, "Invalid manual publication schedule")
  const plan = decodeManualPublicationPlan(await apiRequest<unknown>(
    "/manual-publication-plans",
    jsonInit("POST", {
      revision_id: revisionId,
      scheduled_for: requestedSchedule,
      display_timezone: displayTimezone,
    }),
  ))
  if (
    plan.platformVariantRevisionId !== revisionId
    || plan.displayTimezone !== displayTimezone
    || new Date(plan.scheduledFor).getTime() !== new Date(requestedSchedule).getTime()
  ) {
    throw new Error("Manual publication plan response identity mismatch")
  }
  return plan
}

export async function getManualPublicationPlanForRevision(
  revisionId: string,
): Promise<ManualPublicationPlan | null> {
  try {
    const plan = decodeManualPublicationPlan(await apiRequest<unknown>(
      `/platform-variant-revisions/${revisionId}/manual-publication-plan`,
    ))
    if (plan.platformVariantRevisionId !== revisionId) {
      throw new Error("Manual publication plan response identity mismatch")
    }
    return plan
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 404) return null
    throw caught
  }
}

export async function updateManualPublicationChecklist(
  planId: string,
  checklistState: Record<string, boolean>,
): Promise<ManualPublicationPlan> {
  if (!Object.keys(checklistState).length || Object.values(checklistState).some((value) => typeof value !== "boolean")) {
    throw new Error("Manual publication checklist update is invalid")
  }
  const plan = decodeManualPublicationPlan(await apiRequest<unknown>(
    `/manual-publication-plans/${planId}/checklist`,
    jsonInit("PATCH", { checklist_state: checklistState }),
  ))
  if (plan.id !== planId) throw new Error("Manual publication checklist response identity mismatch")
  return plan
}

export async function markManualPublicationPublished(
  planId: string,
  input: { externalUrl: string | null; note: string | null },
): Promise<ManualPublicationPlan> {
  if (
    input.externalUrl !== null
    && (input.externalUrl.length > 2_048 || /\s/.test(input.externalUrl))
  ) throw new Error("Invalid manual publication URL")
  if (input.externalUrl !== null) httpUrl(input.externalUrl, "Invalid manual publication URL")
  const plan = decodeManualPublicationPlan(await apiRequest<unknown>(
    `/manual-publication-plans/${planId}/mark-published`,
    jsonInit("POST", { external_url: input.externalUrl, note: input.note }),
  ))
  if (plan.id !== planId || plan.status !== "manual_published") {
    throw new Error("Manual publication completion response identity mismatch")
  }
  return plan
}

function decodeExportJobAccepted(value: unknown): ExportJobAccepted {
  const row = exactObject(value, ["job_id", "status", "deduplicated"], "Invalid export job response")
  return {
    jobId: uuid(row.job_id, "Invalid export job response"),
    status: oneOf(row.status, EXPORT_JOB_STATUSES, "Invalid export job response"),
    deduplicated: boolean(row.deduplicated, "Invalid export job response"),
  }
}

export function decodeExportOutcome(value: unknown): ExportOutcome {
  const message = "Invalid export outcome"
  const row = exactObject(value, [
    "export_id",
    "status",
    "finished_at",
    "artifact",
    "downloads",
    "error_code",
    "error_message",
  ], message)
  const exportId = uuid(row.export_id, message)
  const status: ExportJobStatus = oneOf(row.status, EXPORT_JOB_STATUSES, message)
  const artifact = row.artifact === null ? null : decodeExportArtifact(row.artifact)
  const downloads = stringArray(row.downloads, message, false)
  if (artifact !== null && artifact.exportId !== exportId) throw new Error(message)
  const expectedPrefix = `/exports/${exportId}/download/`
  if (downloads.some((download) => !download.startsWith(expectedPrefix) || download.length === expectedPrefix.length)) {
    throw new Error(message)
  }
  downloads.forEach((download) => safeRelativePath(download.slice(expectedPrefix.length), message))
  const finishedAt = nullableTimestamp(row.finished_at, message)
  const errorCode = nullableString(row.error_code, message)
  const errorMessage = nullableString(row.error_message, message, true)
  if (status === "succeeded") {
    if (artifact === null || finishedAt === null) throw new Error(message)
    if (artifact.state === "expired") {
      if (downloads.length !== 0 || errorCode !== "export_expired") throw new Error(message)
    } else if (downloads.length === 0 || errorCode === "export_expired") {
      throw new Error(message)
    }
  } else if (artifact !== null || downloads.length !== 0) {
    throw new Error(message)
  } else if (errorCode === "export_expired") {
    throw new Error(message)
  }
  return {
    exportId,
    status,
    finishedAt,
    artifact,
    downloads,
    errorCode,
    errorMessage,
  }
}

function decodeExportArtifact(value: unknown): ExportArtifact {
  const message = "Invalid export artifact"
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(message)
  const state = (value as Record<string, unknown>).state
  if (state === "expired") return decodeExpiredExportArtifact(value)
  if (state !== "complete") throw new Error(message)
  return decodeCompleteExportArtifact(value)
}

function decodeCompleteExportArtifact(value: unknown): CompleteExportArtifact {
  const message = "Invalid export artifact"
  const row = exactObject(value, [
    "export_id",
    "content_pack_id",
    "state",
    "manifest_file",
    "manifest_sha256",
    "archive_file",
    "archive_sha256",
    "manifest",
  ], message)
  const artifact: CompleteExportArtifact = {
    exportId: uuid(row.export_id, message),
    contentPackId: uuid(row.content_pack_id, message),
    state: oneOf(row.state, ["complete"] as const, message),
    manifestFile: oneOf(row.manifest_file, ["manifest.json"] as const, message),
    manifestSha256: sha256(row.manifest_sha256, message),
    archiveFile: row.archive_file === null ? null : oneOf(row.archive_file, ["bundle.zip"] as const, message),
    archiveSha256: row.archive_sha256 === null ? null : sha256(row.archive_sha256, message),
    manifest: decodeExportManifest(row.manifest),
  }
  if (
    artifact.manifest.contentPackId !== artifact.contentPackId
    || (artifact.archiveFile === null) !== (artifact.archiveSha256 === null)
  ) throw new Error(message)
  return artifact
}

function decodeExpiredExportArtifact(value: unknown): ExpiredExportArtifact {
  const message = "Invalid export artifact"
  const row = exactObject(value, [
    "export_id",
    "content_pack_id",
    "state",
    "expired_at",
  ], message)
  return {
    exportId: uuid(row.export_id, message),
    contentPackId: uuid(row.content_pack_id, message),
    state: oneOf(row.state, ["expired"] as const, message),
    expiredAt: timestamp(row.expired_at, message),
  }
}

function decodeExportManifest(value: unknown): ExportManifest {
  const message = "Invalid export manifest"
  const row = exactObject(value, [
    "schema_version",
    "content_pack_id",
    "story_revision_id",
    "created_at",
    "variants",
    "files",
  ], message)
  const variants = array(row.variants, message).map(decodeExportVariantIdentity)
  const files = array(row.files, message).map(decodeExportFileIdentity)
  const variantKeys = variants.map((item) => `${item.platform}:${item.revisionId}`)
  const fileNames = files.map((item) => item.fileName)
  if (
    new Set(variantKeys).size !== variantKeys.length
    || new Set(fileNames).size !== fileNames.length
    || files.some((file) => !variantKeys.includes(`${file.platform}:${file.revisionId}`))
  ) throw new Error(message)
  return {
    schemaVersion: oneOf(row.schema_version, ["newscraft-export-v1"] as const, message),
    contentPackId: uuid(row.content_pack_id, message),
    storyRevisionId: uuid(row.story_revision_id, message),
    createdAt: timestamp(row.created_at, message),
    variants,
    files,
  }
}

function decodeExportVariantIdentity(value: unknown): ExportVariantIdentity {
  const message = "Invalid export variant identity"
  const row = exactObject(value, [
    "platform",
    "platform_variant_id",
    "revision_id",
    "content_hash",
    "approval_state",
    "evidence_urls",
  ], message)
  const evidenceUrls = array(row.evidence_urls, message).map((item) => httpUrl(item, message))
  if (evidenceUrls.length !== new Set(evidenceUrls).size || evidenceUrls.some((item, index) => index > 0 && evidenceUrls[index - 1] > item)) {
    throw new Error(message)
  }
  return {
    platform: decodePlatform(row.platform),
    platformVariantId: uuid(row.platform_variant_id, message),
    revisionId: uuid(row.revision_id, message),
    contentHash: sha256(row.content_hash, message),
    approvalState: oneOf(row.approval_state, ["approved"] as const, message),
    evidenceUrls,
  }
}

function decodeExportFileIdentity(value: unknown): ExportFileIdentity {
  const message = "Invalid export file identity"
  const row = exactObject(value, [
    "file_name",
    "sha256",
    "byte_length",
    "kind",
    "platform",
    "revision_id",
    "media_asset_id",
  ], message)
  const fileName = safeRelativePath(row.file_name, message)
  const kind = oneOf(row.kind, ["json", "markdown", "html", "media"] as const, message)
  const mediaAssetId = nullableUuid(row.media_asset_id, message)
  if ((kind === "media") !== (mediaAssetId !== null)) throw new Error(message)
  return {
    fileName,
    sha256: sha256(row.sha256, message),
    byteLength: nonNegativeInteger(row.byte_length, message),
    kind,
    platform: decodePlatform(row.platform),
    revisionId: uuid(row.revision_id, message),
    mediaAssetId,
  }
}

export function decodeManualPublicationPlan(value: unknown): ManualPublicationPlan {
  const message = "Invalid manual publication plan"
  const row = exactObject(value, [
    "id",
    "platform_variant_revision_id",
    "platform",
    "scheduled_for",
    "display_timezone",
    "status",
    "checklist_state",
    "external_url",
    "operator_note",
    "completed_at",
    "created_at",
    "updated_at",
  ], message)
  const platform = oneOf(row.platform, ["instagram", "x", "blog"] as const, message)
  const status = oneOf(row.status, MANUAL_PLAN_STATUSES, message)
  const checklistState = decodeManualChecklistState(platform, row.checklist_state)
  const complete = Object.values(checklistState).every(Boolean)
  const externalUrl = row.external_url === null ? null : httpUrl(row.external_url, message)
  const operatorNote = nullableString(row.operator_note, message, true)
  const completedAt = nullableTimestamp(row.completed_at, message)
  if (
    ((status === "ready" || status === "manual_published") && !complete)
    || (status === "planned" && complete)
    || (status === "manual_published" && completedAt === null)
    || (status !== "manual_published" && (externalUrl !== null || operatorNote !== null || completedAt !== null))
  ) throw new Error(message)
  return {
    id: uuid(row.id, message),
    platformVariantRevisionId: uuid(row.platform_variant_revision_id, message),
    platform,
    scheduledFor: timestamp(row.scheduled_for, message),
    displayTimezone: string(row.display_timezone, message),
    status,
    checklistState,
    externalUrl,
    operatorNote,
    completedAt,
    createdAt: timestamp(row.created_at, message),
    updatedAt: timestamp(row.updated_at, message),
  }
}

function decodeManualChecklistState(
  platform: "instagram" | "x" | "blog",
  value: unknown,
): Record<string, boolean> {
  const message = "Invalid manual publication checklist"
  const keys = MANUAL_CHECKLIST_IDS[platform]
  const row = exactObject(value, keys, message)
  return Object.fromEntries(keys.map((key) => [key, boolean(row[key], message)]))
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

function timestamp(value: unknown, message: string): string {
  const text = string(value, message)
  const parsed = new Date(text)
  if (Number.isNaN(parsed.getTime()) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(text)) throw new Error(message)
  return text
}

function nullableTimestamp(value: unknown, message: string): string | null {
  return value === null ? null : timestamp(value, message)
}

function safeRelativePath(value: unknown, message: string): string {
  const path = string(value, message)
  const parts = path.split("/")
  if (
    path.startsWith("/")
    || path.includes("\\")
    || parts.some((part) => !part || part === "." || part === ".." || !/^[A-Za-z0-9._-]+$/.test(part))
  ) throw new Error(message)
  return path
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
