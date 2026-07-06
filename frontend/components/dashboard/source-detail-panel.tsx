"use client"

import { Edit3, ExternalLink, X } from "lucide-react"

import { SourceIcon } from "@/components/dashboard/source-icon"
import { StatusBadge } from "@/components/dashboard/status-badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { formatNumber, formatPlatform } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { SourceSummary } from "@/lib/types"

const tabs = ["Overview", "Settings", "History", "Logs"]

export function SourceDetailPanel({
  source,
  open,
  onOpenChange,
}: {
  source: SourceSummary
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const metrics = [
    ["Items (24h)", formatNumber(source.items24h)],
    ["New (24h)", formatNumber(source.new24h)],
    ["Failed (24h)", formatNumber(source.failed24h)],
    ["Total items", formatNumber(source.totalItems)],
    ["Media (24h)", formatNumber(source.media24h)],
    ["Last success", source.lastSuccess ?? "-"],
  ]

  return (
    <aside
      role="region"
      aria-label="Source details"
      data-open={open}
      className={cn(
        "fixed inset-y-0 right-0 z-30 w-[min(100vw,440px)] flex-col border-l bg-white shadow-xl transition-transform xl:sticky xl:top-0 xl:flex xl:h-screen xl:translate-x-0 xl:shadow-none",
        open ? "flex translate-x-0" : "hidden translate-x-full xl:flex xl:translate-x-0"
      )}
    >
      <div className="flex h-14 items-center justify-between border-b px-4">
        <h2 className="font-semibold">Source details</h2>
        <Button variant="ghost" size="icon-sm" aria-label="Close source details" onClick={() => onOpenChange(false)}>
          <X className="size-5" aria-hidden="true" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="flex items-start gap-3">
          <SourceIcon platform={source.platform} className="size-12" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-lg font-semibold">{source.name}</h2>
              <StatusBadge status={source.status} />
            </div>
            <div className="mt-1 text-sm text-muted-foreground">
              {formatPlatform(source.platform)} feed - {source.url}
            </div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>Category: {source.category}</span>
              <span>Language: {source.language}</span>
            </div>
          </div>
        </div>
        <Separator className="my-4" />
        <div role="tablist" aria-label="Source detail tabs" className="flex border-b">
          {tabs.map((tab, index) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={index === 0}
              className={cn(
                "h-10 border-b-2 border-transparent px-3 text-sm text-muted-foreground",
                index === 0 && "border-primary text-primary"
              )}
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-3 gap-3">
          {metrics.map(([label, value]) => (
            <div key={label} className="rounded-md border bg-white p-3">
              <div className="text-xs text-muted-foreground">{label}</div>
              <div className="mt-2 text-2xl tabular-nums">{value}</div>
            </div>
          ))}
        </div>
        <dl className="mt-6 space-y-4 text-sm">
          <Row
            label="Feed URL"
            value={
              <a href={source.url} className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline">
                {source.url}
                <ExternalLink className="size-3" aria-hidden="true" />
              </a>
            }
          />
          <Row label="Source ID" value={source.id} />
          <Row label="Added" value={source.addedAt} />
          <Row label="Last run" value={source.lastSuccess ? `2025-05-18 ${source.lastSuccess}` : "-"} />
          <Row label="Next run" value={source.nextRun ? `${source.nextRun} (10:00)` : "-"} />
          <Row label="Schedule" value="Every 30 minutes" />
          <Row label="Parser" value={source.parser} />
          <Row label="Deduplication" value={source.deduplication} />
          <Row
            label="Status"
            value={
              <span className="inline-flex items-center gap-2">
                <span className="size-2 rounded-full bg-emerald-600" />
                {source.status === "healthy" ? "Healthy" : source.status === "partial" ? "Partial" : "Failed"}
              </span>
            }
          />
        </dl>
        <div className="mt-8 space-y-4">
          <Button variant="outline" className="h-9 gap-2">
            <Edit3 className="size-4" aria-hidden="true" />
            Edit source
          </Button>
          <Separator />
          <Button variant="destructive" className="h-9 bg-transparent px-0 text-red-600 hover:bg-red-50">
            Disable source
          </Button>
        </div>
      </div>
    </aside>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{value}</dd>
    </div>
  )
}
