"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { ContentPackWorkspace } from "@/components/editorial/content-pack-workspace"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ErrorState, LoadingState } from "@/components/ui/state-panel"
import { createManualPublicationPlan, getManualPublicationPlanForRevision, getPlatformRevision } from "@/features/packages/api"
import { ManualPublishingChecklist } from "@/features/packages/components/manual-publishing-checklist"
import type { ManualPublicationPlan, PlatformRevision, TelegramRevision } from "@/features/packages/types"
import { TelegramReviewWorkspace } from "@/features/review/telegram-review-workspace"
import { ApiError, getApiErrorMessage } from "@/lib/http"
import { zonedLocalDateTimeToUtc } from "@/lib/date-time"
import { packageQueryKeys, queryKeys } from "@/lib/query-keys"

type ManualRevision = Exclude<PlatformRevision, TelegramRevision>

export function ExactRevisionReview({ revisionId }: { revisionId: string }) {
  const revision = useQuery({ queryKey: queryKeys.variantRevision(revisionId), queryFn: () => getPlatformRevision(revisionId) })
  if (revision.isPending) return <section className="nc-page"><LoadingState title="Loading exact revision, variant, and content pack…" /></section>
  if (revision.isError) return <section className="nc-page"><ErrorState dir="auto" title="Exact revision unavailable" description={getApiErrorMessage(revision.error, "Exact editorial revision could not be loaded")} action={<Button variant="outline" onClick={() => void revision.refetch()}>Retry exact revision</Button>} /></section>
  const platform = revision.data.platform
  return <div className="space-y-8"><ContentPackWorkspace packId={revision.data.contentPackId} initialRevisionId={revisionId} />{platform === "telegram" ? <section aria-labelledby="telegram-handoff-heading" className="border-t"><h2 id="telegram-handoff-heading" className="sr-only">Telegram preview, scheduling, and publish handoff</h2><TelegramReviewWorkspace revision={revision.data} /></section> : revision.data.approvalState === "approved" ? <ManualPublicationHandoff key={revision.data.id} revision={revision.data as ManualRevision} /> : <section aria-label="Manual publication unavailable" className="space-y-2 border-t p-4 md:p-6"><h2 className="text-lg font-semibold">Manual publication unavailable</h2><p className="text-sm text-muted-foreground">Approve this exact {platformLabel(platform)} revision before manual publication handoff. Telegram scheduling and publishing controls do not apply.</p></section>}</div>
}

function ManualPublicationHandoff({ revision }: { revision: ManualRevision }) {
  const { timezone } = useDateTime()
  const queryClient = useQueryClient()
  const [scheduledFor, setScheduledFor] = useState("")
  const [localPlan, setLocalPlan] = useState<ManualPublicationPlan | null>(null)
  const [outcome, setOutcome] = useState<string | null>(null)
  const schedule = zonedLocalDateTimeToUtc(scheduledFor, timezone)
  const persistedPlan = useQuery({
    queryKey: packageQueryKeys.manualPlanForRevision(revision.id),
    queryFn: () => getManualPublicationPlanForRevision(revision.id),
  })
  const plan = localPlan ?? persistedPlan.data ?? null

  async function reconcileCreateConflict() {
    const refreshed = await persistedPlan.refetch()
    if (!refreshed.isSuccess) return
    const current = refreshed.data ?? null
    setLocalPlan(current)
    queryClient.setQueryData(packageQueryKeys.manualPlanForRevision(revision.id), current)
    if (current) queryClient.setQueryData(packageQueryKeys.manualPlan(current.id), current)
  }

  const createPlan = useMutation({
    mutationFn: (input: { scheduledFor: string; displayTimezone: string }) => createManualPublicationPlan(revision.id, input.scheduledFor, input.displayTimezone),
    onSuccess: async (created) => {
      setLocalPlan(created)
      setOutcome("Manual publication plan created")
      queryClient.setQueryData(packageQueryKeys.manualPlan(created.id), created)
      queryClient.setQueryData(packageQueryKeys.manualPlanForRevision(revision.id), created)
    },
    onError: async (caught) => {
      if (caught instanceof ApiError && caught.status === 409) await reconcileCreateConflict()
    },
  })

  const canSchedule = persistedPlan.isSuccess && (!plan || plan.status === "cancelled")
  const rescheduling = plan?.status === "cancelled"

  return <section aria-label="Manual publication handoff" className="space-y-4 border-t p-4 md:p-6">
    <div className="space-y-2"><h2 className="text-lg font-semibold">Manual publication handoff</h2><p className="text-sm text-muted-foreground">{platformLabel(revision.platform)} is a manual publication platform. Copy and exports above stay bound to exact revision {revision.revisionNumber}; Telegram scheduling and publishing controls do not apply.</p></div>
    {persistedPlan.isPending ? <div role="status">Loading persisted manual publication plan…</div> : null}
    {persistedPlan.isError ? <Alert tone="error" role="alert"><div className="flex flex-wrap items-center justify-between gap-3"><div><AlertTitle>Publication plan unavailable</AlertTitle><AlertDescription>{getApiErrorMessage(persistedPlan.error, "Persisted manual publication plan could not be loaded")}</AlertDescription></div><Button type="button" variant="outline" onClick={() => void persistedPlan.refetch()}>Retry manual publication plan</Button></div></Alert> : null}
    {canSchedule ? <fieldset disabled={createPlan.isPending} className="grid gap-3 rounded-lg border p-4 md:grid-cols-2">
      <legend className="px-1 font-medium">{rescheduling ? "Schedule a new manual handoff" : "Schedule the manual handoff"}</legend>
      <label className="grid gap-1"><span>Scheduled time ({timezone})</span><Input aria-label={`Scheduled time (${timezone})`} aria-invalid={scheduledFor !== "" && !schedule} type="datetime-local" step="60" value={scheduledFor} onChange={(event) => { setScheduledFor(event.target.value); setOutcome(null) }} /></label>
      <p className="self-end text-sm text-muted-foreground">Local time converts to UTC before persistence.</p>
      <div className="md:col-span-2"><Button type="button" disabled={!schedule || createPlan.isPending} onClick={() => schedule && createPlan.mutate({ scheduledFor: schedule, displayTimezone: timezone })}>{createPlan.isPending ? "Creating manual publication plan…" : rescheduling ? "Create new manual publication plan" : "Create manual publication plan"}</Button></div>
    </fieldset> : null}
    {plan ? <div className="rounded-lg border p-4"><ManualPublishingChecklist plan={plan} contentPackId={revision.contentPackId} onPlanChange={(updated) => { setLocalPlan(updated); queryClient.setQueryData(packageQueryKeys.manualPlanForRevision(revision.id), updated) }} /></div> : null}
    {outcome ? <Alert tone="success" role="status"><AlertDescription>{outcome}</AlertDescription></Alert> : null}
    {createPlan.isError ? <Alert tone="error" role="alert"><AlertDescription>{getApiErrorMessage(createPlan.error, "Manual publication plan could not be created")}</AlertDescription></Alert> : null}
  </section>
}

function platformLabel(platform: string) {
  if (platform === "instagram") return "Instagram"
  if (platform === "x") return "X"
  if (platform === "blog") return "Blog"
  return platform
}
