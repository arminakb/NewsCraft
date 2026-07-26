import type { Platform } from "@/features/packages/types"
import type { components } from "@/lib/api/generated"
import { camelize } from "@/lib/camelize"
import { apiRequest } from "@/lib/http"

import type {
  AIProviderOption,
  Completeness,
  ContentPackRequestSummary,
  EvidenceDetail,
  ResearchRunDetail,
} from "./types"

type BackendEvidence = {
  id: string
  evidence_key: string
  title: string | null
  content_text: string
  content_sha256: string
  source_url: string | null
  authors: string[]
  published_at: string | null
  captured_at: string
}
type BackendResearchRun = {
  id: string
  story_id: string
  requested_mode: "manual" | "auto_if_incomplete"
  status: string
  provider: { id: string; name: string; provider_type: string } | null
  budget: { max_queries?: number; max_pages?: number; max_elapsed_seconds?: number } | null
  requested_model?: string | null
  resolved_model?: string | null
  evidence_set_hash?: string | null
  completeness?: Completeness | null
  attempts?: Array<{ id: string; attempt_number: number; status: string; error_message?: string | null }>
  sources?: Array<{ id: string; url: string; title?: string | null; content_sha256: string; published_at?: string | null }>
  result_revision_id?: string | null
}
type BackendPack = {
  id: string
  story_id: string
  story_revision_id: string
  brand_profile_id: string
  status: string
  created_at: string
  updated_at: string
  variants: Array<{ id: string; platform: Platform }>
}
type BackendContentPackRequest = {
  id: string
  job_id: string | null
  story_id: string
  status: string
  last_failure: string | null
  created_at: string
  updated_at: string
  pack: BackendPack | null
}

export async function getStoryCompleteness(id: string): Promise<Completeness> {
  const row = await apiRequest<{ completeness: Completeness }>(`/stories/${encodeURIComponent(id)}`)
  return validateCompleteness(row.completeness)
}

export async function getStoryEvidence(id: string): Promise<EvidenceDetail[]> {
  const rows = await apiRequest<BackendEvidence[]>(`/stories/${encodeURIComponent(id)}/evidence`)
  return camelize(rows)
}

export async function getResearchRuns(storyId: string): Promise<ResearchRunDetail[]> {
  const row = await apiRequest<{ items: BackendResearchRun[] }>(
    `/stories/${encodeURIComponent(storyId)}/research-runs`,
  )
  return row.items.map(mapResearchRun)
}

export async function getAIProviderOptions(): Promise<AIProviderOption[]> {
  const rows = await apiRequest<components["schemas"]["AIProviderProfileOut"][]>("/ai-provider-profiles")
  return rows.map((row) => ({
    id: row.id,
    name: row.name,
    providerType: providerType(row.provider_type),
    defaultModel: row.default_model,
    capabilities: {
      generation: row.capabilities.generation ?? false,
      research: row.capabilities.research ?? false,
    },
    unavailableReason: row.unavailability_codes.length
      ? row.unavailability_codes.join(", ").replaceAll("_", " ")
      : null,
  }))
}

export async function getContentPackRequests(): Promise<ContentPackRequestSummary[]> {
  const rows = await apiRequest<BackendContentPackRequest[]>("/content-pack-requests")
  return camelize(rows)
}

function mapResearchRun(row: BackendResearchRun): ResearchRunDetail {
  return {
    id: row.id,
    storyId: row.story_id,
    requestedMode: row.requested_mode,
    status: row.status,
    provider: row.provider
      ? { id: row.provider.id, name: row.provider.name, providerType: row.provider.provider_type }
      : null,
    budget: {
      maxQueries: row.budget?.max_queries ?? 0,
      maxPages: row.budget?.max_pages ?? 0,
      maxElapsedSeconds: row.budget?.max_elapsed_seconds ?? 0,
    },
    requestedModel: row.requested_model ?? null,
    resolvedModel: row.resolved_model ?? null,
    evidenceSetHash: row.evidence_set_hash ?? null,
    completeness: row.completeness ? validateCompleteness(row.completeness) : null,
    attempts: (row.attempts ?? []).map((item) => ({
      id: item.id,
      attemptNumber: item.attempt_number,
      status: item.status,
      errorMessage: item.error_message ?? null,
    })),
    sources: (row.sources ?? []).map((item) => ({
      id: item.id,
      url: item.url,
      title: item.title ?? null,
      contentSha256: item.content_sha256,
      publishedAt: item.published_at ?? null,
    })),
    resultStoryRevisionId: row.result_revision_id ?? null,
  }
}

function providerType(value: string): AIProviderOption["providerType"] {
  if (value === "fake" || value === "openrouter" || value === "codex") return value
  throw new Error(`Unsupported provider type: ${value}`)
}

function validateCompleteness(value: Completeness): Completeness {
  if (!Number.isInteger(value.score) || value.score < 0 || value.score > 100) {
    throw new Error("Invalid completeness score")
  }
  return value
}
