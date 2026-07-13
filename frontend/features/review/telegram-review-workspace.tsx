"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useEffect, useMemo, useRef, useState } from "react"

import { useNotices } from "@/components/providers/notice-provider"
import { guardedNavigation, useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  approveTelegramDraft,
  editTelegramDraft,
  getTelegramDestinations,
  getTelegramDispatches,
  getTelegramDraft,
  getTelegramPublishJob,
  getTelegramRoute,
  publishTelegramDraft,
  rejectTelegramDraft,
} from "@/features/automations/telegram-api"
import { getAutomationControl } from "@/features/control/api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import { ReviewResearchOutcome } from "@/features/automations/research-outcome"

export function TelegramReviewWorkspace({ revisionId, contentPackId, platformVariantId }: { revisionId: string; contentPackId?: string; platformVariantId?: string }) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const outcomeRef = useRef<HTMLDivElement>(null)
  const [body, setBody] = useState("")
  const [baselineBody, setBaselineBody] = useState("")
  const [rejectionNote, setRejectionNote] = useState("")
  const [publishOutcome, setPublishOutcome] = useState<{ publishJobId: string; status: string } | null>(null)

  const draftQuery = useQuery({
    queryKey: queryKeys.telegramDraft(revisionId),
    queryFn: () => getTelegramDraft(revisionId),
  })
  const draft = draftQuery.data
  useEffect(() => {
    if (draft) {
      setBody(draft.content.body)
      setBaselineBody(draft.content.body)
    }
  }, [draft])

  const routeQuery = useQuery({
    queryKey: queryKeys.telegramRoute(draft?.routeId ?? "unresolved"),
    queryFn: () => getTelegramRoute(draft!.routeId!),
    enabled: Boolean(draft?.routeId),
  })
  const destinationsQuery = useQuery({
    queryKey: queryKeys.telegramDestinations,
    queryFn: getTelegramDestinations,
  })
  const controlQuery = useQuery({
    queryKey: queryKeys.automationControl,
    queryFn: getAutomationControl,
  })
  const destination = destinationsQuery.data?.find((item) => item.id === routeQuery.data?.destinationId)
  const dispatchesQuery = useQuery({ queryKey: queryKeys.telegramDispatches(draft?.routeId ?? "unresolved"), queryFn: () => getTelegramDispatches(draft!.routeId!), enabled: Boolean(draft?.routeId && draft?.dispatchId) })
  const dispatch = dispatchesQuery.data?.find((item) => item.id === draft?.dispatchId)
  const activePublishJobId = publishOutcome?.publishJobId ?? draft?.publishJobId ?? null
  const publishJobQuery = useQuery({
    queryKey: queryKeys.telegramPublishJob(activePublishJobId ?? "unresolved"),
    queryFn: () => getTelegramPublishJob(activePublishJobId!),
    enabled: Boolean(activePublishJobId),
    refetchInterval: 5_000,
  })

  const invalidateDraft = async (id = revisionId) => {
    const variantId = platformVariantId ?? draft?.platformVariantId
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.telegramDraft(id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.telegramDrafts() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.variantRevision(id) }),
      ...(variantId ? [queryClient.invalidateQueries({ queryKey: queryKeys.variantRevisions(variantId) })] : []),
      ...(contentPackId ? [queryClient.invalidateQueries({ queryKey: queryKeys.contentPack(contentPackId) })] : []),
    ])
  }
  const editMutation = useMutation({
    mutationFn: () => editTelegramDraft(revisionId, {
      content: { body, parse_mode: draft!.content.parseMode, buttons: draft!.content.buttons },
      media_asset_ids: draft!.content.mediaAssetIds,
    }),
    onSuccess: async (child) => {
      await invalidateDraft()
      pushNotice({ tone: "success", title: "Revision saved", message: `Revision ${child.revisionNumber} is ready for review.` })
      setBaselineBody(child.content.body)
      releaseDirtyNavigation()
      guardedNavigation(() => router.push(`/review/${child.id}`))
    },
    onError: (error) => pushNotice({ tone: "error", title: "Edit failed", message: getApiErrorMessage(error) }),
  })
  const approveMutation = useMutation({
    mutationFn: () => approveTelegramDraft(revisionId, draft!.contentHash),
    onSuccess: async () => {
      await invalidateDraft()
      pushNotice({ tone: "success", title: "Revision approved", message: "The exact content hash is approved." })
    },
    onError: (error) => pushNotice({ tone: "error", title: "Approval failed", message: getApiErrorMessage(error) }),
  })
  const rejectMutation = useMutation({
    mutationFn: () => rejectTelegramDraft(revisionId, draft!.contentHash, rejectionNote || undefined),
    onSuccess: async () => {
      await invalidateDraft()
      pushNotice({ tone: "success", title: "Revision rejected", message: "The exact revision was rejected." })
    },
    onError: (error) => pushNotice({ tone: "error", title: "Rejection failed", message: getApiErrorMessage(error) }),
  })
  const publishMutation = useMutation({
    mutationFn: () => publishTelegramDraft(revisionId, draft!.contentHash),
    onSuccess: async (result) => {
      setPublishOutcome({ publishJobId: result.job.publishJobId, status: result.job.status })
      await invalidateDraft()
      await queryClient.invalidateQueries({ queryKey: queryKeys.telegramPublishJob(result.job.publishJobId) })
      requestAnimationFrame(() => outcomeRef.current?.focus())
    },
    onError: (error) => pushNotice({ tone: "error", title: "Publish failed", message: getApiErrorMessage(error) }),
  })

  const blockers = useMemo(() => {
    const values: string[] = []
    if (controlQuery.isPending || routeQuery.isPending || destinationsQuery.isPending) values.push("Publishing controls are loading")
    if (controlQuery.isError || routeQuery.isError || destinationsQuery.isError || (routeQuery.data && !destination)) values.push("Publishing controls are unavailable")
    if (controlQuery.data?.globalPause) values.push("Global pause blocks publishing")
    if (controlQuery.data?.dryRun) values.push("Global dry run blocks publishing")
    if (routeQuery.data?.pausedAt) values.push("Route paused")
    if (routeQuery.data && !routeQuery.data.enabled) values.push("Route disabled")
    if (destination && !destination.configured) values.push("Destination unavailable")
    if (destination && (!destination.enabled || destination.healthStatus !== "healthy")) values.push("Destination unhealthy")
    if (draft?.content.dryRun) values.push("Draft dry run blocks publishing")
    if (draft?.content.mediaPolicy === "replace_manually") values.push("Manual media replacement is required")
    if (draft?.routeId && draft?.dispatchId && dispatchesQuery.isPending) values.push("Dispatch and research outcome are loading")
    if (draft?.routeId && draft?.dispatchId && dispatchesQuery.isError) values.push("Dispatch and research outcome are unavailable")
    if (draft?.routeId && draft?.dispatchId && dispatchesQuery.isSuccess && !dispatch) values.push("Expected dispatch is unavailable")
    if (dispatch?.status === "needs_review" || dispatch?.errorCode?.includes("research")) values.push("Review required because research did not complete")
    return values
  }, [controlQuery.data, controlQuery.isError, controlQuery.isPending, destination, destinationsQuery.isError, destinationsQuery.isPending, dispatch, dispatchesQuery.isError, dispatchesQuery.isPending, dispatchesQuery.isSuccess, draft, routeQuery.data, routeQuery.isError, routeQuery.isPending])

  const editorDirty = Boolean(draft && body !== baselineBody)
  const releaseDirtyNavigation = useDirtyNavigation(editorDirty)

  if (draftQuery.isPending) return <div role="status" className="p-6">Loading Telegram revision…</div>
  if (draftQuery.isError || !draft) return <div role="alert" dir="auto" className="p-6 text-red-700">{getApiErrorMessage(draftQuery.error, "Telegram revision could not be loaded")}</div>

  const mutationPending = editMutation.isPending || approveMutation.isPending || rejectMutation.isPending || publishMutation.isPending
  const canPublish = draft.approvalState === "approved" && blockers.length === 0 && !mutationPending && !editorDirty

  return (
    <section className="min-w-0 space-y-4 p-4 md:p-6" aria-labelledby="telegram-review-heading">
      <div>
        <h1 id="telegram-review-heading" className="text-2xl font-semibold">Review Telegram revision {draft.revisionNumber}</h1>
        <p className="break-all text-sm text-muted-foreground">Exact hash: {draft.contentHash}</p>
      </div>
      {draft.routeId && draft.dispatchId && routeQuery.data ? <Card size="sm"><CardHeader><CardTitle>Research and completeness</CardTitle></CardHeader><CardContent><ReviewResearchOutcome routeId={draft.routeId} dispatchId={draft.dispatchId} researchMode={routeQuery.data.researchMode} /></CardContent></Card> : null}
      <div className="grid min-w-0 gap-4 xl:grid-cols-2">
        <div className="min-w-0 space-y-4">
          <Card size="sm">
            <CardHeader><CardTitle>Captured source evidence</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {draft.evidenceMap.length ? <div className="space-y-2" aria-label="Exact evidence map">{draft.evidenceMap.map((citation) => <div key={`${citation.evidenceSnapshotId}-${citation.locator}`} className="rounded border p-2 text-xs"><div>{citation.evidenceKey} · {citation.locator}</div><div className="break-all">Excerpt hash {citation.excerptSha256}</div>{citation.sourceUrl ? <a href={citation.sourceUrl} target="_blank" rel="noreferrer" className="text-primary underline">Open original source</a> : <span>Operator-provided text</span>}</div>)}</div> : null}
              {draft.evidence.length ? draft.evidence.map((item) => (
                <article key={item.evidenceSnapshotId} className="min-w-0 rounded-md border p-3">
                  <p dir="auto" className="whitespace-pre-wrap break-words">{item.contentText}</p>
                  <div className="break-all text-xs text-muted-foreground">Snapshot hash {item.contentSha256}</div>
                  {item.sourceUrl ? <a className="mt-2 block break-all text-sm text-primary underline" href={item.sourceUrl} target="_blank" rel="noreferrer">Open original source</a> : <div className="text-sm text-muted-foreground">Operator-provided text</div>}
                </article>
              )) : <p className="text-muted-foreground">No readable evidence is available.</p>}
            </CardContent>
          </Card>
          <Card size="sm">
            <CardHeader><CardTitle>Captured album</CardTitle></CardHeader>
            <CardContent className="grid gap-2 sm:grid-cols-2">
              {draft.media.length ? draft.media.map((item, index) => {
                const previewAvailable = item.fetchStatus === "downloaded" && Boolean(item.checksumSha256 && item.previewUrl)
                return <figure key={item.id} className="min-w-0 overflow-hidden rounded-md border">
                  {!previewAvailable ? <div role="status" className="flex min-h-24 items-center justify-center bg-muted p-3 text-muted-foreground">Captured media preview unavailable</div>
                    : item.kind === "image" || item.kind === "photo" ? <img src={item.previewUrl} alt={`Captured image ${index + 1}`} className="max-h-80 w-full object-contain" />
                      : item.kind === "video" ? <video src={item.previewUrl} controls aria-label={`Captured video ${index + 1}`} className="max-h-80 w-full" />
                        : <a href={item.previewUrl} target="_blank" rel="noreferrer" className="flex min-h-24 items-center justify-center p-3 text-primary underline">Open captured {item.kind}</a>}
                  <figcaption className="p-3">
                  <div className="font-medium">{item.kind} · {item.mimeType ?? "unknown type"}</div>
                  <div className="mt-1 break-all text-xs text-muted-foreground">{item.fetchStatus} · {item.checksumSha256 ?? "no checksum"}</div>
                  </figcaption>
                </figure>
              }) : <p className="text-muted-foreground">This revision has no media.</p>}
            </CardContent>
          </Card>
        </div>
        <Card size="sm" className="min-w-0">
          <CardHeader><CardTitle>Exact revision editor</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <label className="block space-y-2">
              <span className="font-medium">Telegram body</span>
              <textarea aria-label="Telegram body" dir={draft.content.direction} value={body} onChange={(event) => setBody(event.target.value)} className="min-h-64 w-full rounded-md border p-3" />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => editMutation.mutate()} disabled={mutationPending || !editorDirty}>Save as new revision</Button>
              <Button variant="outline" onClick={() => approveMutation.mutate()} disabled={mutationPending || editorDirty || draft.approvalState !== "pending_review"}>Approve exact revision</Button>
            </div>
            <label className="block space-y-2">
              <span className="font-medium">Rejection note</span>
              <textarea value={rejectionNote} onChange={(event) => setRejectionNote(event.target.value)} className="min-h-20 w-full rounded-md border p-3" dir="auto" />
            </label>
            <Button variant="outline" onClick={() => rejectMutation.mutate()} disabled={mutationPending || editorDirty || draft.approvalState !== "pending_review"}>Reject exact revision</Button>
            {editorDirty ? <div role="status" className="text-amber-800">Save editor changes as a new revision before approval or publishing.</div> : null}
            {blockers.length ? (
              <div role="status" className="space-y-1 rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-900">
                {blockers.map((blocker) => <div key={blocker}>{blocker}</div>)}
              </div>
            ) : null}
            <Button onClick={() => publishMutation.mutate()} disabled={!canPublish}>Publish exact revision</Button>
            {publishOutcome ? (
              <div ref={outcomeRef} tabIndex={-1} role="status" className="rounded-md border p-3" dir="auto">
                {publishOutcome.status === "queued" ? "Queued" : publishOutcome.status}: {publishOutcome.publishJobId}
              </div>
            ) : null}
            {activePublishJobId ? (
              <div className="space-y-2 rounded-md border p-3" aria-label="Durable publish status">
                {publishJobQuery.isPending ? <div role="status">Loading durable publish status…</div> : null}
                {publishJobQuery.isError ? <div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(publishJobQuery.error)}</div> : null}
                {publishJobQuery.data ? (
                  <>
                    <div>Durable status: {publishJobQuery.data.status.replaceAll("_", " ")}</div>
                    <div>Operations: {publishJobQuery.data.receipts.map((receipt) => `${receipt.operationIndex + 1} ${receipt.status}`).join(", ") || "not dispatched"}</div>
                    {publishJobQuery.data.publication ? (
                      <div>
                        Remote IDs: {publishJobQuery.data.publication.remoteMessageIds.join(", ")}
                        {publishJobQuery.data.publication.permalink ? <a className="ms-2 text-primary underline" href={publishJobQuery.data.publication.permalink} target="_blank" rel="noreferrer">Open publication</a> : null}
                      </div>
                    ) : null}
                  </>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
