"use client"

import type { ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { ArrowRight, CircleAlert, FilePlus2, SquarePen } from "lucide-react"
import Link from "next/link"

import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { GlobalControls } from "@/features/control/global-controls"
import { getJobs, getJobSummary } from "@/features/jobs/api"
import { AttentionQueue } from "@/features/jobs/attention-queue"
import { JobStatusBadge } from "@/features/jobs/job-status-badge"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function TodayPage({ outcomes }: { outcomes?: ReactNode }) {
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
  const queries = [summaryQuery, runningQuery, attentionQuery, successesQuery]
  const firstError = queries.find((query) => query.isError)?.error
  const loading = queries.some((query) => query.isPending)
  const summary = summaryQuery.data
  const isEmpty = summary && Object.values(summary).every((count) => count === 0)
  const priorityJob = attentionQuery.data?.[0]

  const retryAll = () => {
    for (const query of queries) void query.refetch()
  }

  return (
    <section className="min-w-0 space-y-4 p-4 md:p-6" aria-labelledby="today-heading">
      <div>
        <h1 id="today-heading" className="text-2xl font-semibold">Today</h1>
        <p className="text-muted-foreground">Live workflow truth and the work that needs an operator.</p>
      </div>
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
        <HealthSummary summary={summary} />
      ) : null}
      {!firstError && summary ? (
        <PriorityDecision job={priorityJob} />
      ) : null}
      <GlobalControls />
      {outcomes}
      {isEmpty ? <Card size="sm"><CardContent className="p-8 text-center text-muted-foreground">No workflow jobs yet</CardContent></Card> : null}
      {!firstError && !isEmpty && summary ? (
        <div className="grid min-w-0 gap-4 xl:grid-cols-2">
          <AttentionQueue
            jobs={attentionQuery.data ?? []}
          />
          <Card size="sm" role="region" aria-label="Running jobs">
            <CardHeader className="border-b"><CardTitle>Running now</CardTitle></CardHeader>
            <CardContent className="divide-y px-0">
              {(runningQuery.data ?? []).length ? runningQuery.data?.map((job) => (
                <div key={job.id} className="space-y-2 px-3 py-3">
                  <div className="flex justify-between gap-3"><span className="font-medium">{job.job_type}</span><JobStatusBadge status={job.status} /></div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}>
                    <div className="h-full bg-primary" style={{ width: `${job.progress}%` }} />
                  </div>
                  <div className="flex justify-between gap-3 text-sm text-muted-foreground">
                    <span dir="auto">{job.progress_message ?? "Running"}</span>
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
                  <span className="font-medium">{job.job_type}</span><JobStatusBadge status={job.status} />
                </div>
              )) : <div className="p-6 text-center text-muted-foreground">No successful jobs today</div>}
            </CardContent>
          </Card>
        </div>
      ) : null}
    </section>
  )
}

function HealthSummary({
  summary,
}: {
  summary: { queued: number; running: number; attention: number; succeeded_today: number }
}) {
  const values = [
    ["Queued", summary.queued, "queued"],
    ["Running", summary.running, "running"],
    ["Attention", summary.attention, "attention"],
    ["Succeeded", summary.succeeded_today, "succeeded"],
  ] as const
  return (
    <Card size="sm" aria-label="Workflow health" role="region">
      <CardContent className="grid grid-cols-2 divide-x divide-y p-0 sm:grid-cols-4 sm:divide-y-0">
        {values.map(([label, value, kind]) => (
          <div className="flex items-baseline justify-between gap-3 px-4 py-3 sm:block" key={kind}>
            <span className="text-xs text-muted-foreground">{label}</span>
            <strong className="text-xl tabular-nums sm:mt-1 sm:block" data-summary={kind}>{value}</strong>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function PriorityDecision({
  job,
}: {
  job: Awaited<ReturnType<typeof getJobs>>[number] | undefined
}) {
  if (job?.status === "failed") {
    return (
      <Card size="sm" role="region" aria-label="Highest-priority decision">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-semibold"><CircleAlert className="size-5 text-red-700" aria-hidden="true" />Resolve failed workflow</div>
            <p className="mt-1 truncate text-sm text-muted-foreground" dir="auto">{job.job_type}</p>
          </div>
          <Link className={buttonVariants()} href={`/jobs?status=attention&job=${job.id}`}>
            Inspect and retry
            <ArrowRight aria-hidden="true" />
          </Link>
        </CardContent>
      </Card>
    )
  }
  if (job?.status === "needs_review") {
    return (
      <Card size="sm" role="region" aria-label="Highest-priority decision">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
          <div>
            <div className="flex items-center gap-2 font-semibold"><SquarePen className="size-5 text-amber-700" aria-hidden="true" />Editorial review is waiting</div>
            <p className="mt-1 text-sm text-muted-foreground">Continue with the oldest item needing a decision.</p>
          </div>
          <Link className={buttonVariants()} href={`/jobs?status=attention&job=${job.id}`}>
            Continue review
            <ArrowRight aria-hidden="true" />
          </Link>
        </CardContent>
      </Card>
    )
  }
  return (
    <Card size="sm" role="region" aria-label="Highest-priority decision">
      <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div>
          <div className="flex items-center gap-2 font-semibold"><FilePlus2 className="size-5 text-teal-700" aria-hidden="true" />Start the next story</div>
          <p className="mt-1 text-sm text-muted-foreground">No failures or reviews are blocking today.</p>
        </div>
        <Link className={buttonVariants()} href="/inbox?add=story">
          Add story
          <ArrowRight aria-hidden="true" />
        </Link>
      </CardContent>
    </Card>
  )
}
