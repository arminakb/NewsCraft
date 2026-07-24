import { apiRequest } from "./http"
import type { Platform } from "@/features/packages/types"
import type { AIProviderOption, BrandOption, ContentPackDetail, ContentPackRequestSummary, ContentPackSummary, EditorialState, EvidenceDetail, JobAccepted, PromptVersionOption, ResearchDisposition, ResearchRunDetail, StoryDetail, StoryFilters, StoryPage, StorySummary, TelegramButton, VariantRevision } from "./editorial-types"

type BackendSummary = { id: string; title: string; status: string; primary_language: string; evidence_count: number; latest_evidence_at: string | null; completeness: { complete: boolean; score: number; reasons: string[] }; evidence_set_hash: string; created_at: string; updated_at: string }
type BackendEvidence = { id: string; evidence_key: string; title: string | null; content_text: string; content_sha256: string; source_url: string | null; authors?: string[]; published_at: string | null; captured_at: string }

export async function getStories(filters: StoryFilters = {}): Promise<StoryPage> {
  const query = new URLSearchParams()
  if (filters.search?.trim()) query.set("search", filters.search.trim())
  if (filters.editorialState) query.set("editorial_state", filters.editorialState)
  if (filters.completeness) query.set("completeness", filters.completeness)
  if (filters.includeSuperseded) query.set("include_superseded", "true")
  query.set("limit", String(filters.limit ?? 50))
  if (filters.cursor) query.set("cursor", filters.cursor)
  const row = await apiRequest<{ items: BackendSummary[]; next_cursor: string | null }>(`/stories?${query}`)
  return { items: row.items.map(mapStory), nextCursor: row.next_cursor }
}
export async function getStory(id: string): Promise<StoryDetail> {
  const [story, evidence] = await Promise.all([apiRequest<BackendSummary>(`/stories/${id}`), getStoryEvidence(id)])
  return { ...mapStory(story), evidence }
}
export async function getStoryEvidence(id: string): Promise<EvidenceDetail[]> {
  return (await apiRequest<BackendEvidence[]>(`/stories/${id}/evidence`)).map(mapEvidence)
}
export async function createManualStory(input: { kind: "url"; url: string; title: string | null } | { kind: "text"; title: string; text: string; sourceLabel: string; sourceUrl: string | null }): Promise<JobAccepted> {
  const body = input.kind === "url" ? input : { kind: "text", title: input.title, text: input.text, source_label: input.sourceLabel, source_url: input.sourceUrl }
  return mapJob(await jsonPost<{ job_id: string; status: string; deduplicated: boolean }>("/stories/manual", body))
}
export async function groupPendingStories(input: { limit: number }): Promise<JobAccepted> {
  return mapJob(await jsonPost<{ job_id: string; status: string; deduplicated: boolean }>("/stories/group-pending", input))
}
export async function setStoryEditorialState(id: string, state: Exclude<EditorialState, "drafted">): Promise<StorySummary> {
  return mapStory(await apiRequest<BackendSummary>(`/stories/${id}/editorial-state`, jsonInit("PATCH", { state })))
}
export async function bulkSetStoryEditorialState(ids: string[], state: Exclude<EditorialState, "drafted">): Promise<StorySummary[]> {
  const row = await jsonPost<{ items: BackendSummary[] }>("/stories/bulk-editorial-state", { story_ids: ids, state })
  return row.items.map(mapStory)
}
export async function requestResearch(storyId: string, input: { mode: "manual" | "auto_if_incomplete"; depth: "standard" | "deep"; providerProfileId: string; queryHint?: string | null }): Promise<ResearchDisposition> {
  const row = await jsonPost<{ disposition: ResearchDisposition["disposition"]; run_id: string | null; job_id: string | null; completeness: ResearchDisposition["completeness"] }>(`/stories/${storyId}/research-runs`, { mode: input.mode, depth: input.depth, provider_profile_id: input.providerProfileId, query_hint: input.queryHint ?? null })
  return { disposition: row.disposition, runId: row.run_id, jobId: row.job_id, completeness: row.completeness }
}
export async function getResearchRuns(storyId: string): Promise<ResearchRunDetail[]> {
  const row = await apiRequest<{ items: BackendResearchRun[] }>(`/stories/${storyId}/research-runs`)
  return row.items.map(mapRun)
}
export async function getResearchRun(runId: string): Promise<ResearchRunDetail> { return mapRun(await apiRequest<BackendResearchRun>(`/research-runs/${runId}`)) }
export async function getAIProviderOptions(): Promise<AIProviderOption[]> {
  const rows = await apiRequest<Array<{ id: string; name: string; provider_type: AIProviderOption["providerType"]; default_model: string | null; capabilities: AIProviderOption["capabilities"]; unavailability_codes: string[] }>>("/ai-provider-profiles")
  return rows.map((row) => ({ id: row.id, name: row.name, providerType: row.provider_type, defaultModel: row.default_model, capabilities: row.capabilities, unavailableReason: row.unavailability_codes.length ? row.unavailability_codes.join(", ").replaceAll("_", " ") : null }))
}
export async function getBrandOptions(): Promise<BrandOption[]> {
  const rows = await apiRequest<Array<{ id: string; name: string; is_default: boolean }>>("/brand-profiles")
  return rows.map((row) => ({ id: row.id, name: row.name, isDefault: row.is_default }))
}
export async function getPromptVersionOptions(): Promise<PromptVersionOption[]> {
  const templates = await apiRequest<Array<{ id: string; purpose_key: string }>>("/prompt-templates")
  const purposes: PromptVersionOption["purpose"][] = ["canonical_story", "telegram_pack", "instagram_pack", "x_pack", "blog_pack"]
  const supported = templates.filter((item): item is { id: string; purpose_key: PromptVersionOption["purpose"] } => purposes.includes(item.purpose_key as PromptVersionOption["purpose"]))
  const versions = await Promise.all(supported.map(async (template) => ({
    purpose: template.purpose_key as PromptVersionOption["purpose"],
    rows: await apiRequest<Array<{ id: string; version: number; checksum_sha256: string; is_active: boolean }>>(`/prompt-templates/${template.id}/versions`),
  })))
  return versions.flatMap(({ purpose, rows }) => rows.map((row) => ({ id: row.id, purpose, version: row.version, checksumSha256: row.checksum_sha256, active: row.is_active })))
}
type ContentPackRequestBase = { brandProfileId?: string; generationProviderProfileId: string; researchMode?: "off" | "manual" | "auto_if_incomplete"; researchProviderProfileId?: string | null; researchRunId?: string | null }
export type RequestContentPackInput = ContentPackRequestBase & (
  | { platforms: Platform[]; canonicalPromptTemplateVersionId?: never; platformPromptTemplateVersionId?: never }
  | { platforms?: never; canonicalPromptTemplateVersionId: string; platformPromptTemplateVersionId: string }
)
export async function requestContentPack(storyId: string, input: RequestContentPackInput): Promise<JobAccepted> {
  const research = { research_mode: input.researchMode ?? "off", research_provider_profile_id: input.researchProviderProfileId ?? null, research_run_id: input.researchRunId ?? null }
  const profile = input.brandProfileId ? { brand_profile_id: input.brandProfileId } : {}
  const body = "platforms" in input && input.platforms
    ? { ...profile, platforms: input.platforms, generation_provider_profile_id: input.generationProviderProfileId, ...research }
    : { ...profile, platform: "telegram", generation_provider_profile_id: input.generationProviderProfileId, canonical_prompt_template_version_id: input.canonicalPromptTemplateVersionId, platform_prompt_template_version_id: input.platformPromptTemplateVersionId, ...research }
  const row = await jsonPost<{ job_id: string; status: string; deduplicated: boolean }>(`/stories/${storyId}/content-packs`, body)
  return mapJob(row)
}

