import { ChevronRight } from "lucide-react"
import { useState } from "react"

import { SourceIcon } from "@/components/dashboard/source-icon"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { ContentQueueItem } from "@/lib/types"

const filters = ["All", "AI", "Tech", "Economy", "Farsi"]

export function ContentQueuePanel({ items }: { items: ContentQueueItem[] }) {
  const [filter, setFilter] = useState("All")
  const visibleItems = filter === "All" ? items : items.filter((item) => item.category === filter)

  return (
    <Card role="region" aria-label="Content queue" className="rounded-md py-0" size="sm">
      <CardHeader className="flex-row items-center border-b px-3 py-3">
        <CardTitle className="text-base">
          Content queue <span className="font-normal text-muted-foreground">(next)</span>
        </CardTitle>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex gap-1" aria-label="Content queue filters">
            {filters.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setFilter(item)}
                className={cn(
                  "h-8 rounded-md border px-3 text-sm text-muted-foreground",
                  filter === item && "border-primary bg-cyan-50 text-primary"
                )}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-0">
        <div className="overflow-x-auto">
          <div className="min-w-[760px]">
            <div className="grid grid-cols-[minmax(250px,1.4fr)_150px_90px_48px_54px_80px_28px] border-b px-3 py-2 text-xs text-muted-foreground">
              <span>Item</span>
              <span>Source</span>
              <span>Category</span>
              <span>Lang</span>
              <span>Age</span>
              <span>Status</span>
              <span />
            </div>
            <div className="divide-y">
              {visibleItems.length ? (
                visibleItems.map((item) => (
                  <div key={item.id} className="grid grid-cols-[minmax(250px,1.4fr)_150px_90px_48px_54px_80px_28px] items-center gap-2 px-3 py-2 text-sm">
                    <div className="flex min-w-0 items-center gap-3">
                      {item.thumbnailUrl ? (
                        <img src={item.thumbnailUrl} alt="" className="h-11 w-16 rounded-md object-cover" />
                      ) : (
                        <div className="h-11 w-16 rounded-md bg-muted" />
                      )}
                      <span className="line-clamp-2 min-w-0 text-xs leading-snug">{item.title}</span>
                    </div>
                    <div className="flex min-w-0 items-center gap-2">
                      <SourceIcon platform={item.sourcePlatform} className="size-5" />
                      <span className="truncate text-xs">{item.sourceName}</span>
                    </div>
                    <span className="text-xs">{item.category}</span>
                    <span className="text-xs">{item.language}</span>
                    <span className="text-xs tabular-nums">{item.age}</span>
                    <Badge
                      variant="outline"
                      className={cn(
                        "h-6 rounded-md",
                        item.status === "new" ? "border-blue-200 bg-blue-50 text-blue-700" : "border-slate-200 bg-slate-50 text-slate-700"
                      )}
                    >
                      {item.status === "new" ? "New" : "Queued"}
                    </Badge>
                    <ChevronRight className="size-4 text-muted-foreground" aria-hidden="true" />
                  </div>
                ))
              ) : (
                <div className="px-3 py-8 text-center text-sm text-muted-foreground">No content items yet</div>
              )}
            </div>
          </div>
        </div>
        <div className="flex h-9 items-center justify-end border-t px-3 text-sm">
          <span className="text-muted-foreground">Showing {visibleItems.length} of {items.length}</span>
        </div>
      </CardContent>
    </Card>
  )
}
