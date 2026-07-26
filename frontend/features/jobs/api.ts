import type { components } from "@/lib/api/generated"
import { apiRequest } from "@/lib/http"

import type {
  EnqueueIngestInput,
  JobAccepted,
  JobFilters,
  JobSummary,
  WorkflowJob,
  WorkflowJobDetail,
} from "./types"

type Schemas = components["schemas"]

export async function getJobs(filters: JobFilters = {}): Promise<WorkflowJob[]> {
  const params = new URLSearchParams()
  for (const status of filters.statuses ?? []) {
    params.append("status", status)
  }
  if (filters.jobType) params.set("job_type", filters.jobType)
  if (filters.errorClass) params.set("error_class", filters.errorClass)
  if (filters.limit !== undefined) params.set("limit", String(filters.limit))

  const query = params.toString()
  return (await apiRequest<Schemas["JobListOut"]>(`/jobs${query ? `?${query}` : ""}`)).items.map(jobOut)
}

export async function getJob(id: string): Promise<WorkflowJobDetail> {
  const row = await apiRequest<WorkflowJobDetail>(`/jobs/${encodeURIComponent(id)}`)
  return { ...jobOut(row), payload: row.payload, result: row.result, events: row.events.map(eventOut) }
}

export async function getJobSummary(): Promise<JobSummary> {
  return apiRequest<JobSummary>("/jobs/summary")
}

export async function retryJob(id: string): Promise<WorkflowJob> {
  return jobOut(await apiRequest<WorkflowJob>(`/jobs/${encodeURIComponent(id)}/retry`, {
    method: "POST",
  }))
}

export async function cancelJob(id: string): Promise<WorkflowJob> {
  return jobOut(await apiRequest<WorkflowJob>(`/jobs/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  }))
}

export async function enqueueIngest(input: EnqueueIngestInput): Promise<JobAccepted> {
  return apiRequest<JobAccepted>("/ingest/run", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      request_id: input.requestId,
      platforms: input.platforms,
      source_ids: input.sourceIds,
    }),
  })
}

function jobOut(row: WorkflowJob): WorkflowJob {
  const {
    attempt_count, created_at, error_class, error_code, error_message, finished_at,
    id, job_type, max_attempts, origin, pause_sensitive, priority, progress,
    progress_message, scheduled_for, started_at, status, updated_at,
  } = row
  return {
    attempt_count, created_at, error_class, error_code, error_message, finished_at,
    id, job_type, max_attempts, origin, pause_sensitive, priority, progress,
    progress_message, scheduled_for, started_at, status, updated_at,
  }
}

function eventOut(row: Schemas["JobEventOut"]): Schemas["JobEventOut"] {
  const { actor, created_at, event_data, event_type, id } = row
  return { actor, created_at, event_data, event_type, id }
}