type BackendPack = { id: string; story_id: string; story_revision_id: string; brand_profile_id: string; status: string; created_at: string; updated_at: string; last_failure?: string | null; job_id?: string | null; variants: Array<{ id: string; platform: Platform }> }
type BackendRevision = { id: string; platform_variant_id: string; content_pack_id: string; story_id: string; parent_revision_id: string | null; generation_attempt_id: string | null; revision_number: number; content: Record<string, unknown>; content_hash: string; evidence_map: Array<Record<string, unknown>>; validation_results: unknown; approval_state: VariantRevision["approvalState"]; approval_note: string | null; approved_at: string | null; created_by: string; origin: VariantRevision["origin"]; created_at: string; provider_profile: { id: string; name: string; provider_type: string } | null; resolved_model: string | null }

export async function getContentPacks(): Promise<ContentPackSummary[]> { return (await apiRequest<BackendPack[]>("/content-packs")).map(mapPack) }
export async function getContentPackRequests(): Promise<ContentPackRequestSummary[]> {
  const rows = await apiRequest<Array<{ id: string; job_id: string | null; story_id: string; status: string; last_failure: string | null; created_at: string; updated_at: string; pack: BackendPack | null }>>("/content-pack-requests")
  return rows.map((row) => ({ id: row.id, jobId: row.job_id, storyId: row.story_id, status: row.status, lastFailure: row.last_failure, createdAt: row.created_at, updatedAt: row.updated_at, pack: row.pack ? mapPack(row.pack) : null }))
}
export async function getVariantRevisions(variantId: string): Promise<VariantRevision[]> { return (await apiRequest<BackendRevision[]>(`/platform-variants/${variantId}/revisions`)).map(mapRevision) }
export async function getVariantRevision(revisionId: string): Promise<VariantRevision> { return mapRevision(await apiRequest<BackendRevision>(`/platform-variant-revisions/${revisionId}`)) }
export async function getContentPack(packId: string): Promise<ContentPackDetail> {
  const pack = mapPack(await apiRequest<BackendPack>(`/content-packs/${packId}`))
  const revisionRows = await Promise.all(pack.variants.map(async (variant) => [variant.id, await getVariantRevisions(variant.id)] as const))
  return { ...pack, variantRevisions: Object.fromEntries(revisionRows) }
}
export type EditVariantInput = { baseRevisionId: string; baseContentHash: string; content: { body: string; parseMode: "HTML"; buttons: TelegramButton[] }; mediaAssetIds: string[]; editNote: string }
export function saveVariantRevision(variantId: string, input: EditVariantInput): Promise<VariantRevision> {
  return apiRequest<BackendRevision>(`/platform-variants/${variantId}/revisions`, jsonInit("POST", { base_revision_id: input.baseRevisionId, base_content_hash: input.baseContentHash, content: { body: input.content.body, parse_mode: input.content.parseMode, buttons: input.content.buttons }, media_asset_ids: input.mediaAssetIds, edit_note: input.editNote })).then(mapRevision)
}
export function approveVariantRevision(revisionId: string, input: { expectedContentHash: string; note: string | null }): Promise<VariantRevision> { return apiRequest<BackendRevision>(`/platform-variant-revisions/${revisionId}/approve`, jsonInit("POST", { expected_content_hash: input.expectedContentHash, note: input.note })).then(mapRevision) }
export function rejectVariantRevision(revisionId: string, input: { reason: string }, expectedContentHash = ""): Promise<VariantRevision> { return apiRequest<BackendRevision>(`/platform-variant-revisions/${revisionId}/reject`, jsonInit("POST", { expected_content_hash: expectedContentHash, note: input.reason })).then(mapRevision) }
export function regenerateVariant(variantId: string, input: { providerProfileId: string; platformPromptTemplateVersionId: string; instruction: string | null }): Promise<JobAccepted> { return jsonPost<{ job_id: string; status: string; deduplicated: boolean }>(`/platform-variants/${variantId}/regenerate`, { generation_provider_profile_id: input.providerProfileId, platform_prompt_template_version_id: input.platformPromptTemplateVersionId, instruction: input.instruction }).then(mapJob) }

