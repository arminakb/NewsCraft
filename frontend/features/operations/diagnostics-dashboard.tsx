import { AlertTriangle, ArrowUpRight, CheckCircle2, CircleHelp, OctagonX } from "lucide-react"
import Link from "next/link"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

import type { OperationComponentHealth, OperationsSnapshot } from "./types"

const componentNames: Record<string, string> = {
  "worker-source-generation": "Source/generation worker",
  "worker-publishing": "Publishing worker",
  scheduler: "Scheduler",
}

const statusPresentation = {
  healthy: { Icon: CheckCircle2, className: "border-emerald-300 text-emerald-800" },
  degraded: { Icon: AlertTriangle, className: "border-amber-300 text-amber-800" },
  down: { Icon: OctagonX, className: "border-red-300 text-red-800" },
  unknown: { Icon: CircleHelp, className: "border-slate-300 text-slate-700" },
} satisfies Record<OperationComponentHealth["status"], { Icon: typeof CircleHelp; className: string }>

export function DiagnosticsDashboard({ snapshot }: { snapshot: OperationsSnapshot }) {
  const components = Object.entries(snapshot.components)
  const queueCounts = Object.entries(snapshot.queueCounts)

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <TruthCard label="Snapshot generated" value={formatTehranTimestamp(snapshot.generatedAt)} />
        <TruthCard
          label="Automation control"
          value={snapshot.globalPaused ? "Operations paused" : "Operations active"}
        />
        <TruthCard label="Publication mode" value={snapshot.dryRun ? "Dry run enabled" : "Live mode enabled"} />
      </div>

      <Card className="rounded-md py-0" size="sm">
        <CardHeader className="border-b px-3 py-3">
          <CardTitle className="text-base">Runtime components</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {components.length ? (
            <div className="divide-y">
              {components.map(([componentId, component]) => (
                <RuntimeComponent key={componentId} componentId={componentId} value={component} />
              ))}
            </div>
          ) : (
            <p className="p-4 text-sm text-muted-foreground">No runtime components are persisted in this snapshot.</p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(260px,0.7fr)_minmax(0,1.3fr)]">
        <Card className="rounded-md py-0" size="sm">
          <CardHeader className="border-b px-3 py-3">
            <CardTitle className="text-base">Durable queue counts</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {queueCounts.length ? (
              <dl className="divide-y">
                {queueCounts.map(([status, count]) => (
                  <div className="flex items-center justify-between gap-3 px-3 py-2" key={status}>
                    <dt className="capitalize">{humanize(status)}</dt>
                    <dd className="font-medium tabular-nums">{count.toLocaleString("en-US")}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="p-4 text-sm text-muted-foreground">No queue counts were returned.</p>
            )}
          </CardContent>
        </Card>

        <Card className="rounded-md py-0" size="sm">
          <CardHeader className="border-b px-3 py-3">
            <CardTitle className="text-base">Attention</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {snapshot.attention.length ? (
              <ul className="divide-y">
                {snapshot.attention.map((item) => (
                  <li className="flex flex-wrap items-start justify-between gap-3 px-3 py-3" key={item.id}>
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={item.severity === "error" ? "destructive" : "outline"}>
                          {item.severity}
                        </Badge>
                        <span className="text-xs capitalize text-muted-foreground">{humanize(item.kind)}</span>
                      </div>
                      <DirectionBoundary className="font-medium" direction="auto">
                        {item.title}
                      </DirectionBoundary>
                      <time className="block text-xs text-muted-foreground" dateTime={item.occurredAt}>
                        {formatTehranTimestamp(item.occurredAt)}
                      </time>
                    </div>
                    <Link
                      aria-label={`Review ${item.title}`}
                      className="inline-flex items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
                      href={item.actionUrl}
                    >
                      Review
                      <ArrowUpRight aria-hidden="true" className="size-3.5" />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="p-4 text-sm text-muted-foreground">No persisted attention items.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function RuntimeComponent({ componentId, value }: { componentId: string; value: OperationComponentHealth }) {
  const label = componentNames[componentId] ?? componentId
  const presentation = statusPresentation[value.status]
  const Icon = presentation.Icon

  return (
    <article className="grid gap-3 px-3 py-3 md:grid-cols-[minmax(220px,0.8fr)_minmax(0,1.2fr)_auto] md:items-start">
      <div className="min-w-0 space-y-1">
        <h3 className="font-medium">{label}</h3>
        <p className="text-xs text-muted-foreground">Component ID: {componentId}</p>
        <Badge className={presentation.className} variant="outline">
          <Icon aria-hidden="true" className="size-3" />
          {value.status}
        </Badge>
      </div>
      <div className="min-w-0 space-y-1 text-sm">
        {value.observedAt ? (
          <p>
            <time dateTime={value.observedAt}>
              {label} last observed {formatTehranTimestamp(value.observedAt)}
            </time>
          </p>
        ) : (
          <p>{label} status {value.status}</p>
        )}
        <p className="text-xs text-muted-foreground">
          {value.lastSuccessAt ? (
            <time dateTime={value.lastSuccessAt}>
              Last successful {formatTehranTimestamp(value.lastSuccessAt)}
            </time>
          ) : (
            "No successful observation recorded"
          )}
        </p>
        <DirectionBoundary className="text-sm text-muted-foreground" direction="auto">
          {value.message}
        </DirectionBoundary>
      </div>
      {value.actionUrl ? (
        <Link
          aria-label={`Open ${label} action`}
          className="inline-flex items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
          href={value.actionUrl}
        >
          Open action
          <ArrowUpRight aria-hidden="true" className="size-3.5" />
        </Link>
      ) : null}
    </article>
  )
}

function TruthCard({ label, value }: { label: string; value: string }) {
  return (
    <Card className="rounded-md" size="sm">
      <CardContent className="space-y-1">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="font-medium">{value}</div>
      </CardContent>
    </Card>
  )
}

export function formatTehranTimestamp(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Tehran",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed)
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ")
}
