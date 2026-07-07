"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, ExternalLink } from "lucide-react"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { SourceIcon } from "@/components/dashboard/source-icon"
import { StatusBadge } from "@/components/dashboard/status-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { approveContentItem, getContentItems } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { ContentQueueItem } from "@/lib/types"

export function ContentItemsPage({ initialItems }: { initialItems: ContentQueueItem[] }) {
  const queryClient = useQueryClient()
  const contentQuery = useQuery({
    queryKey: queryKeys.contentItems,
    queryFn: getContentItems,
    initialData: initialItems,
    enabled: process.env.NODE_ENV !== "test",
  })
  const approveMutation = useMutation({
    mutationFn: (id: string) => approveContentItem(id, { notes: "Approved from dashboard" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.contentItems }),
  })

  return (
    <OperationsPageFrame title="Content Items" subtitle="Review, classify, and approve captured items.">
      <Card className="rounded-md py-0" size="sm">
        <CardContent className="px-0">
          <div className="overflow-x-auto">
            <div className="min-w-[820px]">
              <div className="grid grid-cols-[minmax(300px,1.5fr)_160px_100px_80px_110px] border-b px-3 py-2 text-xs text-muted-foreground">
                <span>Item</span>
                <span>Source</span>
                <span>Category</span>
                <span>Status</span>
                <span className="text-right">Action</span>
              </div>
              <div className="divide-y">
                {contentQuery.data.map((item) => (
                  <div key={item.id} className="grid grid-cols-[minmax(300px,1.5fr)_160px_100px_80px_110px] items-center gap-3 px-3 py-3 text-sm">
                    <div className="flex min-w-0 items-center gap-3">
                      {item.thumbnailUrl ? <img src={item.thumbnailUrl} alt="" className="h-12 w-16 rounded-md object-cover" /> : <div className="h-12 w-16 rounded-md bg-muted" />}
                      <div className="min-w-0">
                        <div className="line-clamp-2 font-medium leading-snug">{item.title}</div>
                        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                          <span>{item.language}</span>
                          <span>{item.age}</span>
                          <ExternalLink className="size-3" aria-hidden="true" />
                        </div>
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center gap-2">
                      <SourceIcon platform={item.sourcePlatform} className="size-5" />
                      <span className="truncate text-xs">{item.sourceName}</span>
                    </div>
                    <Badge variant="outline" className="h-6 rounded-md">{item.category}</Badge>
                    <StatusBadge status={item.status === "new" ? "partial" : "healthy"} />
                    <div className="text-right">
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
    </OperationsPageFrame>
  )
}
