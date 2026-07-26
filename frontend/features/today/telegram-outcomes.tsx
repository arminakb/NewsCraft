"use client"

import { useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { getTelegramPublicationOutcomes } from "@/features/automations/telegram-api"
import type { TelegramPublicationContext } from "@/features/automations/telegram-types"
import { fetchReconciliationCases } from "@/features/operations/api"
import { ReconciliationPanel } from "@/features/operations/reconciliation-panel"
import type { ReconciliationCase } from "@/features/operations/types"
import { getApiErrorMessage } from "@/lib/http"
import { operationsQueryKeys, queryKeys } from "@/lib/query-keys"

export function TelegramOutcomes() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: queryKeys.telegramPublicationOutcomes,
    queryFn: getTelegramPublicationOutcomes,
    refetchInterval: 5_000,
  })
  const reconciliationsQuery = useQuery({
    queryKey: operationsQueryKeys.reconciliations,
    queryFn: fetchReconciliationCases,
    refetchInterval: 5_000,
  })
  const latestDrafts = Array.from(
    (query.data ?? []).reduce((latest, outcome) => {
      const current = latest.get(outcome.platformVariantId)
      if (!current || outcome.revisionNumber > current.revisionNumber) latest.set(outcome.platformVariantId, outcome)
      return latest
    }, new Map<string, TelegramPublicationContext>()).values()
  )
  const outcomes = latestDrafts.filter((draft) => draft.publishJobId || draft.publication || draft.approvalState === "pending_review")
  const reconciliationCases = reconciliationsQuery.data ?? []

  async function refreshResolvedCase() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: operationsQueryKeys.reconciliations }),
      queryClient.invalidateQueries({ queryKey: queryKeys.telegramPublicationOutcomes }),
    ])
  }

  return (
    <Card size="sm" role="region" aria-label="Telegram publication outcomes">
      <CardHeader className="border-b"><CardTitle>Telegram publication outcomes</CardTitle></CardHeader>
      <CardContent className="space-y-3 p-3">
        {query.isPending ? <div role="status">Loading Telegram outcomes…</div> : null}
        {query.isError ? <div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(query.error, "Telegram outcomes could not be loaded")}</div> : null}
        {reconciliationsQuery.isPending ? <div role="status">Loading reconciliation cases…</div> : null}
        {reconciliationsQuery.isError ? (
          <div className="text-red-700" dir="auto" role="alert">
            {getApiErrorMessage(reconciliationsQuery.error, "Reconciliation cases could not be loaded")}
          </div>
        ) : null}
        {reconciliationCases.map((reconciliationCase) => (
          <ReconciliationPanel
            key={reconciliationGenerationKey(reconciliationCase)}
            onResolved={refreshResolvedCase}
            value={reconciliationCase}
          />
        ))}
        {!query.isPending
          && !query.isError
          && !reconciliationsQuery.isPending
          && !reconciliationsQuery.isError
          && !outcomes.length
          && !reconciliationCases.length ? (
            <p className="p-4 text-center text-muted-foreground">No Telegram outcomes yet.</p>
          ) : null}
        {outcomes.map((draft) => <TelegramOutcomeCard key={draft.revisionId} draft={draft} />)}
      </CardContent>
    </Card>
  )
}

function reconciliationGenerationKey(value: ReconciliationCase): string {
  const ambiguousOperation = value.operations.find(
    (operation) => operation.operationKey === value.ambiguousOperationKey,
  )
  return JSON.stringify([
    value.publishJobId,
    value.ambiguousOperationKey,
    ambiguousOperation?.attemptCount ?? null,
    value.ambiguousAt,
  ])
}

function TelegramOutcomeCard({ draft }: { draft: TelegramPublicationContext }) {
  return (
    <article className="min-w-0 space-y-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href={`/review/${draft.revisionId}`} className="font-medium text-primary underline">Revision {draft.revisionNumber}</Link>
        <span>{outcomeLabel(draft)}</span>
      </div>
      {draft.publication ? (
        <div className="space-y-1">
          <div>Remote IDs: {draft.publication.remoteMessageIds.join(", ")}</div>
          <div>Published: {new Date(draft.publication.publishedAt).toLocaleString()}</div>
          {draft.publication.permalink ? <a href={draft.publication.permalink} target="_blank" rel="noreferrer" className="break-all text-primary underline">Open published Telegram post</a> : null}
        </div>
      ) : null}
    </article>
  )
}

function outcomeLabel(draft: TelegramPublicationContext) {
  if (draft.publication) return "Published"
  if (draft.publishStatus === "reconciliation_required") return "Reconciliation required"
  if (draft.publishStatus === "attention") return "Publish failed"
  if (draft.publishStatus) return `Publishing: ${draft.publishStatus.replaceAll("_", " ")}`
  return "Waiting for review"
}
