"use client"

import { useQuery } from "@tanstack/react-query"
import { ContentPackWorkspace } from "@/components/editorial/content-pack-workspace"
import { getPlatformRevision } from "@/features/packages/api"
import { TelegramReviewWorkspace } from "@/features/review/telegram-review-workspace"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function ExactRevisionReview({ revisionId }: { revisionId: string }) {
  const revision = useQuery({ queryKey: queryKeys.variantRevision(revisionId), queryFn: () => getPlatformRevision(revisionId) })
  if (revision.isPending) return <main role="status" className="p-6">Loading exact revision, variant, and content pack…</main>
  if (revision.isError) return <main role="alert" className="p-6 text-red-700">{getApiErrorMessage(revision.error, "Exact editorial revision could not be loaded")}</main>
  const platform = revision.data.platform
  return <div className="space-y-8"><ContentPackWorkspace packId={revision.data.contentPackId} initialRevisionId={revisionId} />{platform === "telegram" ? <section aria-labelledby="telegram-handoff-heading" className="border-t"><h2 id="telegram-handoff-heading" className="sr-only">Telegram preview, scheduling, and publish handoff</h2><TelegramReviewWorkspace revisionId={revisionId} contentPackId={revision.data.contentPackId} platformVariantId={revision.data.variantId} /></section> : revision.data.approvalState === "approved" ? <section aria-label="Manual publication handoff" className="space-y-2 border-t p-4 md:p-6"><h2 className="text-lg font-semibold">Manual publication handoff</h2><p className="text-sm text-muted-foreground">{platformLabel(platform)} is a manual publication platform. Use this exact approved revision for copy, export, checklist, and calendar handoff; Telegram scheduling and publishing controls do not apply.</p></section> : <section aria-label="Manual publication unavailable" className="space-y-2 border-t p-4 md:p-6"><h2 className="text-lg font-semibold">Manual publication unavailable</h2><p className="text-sm text-muted-foreground">Approve this exact {platformLabel(platform)} revision before manual publication handoff. Telegram scheduling and publishing controls do not apply.</p></section>}</div>
}

function platformLabel(platform: string) {
  if (platform === "instagram") return "Instagram"
  if (platform === "x") return "X"
  if (platform === "blog") return "Blog"
  return platform
}
