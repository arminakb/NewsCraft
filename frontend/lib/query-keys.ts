import type { JobFilters } from "@/features/jobs/types"
import type { HistoryFilters } from "@/features/operations/types"
import type { ArticleFilters, ArticleSort } from "@/features/articles/types"
import type {
  AutomationListFilters,
  AutomationResourceRequest,
  AutomationRunFilters,
} from "@/features/automations/automation-types"

export const queryKeys = {
  sources: ["sources"] as const,
  sourcesPage: (scope: string, offset = 0) => ["sources", "page", scope, offset] as const,
  sourcesCount: ["sources", "count"] as const,
  sourcesToday: ["sources", "today"] as const,
  source: (id: string) => ["sources", id] as const,
  sourceDetailIdle: ["sources", "detail"] as const,
  sourceCollections: ["source-collections"] as const,
  sourceCollection: (id: string) => ["source-collections", id] as const,
  sourceCollectionSources: (id: string, offset = 0, search = "") => [
    "source-collections",
    id,
    "sources",
    offset,
    search,
  ] as const,
  unassignedSources: (offset = 0, search = "") => ["source-collections", "unassigned", offset, search] as const,
  unassignedSourcesCount: ["source-collections", "unassigned", "count"] as const,
  sourceCollectionAvailableSources: (collectionId: string, offset = 0, search = "") => [
    "source-collections",
    collectionId,
    "available",
    offset,
    search,
  ] as const,
  sourceCollectionAllRuns: (collectionId: string) => ["source-collections", collectionId, "runs"] as const,
  sourceCollectionRun: (collectionId: string, runId: string) => [
    "source-collections",
    collectionId,
    "runs",
    runId,
  ] as const,
  sourceCollectionRuns: (collectionId: string, limit = 3, offset = 0) => [
    "source-collections",
    collectionId,
    "runs",
    "list",
    limit,
    offset,
  ] as const,
  sourceCollectionRunHistory: (collectionId: string, pageSize = 25, offset = 0) => [
    "source-collections",
    collectionId,
    "runs",
    "history",
    pageSize,
    offset,
  ] as const,
  diagnostics: ["diagnostics"] as const,
  ingestRunsToday: (limit: number) => ["ingest-runs", "today", limit] as const,
  jobs: (filters: JobFilters = {}) => ["jobs", filters] as const,
  job: (id: string) => ["jobs", id] as const,
  jobSummary: ["jobs", "summary"] as const,
  automationControl: ["automation-control"] as const,
  dateTimeSettings: ["settings", "date-time"] as const,
  notifications: ["notifications"] as const,
  article: (id: string) => ["articles", "detail", id] as const,
  articlesToday: (limit: number) => ["articles", "today", limit] as const,
  articlePage: (params: {
    identity: string
    sort: ArticleSort
    filters: ArticleFilters
    query: string
    collectionId: string | null
    page: number
    cursor: string | null
  }) => ["articles", "feed-page", params] as const,
  articlePages: ["articles", "feed-page"] as const,
  articleCollections: ["articles", "collections"] as const,
  articleFacets: ["articles", "facets"] as const,
  feedSummary: ["feed", "summary"] as const,
  telegramOptions: ["telegram", "options"] as const,
  telegramSources: ["telegram", "sources"] as const,
  telegramDestinations: ["telegram", "destinations"] as const,
  telegramRoutes: ["telegram", "routes"] as const,
  telegramRoute: (id: string) => ["telegram", "routes", id] as const,
  telegramDispatches: (routeId: string) => ["telegram", "routes", routeId, "dispatches"] as const,
  telegramPublicationContext: (id: string) => ["telegram", "publication-context", id] as const,
  telegramPublicationOutcomes: ["telegram", "publication-outcomes"] as const,
  telegramPublishJob: (id: string) => ["telegram", "publish-jobs", id] as const,
  automations: (filters: AutomationListFilters = {}) => ["automations", filters] as const,
  automation: (id: string) => ["automations", id] as const,
  automationVersions: (id: string) => ["automations", id, "versions"] as const,
  automationVersion: (id: string, version: number) => ["automations", id, "versions", version] as const,
  automationNodeCatalog: ["automations", "node-catalog"] as const,
  automationResourceCatalog: (automationId: string | undefined, resources: AutomationResourceRequest[] = []) => [
    "automations",
    "resource-catalog",
    automationId,
    resources,
  ] as const,
  automationTemplates: ["automations", "templates"] as const,
  automationRuns: (id: string, filters: AutomationRunFilters = {}) => ["automations", id, "runs", filters] as const,
  automationRun: (id: string) => ["automation-runs", id] as const,
  brandProfiles: ["settings", "brand-profiles"] as const,
  promptTemplates: ["settings", "prompt-templates"] as const,
  promptVersions: (templateId: string) => ["settings", "prompt-templates", templateId, "versions"] as const,
  aiProviderProfiles: ["settings", "ai-provider-profiles"] as const,
  llmProviders: ["settings", "llm-providers"] as const,
  telegramProxies: ["settings", "telegram-proxies"] as const,
  codexConnections: ["settings", "codex-connections"] as const,
  codexActivity: ["settings", "codex-activity"] as const,
  editorialProviderOptions: ["settings", "ai-provider-profiles", "editorial-options"] as const,
  editorialBrandOptions: ["settings", "brand-profiles", "editorial-options"] as const,
  story: (id: string) => ["stories", id] as const,
  evidence: (storyId: string) => ["stories", storyId, "evidence"] as const,
  researchRuns: (storyId: string) => ["stories", storyId, "research-runs"] as const,
  contentPacks: ["content-packs"] as const,
  contentPackRequests: ["content-pack-requests"] as const,
  contentPack: (id: string) => ["content-packs", id] as const,
  variantRevisions: (variantId: string) => ["platform-variants", variantId, "revisions"] as const,
  variantRevision: (revisionId: string) => ["platform-variant-revisions", revisionId] as const,
}

export const packageQueryKeys = {
  export: (id: string) => ["exports", id] as const,
  manualPlan: (id: string) => ["manual-publication-plans", id] as const,
  manualPlanForRevision: (revisionId: string) => ["manual-publication-plans", "revision", revisionId] as const,
}

export const operationsQueryKeys = {
  diagnostics: ["operations", "diagnostics"] as const,
  health: ["operations", "health"] as const,
  history: (filters: HistoryFilters) => ["operations", "history", filters] as const,
  reconciliations: ["publications", "reconciliation"] as const,
  retentionPolicy: ["operations", "retention-policy"] as const,
  retentionPreview: (policyHash: string) => ["operations", "retention-preview", policyHash] as const,
}
