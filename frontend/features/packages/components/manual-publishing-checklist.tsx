"use client"

import { useEffect, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { useDateTime } from "@/components/providers/date-time-provider"
import { Button } from "@/components/ui/button"
import {
  getManualPublicationPlanForRevision,
  markManualPublicationPublished,
  updateManualPublicationChecklist,
} from "@/features/packages/api"
import type { ManualPublicationPlan } from "@/features/packages/types"
import { formatInTimeZone } from "@/lib/date-time"
import { ApiError, getApiErrorMessage } from "@/lib/http"
import { packageQueryKeys, queryKeys } from "@/lib/query-keys"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"

const CHECKLIST_LABELS: Record<string, string> = {
  copy_reviewed: "Copy reviewed",
  citations_verified: "Citations verified",
  media_and_alt_text_ready: "Media and alt text ready",
  platform_requirements_rechecked: "Platform requirements rechecked",
  thread_order_reviewed: "Thread order reviewed",
  citations_and_links_verified: "Citations and links verified",
  article_reviewed: "Article reviewed",
  seo_fields_reviewed: "SEO fields reviewed",
}

export type ManualPublishingChecklistProps = {
  plan: ManualPublicationPlan
  contentPackId?: string
  onPlanChange?: (plan: ManualPublicationPlan) => void
}

export function ManualPublishingChecklist({
  plan,
  contentPackId,
  onPlanChange,
}: ManualPublishingChecklistProps) {
  const { timezone } = useDateTime()
  const queryClient = useQueryClient()
  const [localPlan, setLocalPlan] = useState(plan)
  const [pendingItem, setPendingItem] = useState<string | null>(null)
  const [completionPending, setCompletionPending] = useState(false)
  const [externalUrl, setExternalUrl] = useState(plan.externalUrl ?? "")
  const [note, setNote] = useState(plan.operatorNote ?? "")
  const [error, setError] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<string | null>(null)

  useEffect(() => {
    setLocalPlan(plan)
    setExternalUrl(plan.externalUrl ?? "")
    setNote(plan.operatorNote ?? "")
  }, [plan.id, plan.updatedAt])

  const terminal = localPlan.status === "manual_published" || localPlan.status === "cancelled"
  const complete = Object.values(localPlan.checklistState).every(Boolean)
  const trimmedExternalUrl = externalUrl.trim()
  const safeUrl = trimmedExternalUrl ? normalizePublicUrl(trimmedExternalUrl) : null
  const invalidUrl = trimmedExternalUrl.length > 0 && safeUrl === null
  const busy = pendingItem !== null || completionPending

  function storePersistedPlan(saved: ManualPublicationPlan) {
    setLocalPlan(saved)
    setExternalUrl(saved.externalUrl ?? "")
    setNote(saved.operatorNote ?? "")
    queryClient.setQueryData(packageQueryKeys.manualPlan(saved.id), saved)
    queryClient.setQueryData(packageQueryKeys.manualPlanForRevision(saved.platformVariantRevisionId), saved)
    onPlanChange?.(saved)
  }

  async function reconcileConflict(caught: unknown) {
    if (!(caught instanceof ApiError) || caught.status !== 409) return
    try {
      const persisted = await getManualPublicationPlanForRevision(localPlan.platformVariantRevisionId)
      queryClient.setQueryData(
        packageQueryKeys.manualPlanForRevision(localPlan.platformVariantRevisionId),
        persisted,
      )
      if (persisted) storePersistedPlan(persisted)
      await queryClient.invalidateQueries({
        queryKey: contentPackId ? queryKeys.contentPack(contentPackId) : queryKeys.contentPacks,
      })
    } catch {
      // Preserve the original mutation error and rollback state when conflict refresh also fails.
    }
  }

  async function toggleItem(id: string, checked: boolean) {
    if (busy || terminal) return
    const rollback = localPlan
    const checklistState = { ...localPlan.checklistState, [id]: checked }
    const optimistic: ManualPublicationPlan = {
      ...localPlan,
      checklistState,
      status: Object.values(checklistState).every(Boolean) ? "ready" : "planned",
    }
    setLocalPlan(optimistic)
    setPendingItem(id)
    setError(null)
    setOutcome(null)
    try {
      const saved = await updateManualPublicationChecklist(localPlan.id, { [id]: checked })
      storePersistedPlan(saved)
    } catch (caught) {
      setLocalPlan(rollback)
      setError(getApiErrorMessage(caught, "Checklist progress could not be saved"))
      await reconcileConflict(caught)
    } finally {
      setPendingItem(null)
    }
  }

  async function markPublished() {
    if (busy || terminal || !complete || invalidUrl) return
    setCompletionPending(true)
    setError(null)
    setOutcome(null)
    try {
      const saved = await markManualPublicationPublished(localPlan.id, {
        externalUrl: safeUrl,
        note: note.trim() || null,
      })
      storePersistedPlan(saved)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: packageQueryKeys.manualPlan(saved.id) }),
        queryClient.invalidateQueries({ queryKey: contentPackId ? queryKeys.contentPack(contentPackId) : queryKeys.contentPacks }),
      ])
      setOutcome("Manual publication recorded")
    } catch (caught) {
      setError(getApiErrorMessage(caught, "Manual publication could not be recorded"))
      await reconcileConflict(caught)
    } finally {
      setCompletionPending(false)
    }
  }

  return (
    <section aria-labelledby="manual-checklist-heading" className="space-y-4">
      <div>
        <h2 id="manual-checklist-heading" className="text-lg font-semibold">Manual publishing checklist</h2>
        <p className="text-sm text-muted-foreground">
          {platformLabel(localPlan.platform)} plan {localPlan.id} · exact revision {localPlan.platformVariantRevisionId}
        </p>
        <p className="font-medium">Status: {statusLabel(localPlan.status)}</p>
        <p className="text-sm text-muted-foreground">Scheduled <time dateTime={localPlan.scheduledFor}>{formatInTimeZone(localPlan.scheduledFor, timezone)}</time> · {timezone}</p>
      </div>

      <fieldset className="space-y-2" disabled={busy || terminal}>
        <legend className="sr-only">Persisted publishing checks</legend>
        {Object.entries(localPlan.checklistState).map(([id, checked]) => (
          <label key={id} className="flex items-center gap-2 rounded-lg border p-3">
            <input
              type="checkbox"
              checked={checked}
              onChange={(event) => void toggleItem(id, event.target.checked)}
            />
            <span>{CHECKLIST_LABELS[id] ?? id.replaceAll("_", " ")}</span>
          </label>
        ))}
      </fieldset>

      {!terminal ? <><div className="grid gap-3">
        <label className="grid gap-1">
          <span>Publication URL (optional)</span>
          <input
            aria-label="Publication URL"
            className="rounded-lg border p-2"
            type="url"
            disabled={busy || terminal}
            value={externalUrl}
            onChange={(event) => setExternalUrl(event.target.value)}
            placeholder="https://…"
          />
        </label>
        {invalidUrl ? (
          <p className="text-sm text-destructive">Enter the public HTTP or HTTPS URL.</p>
        ) : null}
        <label className="grid gap-1">
          <span>Operator note (optional)</span>
          <DirectionBoundary
            as="textarea"
            language={null}
            aria-label="Operator note (optional)"
            className="min-h-20 rounded-lg border p-2"
            maxLength={2_000}
            disabled={busy || terminal}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
      </div>

      <Button
        type="button"
        disabled={busy || terminal || !complete || invalidUrl}
        onClick={() => void markPublished()}
      >
        {completionPending ? "Recording publication…" : "Mark as published"}
      </Button></> : null}

      {localPlan.status === "manual_published" ? <section aria-label="Manual publication completion evidence" className="space-y-2 rounded-lg border p-3">
        <h3 className="font-medium">Completion evidence</h3>
        <p>Completed at {localPlan.completedAt ? <time dateTime={localPlan.completedAt}>{formatInTimeZone(localPlan.completedAt, timezone)}</time> : "Stored completion time unavailable"}</p>
        {localPlan.externalUrl ? <a className="block break-all text-primary underline" href={localPlan.externalUrl} target="_blank" rel="noreferrer">Open recorded publication</a> : <p>No publication URL was recorded.</p>}
        {localPlan.operatorNote ? <DirectionBoundary as="p" language={null}>{localPlan.operatorNote}</DirectionBoundary> : <p>No operator note was recorded.</p>}
      </section> : null}
      {localPlan.status === "cancelled" ? <p>Cancelled plans remain in publication history and cannot be edited.</p> : null}
      {pendingItem ? <div role="status">Saving checklist progress…</div> : null}
      {outcome ? <div role="status" className="text-success">{outcome}</div> : null}
      {error ? <div role="alert" className="text-sm text-destructive">{error}</div> : null}
    </section>
  )
}

function normalizePublicUrl(value: string): string | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  try {
    const url = new URL(trimmed)
    if ((url.protocol !== "http:" && url.protocol !== "https:") || url.username || url.password) return null
    return trimmed
  } catch {
    return null
  }
}

function platformLabel(platform: ManualPublicationPlan["platform"]) {
  if (platform === "x") return "X"
  return platform.charAt(0).toUpperCase() + platform.slice(1)
}

function statusLabel(status: ManualPublicationPlan["status"]) {
  if (status === "manual_published") return "Published manually"
  if (status === "cancelled") return "Cancelled"
  if (status === "ready") return "Ready to publish"
  return "Planned"
}
