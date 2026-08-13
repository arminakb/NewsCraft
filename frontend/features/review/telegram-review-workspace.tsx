"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useMemo, useRef, useState } from "react"

import { useNotices } from "@/components/providers/notice-provider"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge"
import {
  getTelegramDispatches,
  getTelegramPublicationContext,
  getTelegramPublishJob,
  getTelegramRoute,
  publishTelegramDraft,
} from "@/features/automations/telegram-api"
import { getAutomationControl } from "@/features/control/api"
import { getTelegramDestinations } from "@/features/settings/content-settings-api"
import type { TelegramRevision } from "@/features/packages/types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function TelegramReviewWorkspace({ revision }: { revision: TelegramRevision }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const outcomeRef = useRef<HTMLDivElement>(null)
  const [publishOutcome, setPublishOutcome] = useState<{ publishJobId: string; status: string } | null>(null)

  const contextQuery = useQuery({
    queryKey: queryKeys.telegramPublicationContext(revision.id),
    queryFn: () => getTelegramPublicationContext(revision.id),
  })
  const context = contextQuery.data
  const routeQuery = useQuery({
    queryKey: queryKeys.telegramRoute(context?.routeId ?? "unresolved"),
    queryFn: () => getTelegramRoute(context!.routeId!),
    enabled: Boolean(context?.routeId),
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
  const dispatchesQuery = useQuery({
    queryKey: queryKeys.telegramDispatches(context?.routeId ?? "unresolved"),
    queryFn: () => getTelegramDispatches(context!.routeId!),
    enabled: Boolean(context?.routeId && context?.dispatchId),
  })
  const dispatch = dispatchesQuery.data?.find((item) => item.id === context?.dispatchId)
  const activePublishJobId = publishOutcome?.publishJobId ?? context?.publishJobId ?? null
  const publishJobQuery = useQuery({
    queryKey: queryKeys.telegramPublishJob(activePublishJobId ?? "unresolved"),
    queryFn: () => getTelegramPublishJob(activePublishJobId!),
    enabled: Boolean(activePublishJobId),
    refetchInterval: 5_000,
  })

  const publishMutation = useMutation({
    mutationFn: () => publishTelegramDraft(revision.id, revision.contentHash),
    onSuccess: async (result) => {
      setPublishOutcome({ publishJobId: result.job.publishJobId, status: result.job.status })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramPublicationContext(revision.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramPublishJob(result.job.publishJobId) }),
      ])
      requestAnimationFrame(() => outcomeRef.current?.focus())
    },
    onError: (error) => pushNotice({
      tone: "error",
      title: "Publish failed",
      message: getApiErrorMessage(error),
    }),
  })

  const blockers = useMemo(() => {
    const values: string[] = []
    if (contextQuery.isPending) values.push("Publication context is loading")
    if (contextQuery.isError || (contextQuery.isSuccess && !context?.routeId)) {
      values.push("Publication context is unavailable")
    }
    if (controlQuery.isPending || routeQuery.isPending || destinationsQuery.isPending) {
      values.push("Publishing controls are loading")
    }
    if (controlQuery.isError || routeQuery.isError || destinationsQuery.isError || (routeQuery.data && !destination)) {
      values.push("Publishing controls are unavailable")
    }
    if (controlQuery.data?.globalPause) values.push("Global pause blocks publishing")
    if (controlQuery.data?.dryRun) values.push("Global dry run blocks publishing")
    if (routeQuery.data?.pausedAt) values.push("Route paused")
    if (routeQuery.data && !routeQuery.data.enabled) values.push("Route disabled")
    if (destination && !destination.configured) values.push("Destination unavailable")
    if (destination && (!destination.enabled || destination.health_status !== "healthy")) {
      values.push("Destination unhealthy")
    }
    if (revision.payload.dryRun) values.push("Draft dry run blocks publishing")
    if (revision.payload.mediaPolicy === "replace_manually") values.push("Manual media replacement is required")
    if (context?.routeId && context.dispatchId && dispatchesQuery.isPending) {
      values.push("Dispatch and research outcome are loading")
    }
    if (context?.routeId && context.dispatchId && dispatchesQuery.isError) {
      values.push("Dispatch and research outcome are unavailable")
    }
    if (context?.routeId && context.dispatchId && dispatchesQuery.isSuccess && !dispatch) {
      values.push("Expected dispatch is unavailable")
    }
    if (dispatch?.status === "needs_review" || dispatch?.errorCode?.includes("research")) {
      values.push("Review required because research did not complete")
    }
    return values
  }, [
    context,
    contextQuery.isError,
    contextQuery.isPending,
    contextQuery.isSuccess,
    controlQuery.data,
    controlQuery.isError,
    controlQuery.isPending,
    destination,
    destinationsQuery.isError,
    destinationsQuery.isPending,
    dispatch,
    dispatchesQuery.isError,
    dispatchesQuery.isPending,
    dispatchesQuery.isSuccess,
    revision.payload.dryRun,
    revision.payload.mediaPolicy,
    routeQuery.data,
    routeQuery.isError,
    routeQuery.isPending,
  ])

  const canPublish = revision.approvalState === "approved" && blockers.length === 0 && !publishMutation.isPending

  return (
    <section className="nc-page" aria-labelledby="telegram-publication-heading">
      <div>
        <h2 id="telegram-publication-heading" className="text-xl font-semibold">Telegram publication handoff</h2>
        <p className="text-sm text-muted-foreground">
          Publish only the approved revision shown in the editorial studio above.
        </p>
      </div>
      <Card size="sm">
        <CardHeader><CardTitle>Exact revision {revision.revisionNumber}</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {revision.approvalState !== "approved" ? (
            <Alert tone="warning" role="status"><AlertDescription>Approve this exact revision before publishing.</AlertDescription></Alert>
          ) : null}
          {blockers.length ? (
            <Alert tone="warning" role="status">
              <div>
                <AlertTitle>Publishing blocked</AlertTitle>
                <AlertDescription className="space-y-1">
                  {blockers.map((blocker) => <div key={blocker}>{blocker}</div>)}
                </AlertDescription>
              </div>
            </Alert>
          ) : null}
          <details className="rounded-md border p-3" open={blockers.length > 0}>
            <summary className="cursor-pointer font-medium">Advanced publication details{blockers.length ? " — blocker context" : ""}</summary>
            <div className="mt-2 space-y-1 text-sm text-muted-foreground">
              <p className="break-all">Exact hash: {revision.contentHash}</p>
              <p className="break-all">Revision ID: {revision.id}</p>
              <p>Route: {context?.routeId ?? "Unavailable"}</p>
              <p>Destination: {destination?.name ?? "Unavailable"}</p>
            </div>
          </details>
          <Button onClick={() => publishMutation.mutate()} disabled={!canPublish}>Publish exact revision</Button>
          {publishOutcome ? (
            <Alert ref={outcomeRef} tabIndex={-1} tone="success" role="status" dir="auto">
              <AlertDescription>{publishOutcome.status === "queued" ? "Queued" : publishOutcome.status}: {publishOutcome.publishJobId}</AlertDescription>
            </Alert>
          ) : null}
          {activePublishJobId ? (
            <div className="space-y-2 rounded-md border border-border/50 bg-muted/35 p-3 text-[13px]" aria-label="Durable publish status">
              {publishJobQuery.isPending ? <div role="status">Loading durable publish status…</div> : null}
              {publishJobQuery.isError ? <Alert tone="error" role="alert" dir="auto"><AlertDescription>{getApiErrorMessage(publishJobQuery.error)}</AlertDescription></Alert> : null}
              {publishJobQuery.data ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <span>Durable status: {publishJobQuery.data.status.replaceAll("_", " ")}</span>
                    <StatusBadge tone={publishTone(publishJobQuery.data.status)}>{publishJobQuery.data.status.replaceAll("_", " ")}</StatusBadge>
                  </div>
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
    </section>
  )
}

function publishTone(status: string): StatusTone {
  if (["succeeded", "published"].includes(status)) return "success"
  if (["failed", "cancelled"].includes(status)) return "error"
  if (["needs_review", "ambiguous"].includes(status)) return "warning"
  if (["queued", "running", "dispatching"].includes(status)) return "info"
  return "neutral"
}