type BackendResearchRun = {
  id: string; story_id: string; requested_mode: "manual" | "auto_if_incomplete"; status: string
  provider: { id: string; name: string; provider_type: string } | null
  budget: { max_queries?: number; max_pages?: number; max_elapsed_seconds?: number } | null
  requested_model?: string | null; resolved_model?: string | null; evidence_set_hash?: string | null
  completeness?: ResearchDisposition["completeness"] | null
  attempts?: Array<{ id: string; attempt_number: number; status: string; error_message?: string | null }>
  sources?: Array<{ id: string; url: string; title?: string | null; content_sha256: string; published_at?: string | null }>
  result_revision_id?: string | null
}
function mapRun(row: BackendResearchRun): ResearchRunDetail { return { id: row.id, storyId: row.story_id, requestedMode: row.requested_mode, status: row.status, provider: row.provider ? { id: row.provider.id, name: row.provider.name, providerType: row.provider.provider_type } : null, budget: { maxQueries: row.budget?.max_queries ?? 0, maxPages: row.budget?.max_pages ?? 0, maxElapsedSeconds: row.budget?.max_elapsed_seconds ?? 0 }, requestedModel: row.requested_model ?? null, resolvedModel: row.resolved_model ?? null, evidenceSetHash: row.evidence_set_hash ?? null, completeness: row.completeness ? validateCompleteness(row.completeness) : null, attempts: (row.attempts ?? []).map((item) => ({ id: item.id, attemptNumber: item.attempt_number, status: item.status, errorMessage: item.error_message ?? null })), sources: (row.sources ?? []).map((item) => ({ id: item.id, url: item.url, title: item.title ?? null, contentSha256: item.content_sha256, publishedAt: item.published_at ?? null })), resultStoryRevisionId: row.result_revision_id ?? null } }
function mapStory(row: BackendSummary): StorySummary { return { id: row.id, title: row.title, evidenceCount: row.evidence_count, latestEvidenceAt: row.latest_evidence_at, completeness: validateCompleteness(row.completeness), editorialState: row.status as EditorialState, status: row.status, primaryLanguage: row.primary_language, evidenceSetHash: row.evidence_set_hash, createdAt: row.created_at, updatedAt: row.updated_at } }
function mapEvidence(row: BackendEvidence): EvidenceDetail { return { id: row.id, evidenceKey: row.evidence_key, title: row.title, contentText: row.content_text, contentSha256: row.content_sha256, sourceUrl: row.source_url, authors: row.authors ?? [], publishedAt: row.published_at, capturedAt: row.captured_at } }
function mapPack(row: BackendPack): ContentPackSummary {
  if (typeof row.story_id !== "string" || !row.story_id) throw new Error("Content pack story identity is unavailable")
  return { id: row.id, storyId: row.story_id, storyRevisionId: row.story_revision_id, brandProfileId: row.brand_profile_id, status: row.status, createdAt: row.created_at, updatedAt: row.updated_at, lastFailure: row.last_failure ?? null, jobId: row.job_id ?? null, variants: row.variants }
}
function mapRevision(row: BackendRevision): VariantRevision {
  const content = decodeRevisionContent(row.content)
  if (!Array.isArray(row.validation_results) || row.validation_results.length === 0 || row.validation_results.some((item) => !isValidationResult(item))) throw new Error("Invalid revision validation result")
  if (!Array.isArray(row.evidence_map) || row.evidence_map.length === 0 || row.evidence_map.some((item) => !isEvidenceCitation(item))) throw new Error("Invalid revision evidence map")
  const validationResults = row.validation_results.map((item) => ({ gate: item.gate, ok: item.ok, reason: "reason" in item ? item.reason : null }))
  return { id: row.id, variantId: row.platform_variant_id, contentPackId: row.content_pack_id, storyId: row.story_id, parentRevisionId: row.parent_revision_id, generationAttemptId: row.generation_attempt_id, revisionNumber: row.revision_number, content, contentHash: row.content_hash, evidenceMap: row.evidence_map.map((item) => ({ evidenceSnapshotId: item.evidence_snapshot_id as string, evidenceKey: item.evidence_key as string, sourceUrl: item.source_url as string | null, locator: item.locator as string, excerptSha256: item.excerpt_sha256 as string })), validationResults, approvalState: row.approval_state, approvalNote: row.approval_note, approvedAt: row.approved_at, createdBy: row.created_by, origin: row.origin, createdAt: row.created_at, providerProfile: row.provider_profile ? { id: row.provider_profile.id, name: row.provider_profile.name, providerType: row.provider_profile.provider_type } : null, resolvedModel: row.resolved_model }
}
function isValidationResult(value: unknown): value is { gate: string; ok: boolean; reason?: string | null } { if (!value || typeof value !== "object") return false; const row = value as Record<string, unknown>; return typeof row.gate === "string" && row.gate.length > 0 && typeof row.ok === "boolean" && (!("reason" in row) || row.reason === null || typeof row.reason === "string") && Object.keys(row).every((key) => key === "gate" || key === "ok" || key === "reason") }
function decodeRevisionContent(value: Record<string, unknown>): VariantRevision["content"] {
  const keys = ["body", "parse_mode", "buttons", "source_item_id", "source_url", "media_policy", "media_asset_ids", "direction", "dry_run"]
  if (!value || typeof value !== "object" || Object.keys(value).some((key) => !keys.includes(key)) || typeof value.body !== "string" || !value.body.trim() || value.parse_mode !== "HTML" || !Array.isArray(value.buttons) || value.buttons.some((item) => !isTelegramButton(item)) || !(value.source_item_id === null || isUuid(value.source_item_id)) || !Array.isArray(value.media_asset_ids) || value.media_asset_ids.some((item) => !isUuid(item)) || !(value.source_url === null || (typeof value.source_url === "string" && isHttpUrl(value.source_url))) || !["preserve", "omit", "replace_manually"].includes(String(value.media_policy)) || !["ltr", "rtl"].includes(String(value.direction)) || typeof value.dry_run !== "boolean") throw new Error("Invalid revision content")
  return { body: value.body, parseMode: "HTML", buttons: value.buttons as TelegramButton[], mediaAssetIds: value.media_asset_ids as string[], sourceUrl: value.source_url as string | null, mediaPolicy: value.media_policy as string, direction: value.direction as "ltr" | "rtl", dryRun: value.dry_run }
}
function isTelegramButton(value: unknown): value is TelegramButton { if (!value || typeof value !== "object") return false; const row = value as Record<string, unknown>; return Object.keys(row).length === 2 && typeof row.text === "string" && row.text.trim().length > 0 && typeof row.url === "string" && isHttpUrl(row.url) }
function isEvidenceCitation(value: unknown): value is Record<string, string | null> { if (!value || typeof value !== "object") return false; const row = value as Record<string, unknown>; return Object.keys(row).length === 5 && isUuid(row.evidence_snapshot_id) && typeof row.evidence_key === "string" && row.evidence_key.length > 0 && (row.source_url === null || (typeof row.source_url === "string" && isHttpUrl(row.source_url))) && typeof row.locator === "string" && /^chars:(0|[1-9]\d*)-(0|[1-9]\d*)$/.test(row.locator) && typeof row.excerpt_sha256 === "string" && /^[0-9a-f]{64}$/.test(row.excerpt_sha256) }
function isUuid(value: unknown): value is string { return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value) }
function isHttpUrl(value: string): boolean { try { const url = new URL(value); return (url.protocol === "http:" || url.protocol === "https:") && !url.username && !url.password } catch { return false } }
function mapJob(row: { job_id: string; status: string; deduplicated: boolean }): JobAccepted { return { jobId: row.job_id, status: row.status, deduplicated: row.deduplicated } }
function jsonInit(method: string, body: unknown): RequestInit { return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) } }
function jsonPost<T>(path: string, body: unknown): Promise<T> { return apiRequest<T>(path, jsonInit("POST", body)) }
function validateCompleteness(value: ResearchDisposition["completeness"]): ResearchDisposition["completeness"] {
  if (!Number.isInteger(value.score) || value.score < 0 || value.score > 100) throw new Error("Invalid completeness score")
  return value
}
