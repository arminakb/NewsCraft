import { apiRequest } from "@/lib/http"

import type {
  EnqueueIngestInput,
  JobAccepted,
  JobErrorClass,
  JobEvent,
  JobFilters,
  JobOrigin,
  JobStatus,
  JobSummary,
  WorkflowJob,
  WorkflowJobDetail,
} from "./types"

type BackendWorkflowJob = {
  id: string
  job_type: string
  status: JobStatus
  origin: JobOrigin
  priority: number
  pause_sensitive: boolean
  scheduled_for: string
  attempt_count: number
  max_attempts: number
  progress: number
  progress_message: string | null
  error_class: JobErrorClass | null
  error_code: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

type BackendJobEvent = {
  id: string
  event_type: string
  actor: string
  event_data: Record<string, unknown>
  created_at: string
}

type BackendWorkflowJobDetail = BackendWorkflowJob & {
  payload: Record<string, unknown>
  result: Record<string, unknown>
  events: BackendJobEvent[]
}

export async function getJobs(filters: JobFilters = {}): Promise<WorkflowJob[]> {
  const params = new URLSearchParams()
  for (const status of filters.statuses ?? []) {
    params.append("status", status)
  }
  if (filters.jobType) params.set("job_type", filters.jobType)
  if (filters.errorClass) params.set("error_class", filters.errorClass)
  if (filters.limit !== undefined) params.set("limit", String(filters.limit))

  const query = params.toString()
  const response = await apiRequest<{ items: BackendWorkflowJob[] }>(`/jobs${query ? `?${query}` : ""}`)
  return response.items.map(mapWorkflowJob)
}

export async function getJob(id: string): Promise<WorkflowJobDetail> {
  const row = await apiRequest<BackendWorkflowJobDetail>(`/jobs/${encodeURIComponent(id)}`)
  return {
    ...mapWorkflowJob(row),
    payload: row.payload,
    result: row.result,
    events: row.events.map(mapJobEvent),
  }
}

export async function getJobSummary(): Promise<JobSummary> {
  const row = await apiRequest<{
    queued: number
    running: number
    attention: number
    succeeded_today: number
  }>("/jobs/summary")
  return {
    queued: row.queued,
    running: row.running,
    attention: row.attention,
    succeededToday: row.succeeded_today,
  }
}

export async function retryJob(id: string): Promise<WorkflowJob> {
  const row = await apiRequest<BackendWorkflowJob>(`/jobs/${encodeURIComponent(id)}/retry`, {
    method: "POST",
  })
  return mapWorkflowJob(row)
}

export async function cancelJob(id: string): Promise<WorkflowJob> {
  const row = await apiRequest<BackendWorkflowJob>(`/jobs/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  })
  return mapWorkflowJob(row)
}

export async function enqueueIngest(input: EnqueueIngestInput): Promise<JobAccepted> {
  const row = await apiRequest<{
    job_id: string
    status: JobStatus
    deduplicated: boolean
  }>("/ingest/run", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      request_id: input.requestId,
      platforms: input.platforms,
      source_ids: input.sourceIds,
    }),
  })
  return {
    jobId: row.job_id,
    status: row.status,
    deduplicated: row.deduplicated,
  }
}

function mapWorkflowJob(row: BackendWorkflowJob): WorkflowJob {
  return {
    id: row.id,
    jobType: row.job_type,
    status: row.status,
    origin: row.origin,
    priority: row.priority,
    pauseSensitive: row.pause_sensitive,
    scheduledFor: row.scheduled_for,
    attemptCount: row.attempt_count,
    maxAttempts: row.max_attempts,
    progress: row.progress,
    progressMessage: row.progress_message,
    errorClass: row.error_class,
    errorCode: row.error_code,
    errorMessage: row.error_message,
    startedAt: row.started_at,
    finishedAt: row.finished_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  }
}

function mapJobEvent(row: BackendJobEvent): JobEvent {
  return {
    id: row.id,
    eventType: row.event_type,
    actor: row.actor,
    eventData: row.event_data,
    createdAt: row.created_at,
  }
}
