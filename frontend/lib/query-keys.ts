import type { JobFilters } from "@/features/jobs/types"
import type { HistoryFilters } from "@/features/operations/types"

export const queryKeys = {
  sources: ["sources"] as const,
  source: (id: string) => ["sources", id] as const,
  diagnostics: ["diagnostics"] as const,
  jobs: (filters: JobFilters = {}) => ["jobs", filters] as const,
  job: (id: string) => ["jobs", id] as const,
  jobSummary: ["jobs", "summary"] as const,
  automationControl: ["automation-control"] as const,
  telegramOptions: ["telegram", "options"] as const,
  telegramSources: ["telegram", "sources"] as const,
  telegramDestinations: ["telegram", "destinations"] as const,
  telegramRoutes: ["telegram", "routes"] as const,
  telegramRoute: (id: string) => ["telegram", "routes", id] as const,
  telegramDispatches: (routeId: string) => ["telegram", "routes", routeId, "dispatches"] as const,
  telegramPublicationContext: (id: string) => ["telegram", "publication-context", id] as const,
  telegramPublicationOutcomes: ["telegram", "publication-outcomes"] as const,
  telegramPublishJob: (id: string) => ["telegram", "publish-jobs", id] as const,
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
  calendar: (start: string, end: string, timezone: string) => ["calendar", start, end, timezone] as const,
}

export const operationsQueryKeys = {
  diagnostics: ["operations", "diagnostics"] as const,
  history: (filters: HistoryFilters) => ["operations", "history", filters] as const,
  reconciliations: ["publications", "reconciliation"] as const,
  retentionPolicy: ["operations", "retention-policy"] as const,
  retentionPreview: (policyHash: string) => ["operations", "retention-preview", policyHash] as const,
}
