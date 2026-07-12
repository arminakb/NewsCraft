"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useMemo, useRef, useState } from "react"

import { useNotices } from "@/components/providers/notice-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { cancelJob, getJob, getJobs, retryJob } from "@/features/jobs/api"
import { JobDetailPanel } from "@/features/jobs/job-detail-panel"
import { JobTable } from "@/features/jobs/job-table"
import type { JobFilters, JobStatus, WorkflowJob } from "@/features/jobs/types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

const filters: Array<{ label: string; statuses?: JobStatus[] }> = [
  { label: "All" },
  { label: "Queued", statuses: ["queued"] },
  { label: "Running", statuses: ["running"] },
  { label: "Attention", statuses: ["failed", "needs_review"] },
  { label: "Succeeded", statuses: ["succeeded"] },
  { label: "Cancelled", statuses: ["cancelled"] },
]

export function JobsPage() {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [activeFilter, setActiveFilter] = useState("All")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const selectedFilter = filters.find((filter) => filter.label === activeFilter) ?? filters[0]
  const jobFilters = useMemo<JobFilters>(
    () => ({ ...(selectedFilter.statuses ? { statuses: selectedFilter.statuses } : {}), limit: 100 }),
    [selectedFilter]
  )
  const jobsQuery = useQuery({
    queryKey: queryKeys.jobs(jobFilters),
    queryFn: () => getJobs(jobFilters),
  })
  const detailQuery = useQuery({
    queryKey: selectedId ? queryKeys.job(selectedId) : ["jobs", "detail", "none"],
    queryFn: () => getJob(selectedId as string),
    enabled: Boolean(selectedId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === "queued" || status === "running" ? 5_000 : false
    },
  })

  const invalidateJobTruth = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["jobs"] })
    if (selectedId) await queryClient.invalidateQueries({ queryKey: queryKeys.job(selectedId) })
  }, [queryClient, selectedId])

  const retryMutation = useMutation({
    mutationFn: (id: string) => retryJob(id),
    onSuccess: async () => {
      await invalidateJobTruth()
      pushNotice({ tone: "success", title: "Retry requested", message: "The job was returned to the durable queue." })
    },
    onError: (error) => pushNotice({ tone: "error", title: "Retry failed", message: getApiErrorMessage(error) }),
  })
  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelJob(id),
    onSuccess: async () => {
      await invalidateJobTruth()
      pushNotice({ tone: "success", title: "Job cancelled", message: "The queued job was cancelled." })
    },
    onError: (error) => pushNotice({ tone: "error", title: "Cancellation failed", message: getApiErrorMessage(error) }),
  })

  const closeDetail = useCallback(() => {
    setSelectedId(null)
    triggerRef.current?.focus()
  }, [])

  const selectJob = (job: WorkflowJob, trigger: HTMLButtonElement) => {
    triggerRef.current = trigger
    setSelectedId(job.id)
  }

  return (
    <section className="min-w-0 space-y-4 p-4 md:p-6" aria-labelledby="jobs-heading">
      <div>
        <h1 id="jobs-heading" className="text-2xl font-semibold">Job Queue</h1>
        <p className="text-muted-foreground">Inspect durable workflow state, progress, failures, and operator actions.</p>
      </div>
      <div role="group" aria-label="Job filters" className="flex flex-wrap gap-2">
        {filters.map((filter) => (
          <Button
            key={filter.label}
            variant={activeFilter === filter.label ? "default" : "outline"}
            aria-pressed={activeFilter === filter.label}
            onClick={() => setActiveFilter(filter.label)}
          >
            {filter.label}
          </Button>
        ))}
      </div>
      <Card size="sm">
        <CardContent className="px-0">
          {jobsQuery.isPending ? <div role="status" aria-label="Loading jobs" className="p-6 text-muted-foreground">Loading jobs</div> : null}
          {jobsQuery.isError ? (
            <div className="space-y-3 p-6">
              <div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(jobsQuery.error, "Job request failed")}</div>
              <Button variant="outline" onClick={() => void jobsQuery.refetch()}>Retry jobs</Button>
            </div>
          ) : null}
          {jobsQuery.data?.length ? (
            <JobTable jobs={jobsQuery.data} selectedId={selectedId} onSelect={selectJob} />
          ) : jobsQuery.isSuccess ? (
            <div className="p-8 text-center text-muted-foreground">No jobs match this filter</div>
          ) : null}
        </CardContent>
      </Card>
      {selectedId ? (
        <JobDetailPanel
          job={detailQuery.data}
          isLoading={detailQuery.isPending}
          error={detailQuery.error}
          mutationPending={retryMutation.isPending || cancelMutation.isPending}
          onClose={closeDetail}
          onRetry={() => retryMutation.mutate(selectedId)}
          onCancel={() => cancelMutation.mutate(selectedId)}
        />
      ) : null}
      {retryMutation.isError || cancelMutation.isError ? (
        <div className="sr-only" role="alert" dir="auto">
          {retryMutation.error ? getApiErrorMessage(retryMutation.error) : cancelMutation.error ? getApiErrorMessage(cancelMutation.error) : ""}
        </div>
      ) : null}
    </section>
  )
}
