import {
  cancelJob,
  enqueueIngest,
  getJob,
  getJobs,
  getJobSummary,
  retryJob,
} from "@/features/jobs/api"
import { queryKeys } from "@/lib/query-keys"

const backendJob = {
  id: "11111111-1111-4111-8111-111111111111",
  job_type: "ingest.collect",
  status: "failed",
  origin: "manual",
  priority: 7,
  pause_sensitive: false,
  scheduled_for: "2026-07-12T08:00:00Z",
  attempt_count: 2,
  max_attempts: 3,
  progress: 45,
  progress_message: "Fetching sources",
  error_class: "retryable",
  error_code: "ingest_partial",
  error_message: "One source failed",
  started_at: "2026-07-12T08:01:00Z",
  finished_at: "2026-07-12T08:02:00Z",
  created_at: "2026-07-12T07:59:00Z",
  updated_at: "2026-07-12T08:02:00Z",
  lease_owner: "must-not-cross-the-api-boundary",
}

describe("job API", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("maps every public job field and sends repeated status filters", async () => {
    const fetchSpy = stubFetch({ items: [backendJob] })

    await expect(
      getJobs({ statuses: ["failed", "needs_review"], limit: 25 })
    ).resolves.toEqual([
      {
        id: "11111111-1111-4111-8111-111111111111",
        job_type: "ingest.collect",
        status: "failed",
        origin: "manual",
        priority: 7,
        pause_sensitive: false,
        scheduled_for: "2026-07-12T08:00:00Z",
        attempt_count: 2,
        max_attempts: 3,
        progress: 45,
        progress_message: "Fetching sources",
        error_class: "retryable",
        error_code: "ingest_partial",
        error_message: "One source failed",
        started_at: "2026-07-12T08:01:00Z",
        finished_at: "2026-07-12T08:02:00Z",
        created_at: "2026-07-12T07:59:00Z",
        updated_at: "2026-07-12T08:02:00Z",
      },
    ])
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/jobs?status=failed&status=needs_review&limit=25",
      undefined
    )
  })

  it("maps job detail payload, result, and newest-first events", async () => {
    const fetchSpy = stubFetch({
      ...backendJob,
      payload: { source_ids: ["source-1"] },
      result: { fetched: 4 },
      events: [
        {
          id: "33333333-3333-4333-8333-333333333333",
          event_type: "job.failed",
          actor: "worker-1",
          event_data: { error_code: "ingest_partial" },
          created_at: "2026-07-12T08:02:00Z",
        },
        {
          id: "22222222-2222-4222-8222-222222222222",
          event_type: "job.claimed",
          actor: "worker-1",
          event_data: { attempt: 2 },
          created_at: "2026-07-12T08:01:00Z",
        },
      ],
    })

    const detail = await getJob("11111111-1111-4111-8111-111111111111")

    expect(detail).toEqual(
      expect.objectContaining({
        job_type: "ingest.collect",
        payload: { source_ids: ["source-1"] },
        result: { fetched: 4 },
        events: [
          {
            id: "33333333-3333-4333-8333-333333333333",
            event_type: "job.failed",
            actor: "worker-1",
            event_data: { error_code: "ingest_partial" },
            created_at: "2026-07-12T08:02:00Z",
          },
          {
            id: "22222222-2222-4222-8222-222222222222",
            event_type: "job.claimed",
            actor: "worker-1",
            event_data: { attempt: 2 },
            created_at: "2026-07-12T08:01:00Z",
          },
        ],
      })
    )
    expect(detail).not.toHaveProperty("lease_owner")
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/backend/jobs/11111111-1111-4111-8111-111111111111",
      undefined
    )
  })

  it("maps the job summary", async () => {
    stubFetch({ queued: 3, running: 2, attention: 4, succeeded_today: 9 })

    await expect(getJobSummary()).resolves.toEqual({
      queued: 3,
      running: 2,
      attention: 4,
      succeeded_today: 9,
    })
  })

  it.each([
    ["retry", retryJob],
    ["cancel", cancelJob],
  ] as const)("posts the %s transition and maps its job", async (transition, request) => {
    const fetchSpy = stubFetch(backendJob)

    await expect(request(backendJob.id)).resolves.toEqual(
      expect.objectContaining({ id: backendJob.id, job_type: "ingest.collect" })
    )
    expect(fetchSpy).toHaveBeenCalledWith(`/api/backend/jobs/${backendJob.id}/${transition}`, {
      method: "POST",
    })
  })

  it("enqueues ingestion with a caller-provided request UUID", async () => {
    const fetchSpy = stubFetch({
      job_id: backendJob.id,
      status: "queued",
      deduplicated: false,
    })

    await expect(
      enqueueIngest({
        requestId: "44444444-4444-4444-8444-444444444444",
        platforms: ["rss"],
        sourceIds: ["source-1"],
      })
    ).resolves.toEqual({
      job_id: backendJob.id,
      status: "queued",
      deduplicated: false,
    })
    expect(fetchSpy).toHaveBeenCalledWith("/api/backend/ingest/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        request_id: "44444444-4444-4444-8444-444444444444",
        platforms: ["rss"],
        source_ids: ["source-1"],
      }),
    })
  })

  it("provides stable serializable job query keys", () => {
    const filters = { statuses: ["failed", "needs_review"] as const, limit: 25 }

    expect(queryKeys.jobs(filters)).toEqual(["jobs", filters])
    expect(queryKeys.job(backendJob.id)).toEqual(["jobs", backendJob.id])
    expect(queryKeys.jobSummary).toEqual(["jobs", "summary"])
  })
})

function stubFetch(payload: unknown) {
  const fetchSpy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  })
  vi.stubGlobal("fetch", fetchSpy)
  return fetchSpy
}
