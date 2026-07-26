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
  healthy: { Icon: CheckCircle2, variant: "success" },
  degraded: { Icon: AlertTriangle, variant: "warning" },
  down: { Icon: OctagonX, variant: "error" },
  unknown: { Icon: CircleHelp, variant: "neutral" },
} as const satisfies Record<
  OperationComponentHealth["status"],
  { Icon: typeof CircleHelp; variant: "success" | "warning" | "error" | "neutral" }
>

export function DiagnosticsDashboard({ snapshot }: { snapshot: OperationsSnapshot }) {
  const components = Object.entries(snapshot.components)
  const queueCounts = Object.entries(snapshot.queueCounts)

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <TruthCard label="Snapshot generated" value={formatTehranTimestamp(snapshot.generatedAt)} />
        <TruthCard
          label="Automation control"
          value={snapshot.globalPaused ? "Operations paused" : "Operations active"}
        />
        <TruthCard label="Publication mode" value={snapshot.dryRun ? "Dry run enabled" : "Live mode enabled"} />
        <TruthCard label="Outbound network" value={outboundProxySummary(snapshot)} />
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
                    <dd>
                      <Link
                        className="font-medium tabular-nums text-primary underline-offset-4 hover:underline"
                        href={`/jobs?status=${queueStatusFilter(status)}`}
                      >
                        {count.toLocaleString("en-US")}
                      </Link>
                    </dd>
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
                        <Badge variant={item.severity === "error" ? "error" : "warning"}>
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
                      aria-label={`${attentionActionLabel(item.kind)} ${item.title}`}
                      className="inline-flex items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
                      href={item.actionUrl}
                    >
                      {attentionActionLabel(item.kind)}
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

function outboundProxySummary(snapshot: OperationsSnapshot): string {
  const proxy = snapshot.outboundProxy
  if (proxy.configurationErrorCode) return `Configuration error: ${humanize(proxy.configurationErrorCode)}`
  const route = proxy.mode === "direct" ? "Direct" : `Proxy (${proxy.scheme ?? "unknown"})`
  return `${route} · ${proxy.bypassRuleCount} bypass rules · ${humanize(proxy.lastConnectivityStatus)}`
}

function RuntimeComponent({ componentId, value }: { componentId: string; value: OperationComponentHealth }) {
  const label = componentNames[componentId] ?? componentId
  const presentation = statusPresentation[value.status]
  const Icon = presentation.Icon

  return (
    <article className="grid gap-3 px-3 py-3 md:grid-cols-[minmax(220px,0.8fr)_minmax(0,1.2fr)_auto] md:items-start">
      <div className="min-w-0 space-y-1">
        <h3 className="font-medium">{label}</h3>
        <Badge variant={presentation.variant}>
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
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">Advanced runtime identity</summary>
          <p className="mt-1 break-all">{componentId}</p>
        </details>
      </div>
      {value.actionUrl ? (
        <Link
          aria-label={`Open ${label} action`}
          className="inline-flex items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
          href={value.actionUrl}
        >
          {runtimeActionLabel(value.actionUrl)}
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

function queueStatusFilter(status: string): string {
  return ["failed", "needs_review"].includes(status) ? "attention" : status
}

function attentionActionLabel(kind: OperationsSnapshot["attention"][number]["kind"]): string {
  if (kind === "source") return "Open source"
  if (kind === "destination") return "Repair destination"
  if (kind === "publication") return "Resolve publication"
  if (kind === "job") return "Open job"
  return "Open repair"
}

function runtimeActionLabel(actionUrl: string): string {
  if (actionUrl.startsWith("/jobs")) return "Inspect jobs"
  if (actionUrl.startsWith("/automations")) return "Inspect automations"
  return "Inspect evidence"
}
