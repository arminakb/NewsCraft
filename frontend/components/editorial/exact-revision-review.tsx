"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { ContentPackWorkspace } from "@/components/editorial/content-pack-workspace"
import { Button } from "@/components/ui/button"
import { createManualPublicationPlan, getManualPublicationPlanForRevision, getPlatformRevision } from "@/features/packages/api"
import { ManualPublishingChecklist } from "@/features/packages/components/manual-publishing-checklist"
import type { ManualPublicationPlan, PlatformRevision, TelegramRevision } from "@/features/packages/types"
import { TelegramReviewWorkspace } from "@/features/review/telegram-review-workspace"
import { ApiError, getApiErrorMessage } from "@/lib/http"
import { packageQueryKeys, queryKeys } from "@/lib/query-keys"

type ManualRevision = Exclude<PlatformRevision, TelegramRevision>

export function ExactRevisionReview({ revisionId }: { revisionId: string }) {
  const revision = useQuery({ queryKey: queryKeys.variantRevision(revisionId), queryFn: () => getPlatformRevision(revisionId) })
  if (revision.isPending) return <section role="status" className="p-6">Loading exact revision, variant, and content pack…</section>
  if (revision.isError) return <section role="alert" dir="auto" className="p-6 text-red-700">{getApiErrorMessage(revision.error, "Exact editorial revision could not be loaded")}</section>
  const platform = revision.data.platform
  return <div className="space-y-8"><ContentPackWorkspace packId={revision.data.contentPackId} initialRevisionId={revisionId} />{platform === "telegram" ? <section aria-labelledby="telegram-handoff-heading" className="border-t"><h2 id="telegram-handoff-heading" className="sr-only">Telegram preview, scheduling, and publish handoff</h2><TelegramReviewWorkspace revision={revision.data} /></section> : revision.data.approvalState === "approved" ? <ManualPublicationHandoff key={revision.data.id} revision={revision.data as ManualRevision} /> : <section aria-label="Manual publication unavailable" className="space-y-2 border-t p-4 md:p-6"><h2 className="text-lg font-semibold">Manual publication unavailable</h2><p className="text-sm text-muted-foreground">Approve this exact {platformLabel(platform)} revision before manual publication handoff. Telegram scheduling and publishing controls do not apply.</p></section>}</div>
}

function ManualPublicationHandoff({ revision }: { revision: ManualRevision }) {
  const queryClient = useQueryClient()
  const [scheduledFor, setScheduledFor] = useState("")
  const [displayTimezone, setDisplayTimezone] = useState("Asia/Tehran")
  const [localPlan, setLocalPlan] = useState<ManualPublicationPlan | null>(null)
  const [outcome, setOutcome] = useState<string | null>(null)
  const schedule = utcSchedule(scheduledFor)
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
    await queryClient.invalidateQueries({ queryKey: ["calendar"] })
  }

  const createPlan = useMutation({
    mutationFn: (input: { scheduledFor: string; displayTimezone: string }) => createManualPublicationPlan(revision.id, input.scheduledFor, input.displayTimezone),
    onSuccess: async (created) => {
      setLocalPlan(created)
      setOutcome("Manual publication plan created")
      queryClient.setQueryData(packageQueryKeys.manualPlan(created.id), created)
      queryClient.setQueryData(packageQueryKeys.manualPlanForRevision(revision.id), created)
      await queryClient.invalidateQueries({ queryKey: ["calendar"] })
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
    {persistedPlan.isError ? <div className="space-y-2"><div role="alert" className="text-sm text-red-700">{getApiErrorMessage(persistedPlan.error, "Persisted manual publication plan could not be loaded")}</div><Button type="button" variant="outline" onClick={() => void persistedPlan.refetch()}>Retry manual publication plan</Button></div> : null}
    {canSchedule ? <fieldset disabled={createPlan.isPending} className="grid gap-3 rounded-lg border p-4 md:grid-cols-2">
      <legend className="px-1 font-medium">{rescheduling ? "Schedule a new manual handoff" : "Schedule the manual handoff"}</legend>
      <label className="grid gap-1"><span>Scheduled time (UTC)</span><input aria-label="Scheduled time (UTC)" type="datetime-local" step="60" className="rounded-lg border p-2" value={scheduledFor} onChange={(event) => { setScheduledFor(event.target.value); setOutcome(null) }} /></label>
      <label className="grid gap-1"><span>Display timezone</span><select aria-label="Display timezone" className="rounded-lg border bg-background p-2" value={displayTimezone} onChange={(event) => setDisplayTimezone(event.target.value)}><option value="Asia/Tehran">Asia/Tehran</option><option value="UTC">UTC</option><option value="Europe/London">Europe/London</option><option value="America/New_York">America/New_York</option></select></label>
      <div className="md:col-span-2"><Button type="button" disabled={!schedule || createPlan.isPending} onClick={() => schedule && createPlan.mutate({ scheduledFor: schedule, displayTimezone })}>{createPlan.isPending ? "Creating manual publication plan…" : rescheduling ? "Create new manual publication plan" : "Create manual publication plan"}</Button></div>
    </fieldset> : null}
    {plan ? <div className="rounded-lg border p-4"><ManualPublishingChecklist plan={plan} contentPackId={revision.contentPackId} onPlanChange={(updated) => { setLocalPlan(updated); queryClient.setQueryData(packageQueryKeys.manualPlanForRevision(revision.id), updated) }} /></div> : null}
    {outcome ? <div role="status" className="text-sm text-green-700">{outcome}</div> : null}
    {createPlan.isError ? <div role="alert" className="text-sm text-red-700">{getApiErrorMessage(createPlan.error, "Manual publication plan could not be created")}</div> : null}
  </section>
}

function utcSchedule(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null
  const candidate = `${value}:00.000Z`
  const parsed = new Date(candidate)
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString() !== candidate) return null
  return candidate
}

function platformLabel(platform: string) {
  if (platform === "instagram") return "Instagram"
  if (platform === "x") return "X"
  if (platform === "blog") return "Blog"
  return platform
}
