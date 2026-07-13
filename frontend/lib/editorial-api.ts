import { apiRequest } from "./http"
import type { AIProviderOption, BrandOption, EditorialState, EvidenceDetail, JobAccepted, PromptVersionOption, ResearchDisposition, ResearchRunDetail, StoryDetail, StoryFilters, StoryPage, StorySummary } from "./editorial-types"

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
  const supported = templates.filter((item) => item.purpose_key === "canonical_story" || item.purpose_key === "telegram_pack")
  const versions = await Promise.all(supported.map(async (template) => ({
    purpose: template.purpose_key as PromptVersionOption["purpose"],
    rows: await apiRequest<Array<{ id: string; version: number; checksum_sha256: string; is_active: boolean }>>(`/prompt-templates/${template.id}/versions`),
  })))
  return versions.flatMap(({ purpose, rows }) => rows.map((row) => ({ id: row.id, purpose, version: row.version, checksumSha256: row.checksum_sha256, active: row.is_active })))
}
export async function requestContentPack(storyId: string, input: { brandProfileId: string; generationProviderProfileId: string; canonicalPromptTemplateVersionId: string; platformPromptTemplateVersionId: string; researchMode?: "off" | "manual" | "auto_if_incomplete"; researchProviderProfileId?: string | null }): Promise<JobAccepted> {
  const row = await jsonPost<{ job_id: string; status: string; deduplicated: boolean }>(`/stories/${storyId}/content-packs`, { brand_profile_id: input.brandProfileId, platform: "telegram", generation_provider_profile_id: input.generationProviderProfileId, canonical_prompt_template_version_id: input.canonicalPromptTemplateVersionId, platform_prompt_template_version_id: input.platformPromptTemplateVersionId, research_mode: input.researchMode ?? "off", research_provider_profile_id: input.researchProviderProfileId ?? null })
  return mapJob(row)
}

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
function mapJob(row: { job_id: string; status: string; deduplicated: boolean }): JobAccepted { return { jobId: row.job_id, status: row.status, deduplicated: row.deduplicated } }
function jsonInit(method: string, body: unknown): RequestInit { return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) } }
function jsonPost<T>(path: string, body: unknown): Promise<T> { return apiRequest<T>(path, jsonInit("POST", body)) }
function validateCompleteness(value: ResearchDisposition["completeness"]): ResearchDisposition["completeness"] {
  if (!Number.isInteger(value.score) || value.score < 0 || value.score > 100) throw new Error("Invalid completeness score")
  return value
}
