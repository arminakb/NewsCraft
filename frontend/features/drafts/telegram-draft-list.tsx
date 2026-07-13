"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { getTelegramDrafts } from "@/features/automations/telegram-api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"

export function TelegramDraftList({ approvalState }: { approvalState?: "draft" | "pending_review" | "approved" | "rejected" }) {
  const query = useQuery({
    queryKey: queryKeys.telegramDrafts({}),
    queryFn: () => getTelegramDrafts({}),
  })
  const latestDrafts = Array.from(
    (query.data ?? []).reduce((latest, draft) => {
      const current = latest.get(draft.platformVariantId)
      if (!current || draft.revisionNumber > current.revisionNumber) latest.set(draft.platformVariantId, draft)
      return latest
    }, new Map<string, NonNullable<typeof query.data>[number]>()).values()
  ).filter((draft) => !approvalState || draft.approvalState === approvalState)

  if (query.isPending) return <div role="status" className="p-6">Loading Telegram drafts…</div>
  if (query.isError) return <div role="alert" dir="auto" className="p-6 text-red-700">{getApiErrorMessage(query.error, "Telegram drafts could not be loaded")}</div>

  return (
    <section className="min-w-0 space-y-4 p-4 md:p-6" aria-labelledby="telegram-drafts-heading">
      <div>
        <h1 id="telegram-drafts-heading" className="text-2xl font-semibold">Telegram drafts</h1>
        <p className="text-muted-foreground">Review and publish exact immutable revisions.</p>
      </div>
      {latestDrafts.length ? (
        <div className="grid min-w-0 gap-3 lg:grid-cols-2">
          {latestDrafts.map((draft) => (
            <Card key={draft.id} size="sm" className="min-w-0">
              <CardHeader><CardTitle>Revision {draft.revisionNumber}</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap gap-2 text-sm"><span>{draft.approvalState.replaceAll("_", " ")}</span>{draft.publishStatus ? <span>· {draft.publishStatus.replaceAll("_", " ")}</span> : null}</div>
                <DirectionBoundary as="p" direction={draft.content.direction} className="line-clamp-4 whitespace-pre-wrap break-words">{draft.content.body}</DirectionBoundary>
                <Link className="inline-flex min-h-11 items-center text-primary underline" href={`/review/${draft.id}`}>Review exact revision</Link>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : <Card size="sm"><CardContent className="p-8 text-center text-muted-foreground">No Telegram drafts match this queue.</CardContent></Card>}
    </section>
  )
}
