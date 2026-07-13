import type { JobFilters } from "@/features/jobs/types"
import type { TelegramDraftFilters } from "@/features/automations/telegram-types"
import type { StoryFilters } from "@/lib/editorial-types"

export const queryKeys = {
  dashboardSummary: ["dashboard-summary"] as const,
  sources: ["sources"] as const,
  source: (id: string) => ["sources", id] as const,
  runs: ["ingest-runs"] as const,
  contentItems: ["content-items"] as const,
  media: ["media-assets"] as const,
  dashboardSnapshot: ["dashboard-snapshot"] as const,
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
  telegramDrafts: (filters: TelegramDraftFilters = {}) => ["telegram", "drafts", filters] as const,
  telegramDraft: (id: string) => ["telegram", "drafts", id] as const,
  telegramPublishJob: (id: string) => ["telegram", "publish-jobs", id] as const,
  brandProfiles: ["settings", "brand-profiles"] as const,
  promptTemplates: ["settings", "prompt-templates"] as const,
  promptVersions: (templateId: string) => ["settings", "prompt-templates", templateId, "versions"] as const,
  aiProviderProfiles: ["settings", "ai-provider-profiles"] as const,
  editorialProviderOptions: ["settings", "ai-provider-profiles", "editorial-options"] as const,
  editorialBrandOptions: ["settings", "brand-profiles", "editorial-options"] as const,
  editorialPromptOptions: ["settings", "prompt-templates", "editorial-options"] as const,
  stories: (filters: StoryFilters = {}) => ["stories", filters] as const,
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

export const editorialQueryKeys = {
  editorialProviderOptions: queryKeys.editorialProviderOptions,
  editorialBrandOptions: queryKeys.editorialBrandOptions,
  editorialPromptOptions: queryKeys.editorialPromptOptions,
  stories: queryKeys.stories,
  story: queryKeys.story,
  evidence: queryKeys.evidence,
  researchRuns: queryKeys.researchRuns,
  contentPacks: queryKeys.contentPacks,
  contentPack: queryKeys.contentPack,
  variantRevisions: queryKeys.variantRevisions,
}
