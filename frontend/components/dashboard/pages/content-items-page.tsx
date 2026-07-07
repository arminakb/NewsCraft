"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, ExternalLink, Eye } from "lucide-react"
import { useMemo, useState } from "react"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { approveContentItem, getContentItem, getContentItems } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { ContentQueueItem } from "@/lib/types"

export function ContentItemsPage({ initialItems }: { initialItems: ContentQueueItem[] }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState("all")
  const [sort, setSort] = useState<"latest" | "score">("latest")
  const [rewriteReadyOnly, setRewriteReadyOnly] = useState(false)
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null)
  const filters = useMemo(
    () => ({
      status: status === "all" ? undefined : status,
      sort,
      isRewriteReady: rewriteReadyOnly ? true : undefined,
      limit: 50,
    }),
    [rewriteReadyOnly, sort, status]
  )
  const contentQuery = useQuery({
    queryKey: [...queryKeys.contentItems, filters],
    queryFn: () => getContentItems(filters),
    initialData: initialItems,
    enabled: process.env.NODE_ENV !== "test",
  })
  const approveMutation = useMutation({
    mutationFn: (id: string) => approveContentItem(id, { notes: "Approved from dashboard" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.contentItems }),
  })
  const selectedListItem = contentQuery.data.find((item) => item.id === selectedItemId)
  const detailQuery = useQuery({
    queryKey: selectedItemId ? ["content-item", selectedItemId] : ["content-item"],
    queryFn: () => getContentItem(selectedItemId as string),
    enabled: Boolean(selectedItemId) && process.env.NODE_ENV !== "test",
    initialData: selectedListItem,
  })
  const selectedItem = detailQuery.data

  return (
    <OperationsPageFrame
      title="Content Items"
      subtitle="Review, classify, and approve captured items."
      actions={
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Status</span>
            <select
              aria-label="Status"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              className="h-9 rounded-md border bg-white px-2 text-sm"
            >
              <option value="all">All</option>
              <option value="new">New</option>
              <option value="queued">Queued</option>
              <option value="approved">Approved</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Sort</span>
            <select
              aria-label="Sort"
              value={sort}
              onChange={(event) => setSort(event.target.value as "latest" | "score")}
              className="h-9 rounded-md border bg-white px-2 text-sm"
            >
              <option value="latest">Latest</option>
              <option value="score">Score</option>
            </select>
          </label>
          <label className="flex h-9 items-center gap-2 rounded-md border px-2 text-sm">
            <input
              type="checkbox"
              checked={rewriteReadyOnly}
              onChange={(event) => setRewriteReadyOnly(event.target.checked)}
            />
            Rewrite-ready only
          </label>
        </div>
      }
    >
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Card className="rounded-md py-0" size="sm">
          <CardContent className="px-0">
            <div className="overflow-x-auto">
              <div className="min-w-[860px]">
                <div className="grid grid-cols-[minmax(340px,1.5fr)_120px_110px_140px_110px_150px] border-b px-3 py-2 text-xs text-muted-foreground">
                <span>Item</span>
                <span>Score</span>
                <span>Category</span>
                <span>Rewrite</span>
                <span>Quality</span>
                <span>Status</span>
                </div>
                <div className="divide-y">
                  {contentQuery.data.map((item) => (
                    <div key={item.id} className="grid grid-cols-[minmax(340px,1.5fr)_120px_110px_140px_110px_150px] items-start gap-3 px-3 py-3 text-sm">
                    <div className="flex min-w-0 items-center gap-3">
                      {item.thumbnailUrl ? <img src={item.thumbnailUrl} alt="" className="h-12 w-16 rounded-md object-cover" /> : <div className="h-12 w-16 rounded-md bg-muted" />}
                      <div className="min-w-0">
                        <div className="line-clamp-2 font-medium leading-snug">{item.title}</div>
                        {item.summary ? <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{item.summary}</div> : null}
                        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                          <span>{item.language}</span>
                          <span>{item.age}</span>
                          {item.canonicalUrl ? (
                            <a href={item.canonicalUrl} className="inline-flex items-center gap-1 text-primary hover:underline">
                              Source
                              <ExternalLink className="size-3" aria-hidden="true" />
                            </a>
                          ) : null}
                        </div>
                        {item.tags?.length ? (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {item.tags.map((tag) => (
                              <Badge key={tag} variant="outline" className="h-5 rounded-md text-[11px]">
                                {tag}
                              </Badge>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div className="font-medium tabular-nums">Score {item.score ?? 0}</div>
                      {Object.keys(item.scoreBreakdown ?? {}).length ? (
                        <div className="text-xs text-muted-foreground">
                          {Object.entries(item.scoreBreakdown ?? {})
                            .map(([key, value]) => `${key}: ${String(value)}`)
                            .join(", ")}
                        </div>
                      ) : null}
                    </div>
                    <div className="space-y-1">
                      <Badge variant="outline" className="h-6 rounded-md">{item.category}</Badge>
                      {item.contentType ? <div className="text-xs text-muted-foreground">{item.contentType}</div> : null}
                      {item.freshnessBucket ? <div className="text-xs text-muted-foreground">{item.freshnessBucket}</div> : null}
                    </div>
                    <div className="space-y-1 text-xs">
                      <div className="font-medium">{item.rewriteBucket ?? "unbucketed"}</div>
                      {item.isRewriteReady ? <Badge variant="outline" className="h-5 rounded-md border-emerald-200 bg-emerald-50 text-emerald-700">Ready</Badge> : null}
                      {item.rewriteReadyReason ? <div className="text-muted-foreground">{item.rewriteReadyReason}</div> : null}
                      {(item.rewriteBlockers ?? []).map((blocker) => (
                        <div key={blocker} className="text-red-600">{blocker}</div>
                      ))}
                    </div>
                    <div className="space-y-1 text-xs">
                      <div className="font-medium">{item.qualityStatus ?? "unknown"}</div>
                      {item.primaryMedia?.quality ? <div className="text-muted-foreground">Media {item.primaryMedia.quality}</div> : null}
                      {item.sourceTier ? <div className="text-muted-foreground">{item.sourceTier}</div> : null}
                      {(item.classificationReasons ?? []).map((reason) => (
                        <div key={reason} className="text-muted-foreground">{reason}</div>
                      ))}
                    </div>
                    <div className="space-y-2 text-right">
                      <Badge variant="outline" className="h-6 rounded-md capitalize">{item.status}</Badge>
                      <Button
                        variant="ghost"
                        className="h-8 gap-2 rounded-md"
                        onClick={() => setSelectedItemId(item.id)}
                      >
                        <Eye className="size-4" aria-hidden="true" />
                        View details
                      </Button>
                      <Button
                        variant="outline"
                        className="h-8 gap-2 rounded-md"
                        onClick={() => approveMutation.mutate(item.id)}
                        disabled={approveMutation.isPending}
                      >
                        <CheckCircle2 className="size-4" aria-hidden="true" />
                        Approve
                      </Button>
                    </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
        {selectedItem ? (
          <aside role="region" aria-label="Content item details" className="rounded-md border bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="line-clamp-2 text-base font-semibold">{selectedItem.title}</h2>
                <div className="mt-1 text-xs text-muted-foreground">{selectedItem.id}</div>
              </div>
              <Badge variant="outline" className="h-6 rounded-md capitalize">{selectedItem.status}</Badge>
            </div>
            {selectedItem.thumbnailUrl ? <img src={selectedItem.thumbnailUrl} alt="" className="mt-4 aspect-video w-full rounded-md object-cover" /> : null}
            {selectedItem.summary ? <p className="mt-4 text-sm leading-6">{selectedItem.summary}</p> : null}
            <dl className="mt-4 space-y-3 text-sm">
              <DetailRow label="Score" value={String(selectedItem.score ?? 0)} />
              <DetailRow label="Category" value={selectedItem.category} />
              <DetailRow label="Quality" value={selectedItem.qualityStatus ?? "unknown"} />
              <DetailRow label="Rewrite" value={selectedItem.rewriteBucket ?? "unbucketed"} />
              <DetailRow label="Ready reason" value={selectedItem.rewriteReadyReason ?? "-"} />
              <DetailRow label="Source tier" value={selectedItem.sourceTier ?? "-"} />
              <DetailRow label="Freshness" value={selectedItem.freshnessBucket ?? "-"} />
              <DetailRow label="URL" value={selectedItem.canonicalUrl ?? "-"} />
            </dl>
          </aside>
        ) : null}
      </div>
    </OperationsPageFrame>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[92px_minmax(0,1fr)] gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{value}</dd>
    </div>
  )
}
