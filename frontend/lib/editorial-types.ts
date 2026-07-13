export type ResearchMode = "off" | "manual" | "auto_if_incomplete"
export type EditorialState = "inbox" | "shortlisted" | "rejected" | "drafted"

export type Completeness = { complete: boolean; score: number; reasons: string[] }
export type AIProviderOption = {
  id: string
  name: string
  providerType: "fake" | "openrouter" | "codex"
  defaultModel: string | null
  capabilities: { generation: boolean; research: boolean }
  unavailableReason: string | null
}
export type PromptVersionOption = {
  id: string
  purpose: "canonical_story" | "telegram_pack"
  version: number
  checksumSha256: string
  active: boolean
}
export type BrandOption = { id: string; name: string; isDefault: boolean }
export type StoryFilters = {
  search?: string
  editorialState?: EditorialState
  completeness?: "complete" | "incomplete"
  includeSuperseded?: boolean
  limit?: number
  cursor?: string
}
export type StorySummary = {
  id: string
  title: string
  evidenceCount: number
  latestEvidenceAt: string | null
  completeness: Completeness
  editorialState: EditorialState
  status: string
  primaryLanguage: string
  evidenceSetHash: string
  createdAt: string
  updatedAt: string
}
export type EvidenceDetail = {
  id: string
  evidenceKey: string
  title: string | null
  contentText: string
  contentSha256: string
  sourceUrl: string | null
  authors: string[]
  publishedAt: string | null
  capturedAt: string
}
export type StoryDetail = StorySummary & { evidence: EvidenceDetail[] }
export type StoryPage = { items: StorySummary[]; nextCursor: string | null }
export type JobAccepted = { jobId: string; status: string; deduplicated: boolean }
export type ResearchSourceDetail = { id: string; url: string; title: string | null; contentSha256: string; publishedAt: string | null }
export type ResearchRunDetail = {
  id: string
  storyId: string
  requestedMode: "manual" | "auto_if_incomplete"
  status: string
  provider: { id: string; name: string; providerType: string } | null
  budget: { maxQueries: number; maxPages: number; maxElapsedSeconds: number }
  requestedModel: string | null
  resolvedModel: string | null
  evidenceSetHash: string | null
  completeness: Completeness | null
  attempts: Array<{ id: string; attemptNumber: number; status: string; errorMessage: string | null }>
  sources: ResearchSourceDetail[]
  resultStoryRevisionId: string | null
}
export type ResearchDisposition = { disposition: "skipped" | "complete_without_research" | "enqueued"; runId: string | null; jobId: string | null; completeness: Completeness }
