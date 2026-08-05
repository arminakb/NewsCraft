"use client"

import { ExternalLink, X } from "lucide-react"

import { SourceIcon } from "@/components/dashboard/source-icon"
import { StatusBadge } from "@/components/dashboard/status-badge"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Button } from "@/components/ui/button"
import { formatNumber, formatPlatform } from "@/lib/format"
import { formatInTimeZone } from "@/lib/date-time"
import type { SourceSummary } from "@/features/operations/ingestion-types"

export function SourceDetailPanel({
  source,
  open,
  onOpenChange,
}: {
  source: SourceSummary
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { timezone } = useDateTime()
  if (!open) return null

  const activity = [
    ["Items (24h)", formatNumber(source.items24h)],
    ["New (24h)", formatNumber(source.new24h)],
    ["Failed (24h)", formatNumber(source.failed24h)],
    ["Media (24h)", formatNumber(source.media24h)],
  ]

  return (
    <aside
      aria-label="Source details"
      className="order-first min-w-0 self-start overflow-hidden rounded-lg border border-border/50 bg-card shadow-sm xl:order-none xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)]"
      role="region"
    >
      <header className="flex min-h-14 items-center justify-between gap-3 border-b px-4 py-2">
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Selected source</div>
          <h2 className="text-base font-semibold">Source details</h2>
        </div>
        <Button
          aria-label="Close source details"
          className="size-11 min-h-11 min-w-11"
          onClick={() => onOpenChange(false)}
          type="button"
          variant="ghost"
        >
          <X className="size-5" aria-hidden="true" />
        </Button>
      </header>

      <div className="p-4 xl:max-h-[calc(100vh-8rem)] xl:overflow-y-auto">
        <section aria-labelledby="source-identity-heading">
          <div className="flex items-start gap-3">
            <SourceIcon platform={source.platform} className="size-11 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="min-w-0 break-words text-lg font-semibold leading-6" id="source-identity-heading">
                  {source.name}
                </h3>
                <StatusBadge status={source.status} />
              </div>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                {formatPlatform(source.platform)} source
              </p>
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                <span className="rounded-full border bg-muted/40 px-2.5 py-1">{source.category}</span>
                <span className="rounded-full border bg-muted/40 px-2.5 py-1 uppercase">{source.language}</span>
              </div>
            </div>
          </div>
        </section>

        <section aria-labelledby="source-health-heading" className="mt-4 rounded-lg border border-border/50 bg-muted/25 p-3">
          <h3 className="text-sm font-semibold" id="source-health-heading">Health</h3>
          <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
            <Detail label="Current status" value={<StatusBadge status={source.status} />} />
            <Detail label="Last checked" value={formatCheckedAt(source.lastCheckedAt, timezone)} />
          </dl>
          {source.failureReason ? (
            <p className="mt-3 rounded-md border border-destructive/30 bg-[var(--error-surface)] p-3 text-sm leading-5 text-destructive" role="status">
              {source.failureReason}
            </p>
          ) : null}
        </section>

        <section aria-labelledby="source-activity-heading" className="mt-5">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-semibold" id="source-activity-heading">Activity</h3>
            <span className="text-xs text-muted-foreground">
              <span>{formatNumber(source.totalItems)}</span> total items
            </span>
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-2">
            {activity.map(([label, value]) => (
              <div className="rounded-md border border-border/50 bg-background p-3" key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="mt-1 text-lg font-semibold tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section aria-labelledby="source-connection-heading" className="mt-5 border-t border-border/50 pt-4">
          <h3 className="text-sm font-semibold" id="source-connection-heading">Connection</h3>
          <dl className="mt-3 space-y-4 text-sm">
            <Detail
              label="Source URL"
              value={
                <a
                  className="inline-flex min-w-0 items-start gap-1 break-all text-primary underline-offset-4 hover:underline"
                  href={source.url}
                  rel="noreferrer"
                  target="_blank"
                >
                  <span>{source.url}</span>
                  <ExternalLink className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                </a>
              }
            />
            <Detail label="Fetch interval" value={`Every ${source.fetchIntervalMinutes} minutes`} />
            <Detail label="Last success" value={source.lastSuccess ? formatInTimeZone(source.lastSuccess, timezone) : "No successful fetch yet"} />
            <Detail label="Added" value={formatInTimeZone(source.addedAt, timezone)} />
          </dl>
        </section>
      </div>
    </aside>
  )
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid min-w-0 gap-1">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-foreground">{value}</dd>
    </div>
  )
}

function formatCheckedAt(value: string | null | undefined, timezone: string) {
  if (!value) return "Never checked"
  return formatInTimeZone(value, timezone, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}
