"use client"

import type { ReactNode } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { useNotices } from "@/components/providers/notice-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { GlobalControls } from "@/features/control/global-controls"
import { cancelJob, getJobs, getJobSummary, retryJob } from "@/features/jobs/api"
import { AttentionQueue } from "@/features/jobs/attention-queue"
import { JobStatusBadge } from "@/features/jobs/job-status-badge"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function TodayPage({ outcomes }: { outcomes?: ReactNode }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const summaryQuery = useQuery({ queryKey: queryKeys.jobSummary, queryFn: getJobSummary, refetchInterval: 5_000 })
  const runningQuery = useQuery({
    queryKey: queryKeys.jobs({ statuses: ["running"], limit: 25 }),
    queryFn: () => getJobs({ statuses: ["running"], limit: 25 }),
    refetchInterval: 5_000,
  })
  const attentionQuery = useQuery({
    queryKey: queryKeys.jobs({ statuses: ["failed", "needs_review"], limit: 25 }),
    queryFn: () => getJobs({ statuses: ["failed", "needs_review"], limit: 25 }),
    refetchInterval: 5_000,
  })
  const successesQuery = useQuery({
    queryKey: queryKeys.jobs({ statuses: ["succeeded"], limit: 10 }),
    queryFn: () => getJobs({ statuses: ["succeeded"], limit: 10 }),
  })
  const invalidate = async () => queryClient.invalidateQueries({ queryKey: ["jobs"] })
  const retryMutation = useMutation({
    mutationFn: (id: string) => retryJob(id),
    onSuccess: async () => {
      await invalidate()
      pushNotice({ tone: "success", title: "Retry requested", message: "The job was queued again." })
    },
    onError: (error) => pushNotice({ tone: "error", title: "Retry failed", message: getApiErrorMessage(error) }),
  })
  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelJob(id),
    onSuccess: async () => {
      await invalidate()
      pushNotice({ tone: "success", title: "Job cancelled", message: "The queued job was cancelled." })
    },
    onError: (error) => pushNotice({ tone: "error", title: "Cancellation failed", message: getApiErrorMessage(error) }),
  })

  const queries = [summaryQuery, runningQuery, attentionQuery, successesQuery]
  const firstError = queries.find((query) => query.isError)?.error
  const loading = queries.some((query) => query.isPending)
  const summary = summaryQuery.data
  const isEmpty = summary && Object.values(summary).every((count) => count === 0)
  const pendingJobId = retryMutation.isPending
    ? retryMutation.variables
    : cancelMutation.isPending
      ? cancelMutation.variables
      : null

  const retryAll = () => {
    for (const query of queries) void query.refetch()
  }

  return (
    <section className="min-w-0 space-y-4 p-4 md:p-6" aria-labelledby="today-heading">
      <div>
        <h1 id="today-heading" className="text-2xl font-semibold">Today</h1>
        <p className="text-muted-foreground">Live workflow truth and the work that needs an operator.</p>
      </div>
      <GlobalControls />
      {outcomes}
      {loading ? (
        <div role="status" aria-label="Loading Today" className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} data-testid="today-skeleton" aria-hidden="true" className="h-24 animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      ) : null}
      {firstError ? (
        <Card size="sm">
          <CardContent className="space-y-3 p-4">
            <div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(firstError, "Today data request failed")}</div>
            <Button variant="outline" onClick={retryAll}>Retry Today</Button>
          </CardContent>
        </Card>
      ) : null}
      {summary ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <SummaryCard label="Queued" value={summary.queued} kind="queued" />
          <SummaryCard label="Running" value={summary.running} kind="running" />
          <SummaryCard label="Attention" value={summary.attention} kind="attention" />
          <SummaryCard label="Succeeded today" value={summary.succeededToday} kind="succeeded" />
        </div>
      ) : null}
      {isEmpty ? <Card size="sm"><CardContent className="p-8 text-center text-muted-foreground">No workflow jobs yet</CardContent></Card> : null}
      {!firstError && !isEmpty && summary ? (
        <div className="grid min-w-0 gap-4 xl:grid-cols-2">
          <AttentionQueue
            jobs={attentionQuery.data ?? []}
            pendingJobId={pendingJobId}
            onRetry={(id) => retryMutation.mutate(id)}
            onCancel={(id) => cancelMutation.mutate(id)}
          />
          <Card size="sm" role="region" aria-label="Running jobs">
            <CardHeader className="border-b"><CardTitle>Running now</CardTitle></CardHeader>
            <CardContent className="divide-y px-0">
              {(runningQuery.data ?? []).length ? runningQuery.data?.map((job) => (
                <div key={job.id} className="space-y-2 px-3 py-3">
                  <div className="flex justify-between gap-3"><span className="font-medium">{job.jobType}</span><JobStatusBadge status={job.status} /></div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}>
                    <div className="h-full bg-primary" style={{ width: `${job.progress}%` }} />
                  </div>
                  <div className="flex justify-between gap-3 text-sm text-muted-foreground">
                    <span dir="auto">{job.progressMessage ?? "Running"}</span>
                    <span data-progress-label dir="auto">{job.progress}%</span>
                  </div>
                </div>
              )) : <div className="p-6 text-center text-muted-foreground">No jobs running</div>}
            </CardContent>
          </Card>
          <Card size="sm" role="region" aria-label="Recent successes" className="xl:col-span-2">
            <CardHeader className="border-b"><CardTitle>Recent successes</CardTitle></CardHeader>
            <CardContent className="divide-y px-0">
              {(successesQuery.data ?? []).length ? successesQuery.data?.map((job) => (
                <div key={job.id} className="flex items-center justify-between gap-3 px-3 py-3">
                  <span className="font-medium">{job.jobType}</span><JobStatusBadge status={job.status} />
                </div>
              )) : <div className="p-6 text-center text-muted-foreground">No successful jobs today</div>}
            </CardContent>
          </Card>
        </div>
      ) : null}
    </section>
  )
}

function SummaryCard({ label, value, kind }: { label: string; value: number; kind: "queued" | "running" | "attention" | "succeeded" }) {
  return <Card size="sm"><CardContent className="p-4"><div className="text-sm text-muted-foreground">{label}</div><div data-summary={kind} className="mt-1 text-2xl font-semibold tabular-nums">{value}</div></CardContent></Card>
}
