"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  getTelegramDrafts,
  getTelegramPublishJob,
  reconcileTelegramPublishJob,
} from "@/features/automations/telegram-api"
import type { TelegramDraft, TelegramReconcileInput } from "@/features/automations/telegram-types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function TelegramOutcomes() {
  const query = useQuery({
    queryKey: queryKeys.telegramDrafts({}),
    queryFn: () => getTelegramDrafts({}),
    refetchInterval: 5_000,
  })
  const latestDrafts = Array.from(
    (query.data ?? []).reduce((latest, draft) => {
      const current = latest.get(draft.platformVariantId)
      if (!current || draft.revisionNumber > current.revisionNumber) latest.set(draft.platformVariantId, draft)
      return latest
    }, new Map<string, TelegramDraft>()).values()
  )
  const outcomes = latestDrafts.filter((draft) => draft.publishJobId || draft.publication || draft.approvalState === "pending_review")

  return (
    <Card size="sm" role="region" aria-label="Telegram publication outcomes">
      <CardHeader className="border-b"><CardTitle>Telegram publication outcomes</CardTitle></CardHeader>
      <CardContent className="space-y-3 p-3">
        {query.isPending ? <div role="status">Loading Telegram outcomes…</div> : null}
        {query.isError ? <div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(query.error, "Telegram outcomes could not be loaded")}</div> : null}
        {!query.isPending && !query.isError && !outcomes.length ? <p className="p-4 text-center text-muted-foreground">No Telegram outcomes yet.</p> : null}
        {outcomes.map((draft) => <TelegramOutcomeCard key={draft.id} draft={draft} />)}
      </CardContent>
    </Card>
  )
}

function TelegramOutcomeCard({ draft }: { draft: TelegramDraft }) {
  const needsReconciliation = draft.publishStatus === "reconciliation_required" && Boolean(draft.publishJobId)
  const publishJobQuery = useQuery({
    queryKey: queryKeys.telegramPublishJob(draft.publishJobId ?? "unresolved"),
    queryFn: () => getTelegramPublishJob(draft.publishJobId!),
    enabled: needsReconciliation,
  })

  return (
    <article className="min-w-0 space-y-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href={`/review/${draft.id}`} className="font-medium text-primary underline">Revision {draft.revisionNumber}</Link>
        <span>{outcomeLabel(draft)}</span>
      </div>
      {draft.publication ? (
        <div className="space-y-1">
          <div>Remote IDs: {draft.publication.remoteMessageIds.join(", ")}</div>
          <div>Published: {new Date(draft.publication.publishedAt).toLocaleString()}</div>
          {draft.publication.permalink ? <a href={draft.publication.permalink} target="_blank" rel="noreferrer" className="break-all text-primary underline">Open published Telegram post</a> : null}
        </div>
      ) : null}
      {needsReconciliation ? (
        publishJobQuery.isPending ? <div role="status">Loading reconciliation receipts…</div>
          : publishJobQuery.isError ? <div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(publishJobQuery.error)}</div>
            : publishJobQuery.data ? <TelegramReconciliation jobId={draft.publishJobId!} receiptCount={publishJobQuery.data.receipts.find((receipt) => receipt.status === "ambiguous")?.method === "sendMediaGroup" ? null : 1} /> : null
      ) : null}
    </article>
  )
}

function TelegramReconciliation({ jobId, receiptCount }: { jobId: string; receiptCount: number | null }) {
  const queryClient = useQueryClient()
  const [remoteIds, setRemoteIds] = useState("")
  const [outcome, setOutcome] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: (input: TelegramReconcileInput) => reconcileTelegramPublishJob(jobId, input),
    onSuccess: async (result) => {
      setOutcome(result.reconciliationStatus)
      await queryClient.invalidateQueries({ queryKey: queryKeys.telegramPublishJob(jobId) })
      await queryClient.invalidateQueries({ queryKey: queryKeys.telegramDrafts() })
    },
  })
  const tokens = remoteIds.split(",").map((value) => value.trim())
  const parsed = tokens.map(Number)
  const idsValid = remoteIds.trim().length > 0
    && tokens.every((value) => /^\d+$/.test(value))
    && parsed.every((value) => Number.isSafeInteger(value) && value > 0)
    && new Set(parsed).size === parsed.length
  const countOkay = idsValid && (receiptCount === null || parsed.length === receiptCount)

  return (
    <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50 p-3">
      <strong>Reconciliation required</strong>
      <p>Verify the ambiguous operation in Telegram. Automatic retry is disabled.</p>
      <label className="block space-y-1">
        <span>Verified remote message IDs</span>
        <input value={remoteIds} onChange={(event) => setRemoteIds(event.target.value)} placeholder="501, 502" className="min-h-11 w-full rounded-md border bg-white px-3" inputMode="numeric" aria-invalid={remoteIds.length > 0 && !countOkay} />
      </label>
      {remoteIds.length > 0 && !countOkay ? <div role="alert" className="text-red-700">Enter only the exact positive, unique message IDs separated by commas.</div> : null}
      <div className="flex flex-wrap gap-2">
        <Button disabled={mutation.isPending || !countOkay} onClick={() => mutation.mutate({ outcome: "published", remoteMessageIds: parsed })}>Confirm published IDs</Button>
        <Button variant="outline" disabled={mutation.isPending} onClick={() => mutation.mutate({ outcome: "not_published" })}>Confirm not published</Button>
      </div>
      {mutation.isError ? <div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(mutation.error)}</div> : null}
      {outcome ? <div role="status">Reconciliation: {outcome.replaceAll("_", " ")}</div> : null}
    </div>
  )
}

function outcomeLabel(draft: TelegramDraft) {
  if (draft.publication) return "Published"
  if (draft.publishStatus === "reconciliation_required") return "Reconciliation required"
  if (draft.publishStatus === "attention") return "Publish failed"
  if (draft.publishStatus) return `Publishing: ${draft.publishStatus.replaceAll("_", " ")}`
  return "Waiting for review"
}
