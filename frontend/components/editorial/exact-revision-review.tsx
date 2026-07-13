"use client"

import { useQuery } from "@tanstack/react-query"
import { ContentPackWorkspace } from "@/components/editorial/content-pack-workspace"
import { TelegramReviewWorkspace } from "@/features/review/telegram-review-workspace"
import { getVariantRevision } from "@/lib/editorial-api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function ExactRevisionReview({ revisionId }: { revisionId: string }) {
  const revision = useQuery({ queryKey: queryKeys.variantRevision(revisionId), queryFn: () => getVariantRevision(revisionId) })
  if (revision.isPending) return <main role="status" className="p-6">Loading exact revision, variant, and content pack…</main>
  if (revision.isError) return <main role="alert" className="p-6 text-red-700">{getApiErrorMessage(revision.error, "Exact editorial revision could not be loaded")}</main>
  return <div className="space-y-8"><ContentPackWorkspace packId={revision.data.contentPackId} initialRevisionId={revisionId} /><section aria-labelledby="telegram-handoff-heading" className="border-t"><h2 id="telegram-handoff-heading" className="sr-only">Telegram preview, scheduling, and publish handoff</h2><TelegramReviewWorkspace revisionId={revisionId} /></section></div>
}
