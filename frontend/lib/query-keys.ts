import type { JobFilters } from "@/features/jobs/types"

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
}
