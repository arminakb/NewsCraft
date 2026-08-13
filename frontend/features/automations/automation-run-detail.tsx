"use client"

import { ExternalLink, FileText, Wrench } from "lucide-react"
import Link from "next/link"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge"

import type { AutomationRun } from "./automation-types"

const privateKey = /api.?key|authorization|credential|password|secret|access.?token|refresh.?token|raw.?(prompt|response)|prompt.?(body|text)|system.?prompt|stack.?trace|traceback|request.?headers|response.?headers|messages/i

export function AutomationRunDetail({ run }: { run: AutomationRun }) {
  const version = scalar(run.resourceSnapshot.automationVersion) ?? short(run.automationVersionId)
  const recovery = recoveryFor(run.safeErrorCode)

  return (
    <div className="flex flex-col gap-4" aria-label={`Run ${short(run.id)} details`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Persisted run</p>
          <h3 className="font-heading text-lg font-semibold">Run {short(run.id)}</h3>
          <p className="mt-1 text-sm text-muted-foreground">Version {version} · {run.dryRun ? "Dry run" : "Live"} · {humanize(run.triggerKind)}</p>
        </div>
        <StatusBadge tone={runTone(run.status)}>{humanize(run.status)}</StatusBadge>
      </div>

      {run.safeErrorCode ? (
        <Alert tone="error" role="alert">
          <Wrench aria-hidden="true" />
          <div>
            <AlertTitle>{humanize(run.safeErrorCode)}</AlertTitle>
            <AlertDescription>{run.safeErrorMessage || recovery.cause} {recovery.action}</AlertDescription>
          </div>
        </Alert>
      ) : null}

      <dl className="grid gap-3 rounded-xl border border-border/60 bg-muted/20 p-3 text-sm sm:grid-cols-3">
        <Metric label="Started" value={dateTime(run.startedAt ?? run.createdAt)} />
        <Metric label="Duration" value={duration(run.startedAt, run.finishedAt)} />
        <Metric label="Current stage" value={run.currentNodeId ? humanize(run.currentNodeId) : "Complete"} />
      </dl>

      <div className="flex flex-col gap-3" aria-label="Persisted node results">
        {run.nodes.map((node, index) => {
          const jobId = node.workflowJobId
          const revisionId = node.platformVariantRevisionId
          const summary = safeEntries({ ...node.inputSummary, ...node.outputSummary })
          const usage = safeEntries(node.usage)
          return (
            <Card key={node.id} size="sm" role="article" aria-label={`Step ${index + 1}: ${humanize(node.nodeId)}`}>
              <CardHeader className="border-b">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle>{index + 1}. {humanize(node.nodeId)}</CardTitle>
                  <StatusBadge tone={runTone(node.status)}>{humanize(node.status)}</StatusBadge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {node.artifact ? (
                  <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/15 bg-primary/5 p-2.5" aria-label={`Artifact ${humanize(node.artifact.kind)} with capabilities ${node.artifact.capabilities.join(", ")}`}>
                    <StatusBadge tone="info">{humanize(node.artifact.kind)} artifact</StatusBadge>
                    <span className="text-xs text-muted-foreground">{node.artifact.capabilities.join(" · ")}</span>
                  </div>
                ) : null}
                <dl className="grid gap-2 text-[13px] sm:grid-cols-2">
                  <Metric label="Attempt" value={String(node.attempt)} />
                  <Metric label="Timing" value={duration(node.startedAt, node.finishedAt)} />
                  {summary.map(([key, value]) => <Metric key={key} label={humanize(key)} value={value} />)}
                  {usage.map(([key, value]) => <Metric key={`usage-${key}`} label={`Usage · ${humanize(key)}`} value={value} />)}
                </dl>
                {node.safeErrorCode && node.safeErrorCode !== run.safeErrorCode ? (
                  <p className="text-sm text-destructive" role="alert">{humanize(node.safeErrorCode)}: {node.safeErrorMessage || recoveryFor(node.safeErrorCode).cause}</p>
                ) : null}
                {node.retryMetadata.retryable === true ? <p className="text-xs text-muted-foreground">Retryable through related durable Job.</p> : null}
                <div className="flex flex-wrap gap-2">
                  {revisionId ? <Link className={buttonVariants({ variant: "outline", size: "sm" })} href={`/review/${revisionId}`}><FileText data-icon="inline-start" aria-hidden="true" />Open exact revision</Link> : null}
                  {jobId ? <Link className={buttonVariants({ variant: "outline", size: "sm" })} href={`/operations?view=jobs&job=${jobId}`}><ExternalLink data-icon="inline-start" aria-hidden="true" />Related Job</Link> : null}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="break-words font-medium">{value}</dd></div>
}

function safeEntries(value: Record<string, unknown>) {
  return Object.entries(value)
    .filter(([key, item]) => !privateKey.test(key) && item !== null && item !== undefined && item !== "")
    .slice(0, 12)
    .map(([key, item]) => [key, scalar(item)] as const)
    .filter((item): item is readonly [string, string] => item[1] !== null)
}

function scalar(value: unknown): string | null {
  if (["string", "number", "boolean"].includes(typeof value)) return String(value).slice(0, 500)
  if (Array.isArray(value) && value.every((item) => ["string", "number", "boolean"].includes(typeof item))) return value.slice(0, 10).join(", ").slice(0, 500)
  return null
}

function recoveryFor(code: string | null) {
  if (!code) return { cause: "Run stopped safely.", action: "Inspect related Job for operational detail." }
  if (code.includes("resource") || code.includes("capability")) return { cause: "Required resource is unavailable.", action: "Repair resource in Settings, then start a new dry run." }
  if (code.includes("validation") || code.includes("input")) return { cause: "Saved version or input failed validation.", action: "Correct highlighted workflow step, save, and validate again." }
  if (code.includes("pause")) return { cause: "Workflow execution is paused.", action: "Resume workflow before testing again." }
  return { cause: "Run stopped at this persisted step.", action: "Open related Job in Operations Center for next action." }
}

function runTone(status: string): StatusTone {
  if (status === "succeeded") return "success"
  if (["failed", "cancelled"].includes(status)) return "error"
  if (["queued", "running"].includes(status)) return "info"
  if (["warning", "waiting_for_review"].includes(status)) return "warning"
  return "neutral"
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function short(value: string) {
  return value.slice(0, 8)
}

function dateTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not started"
}

function duration(startedAt: string | null, finishedAt: string | null) {
  if (!startedAt) return "Not started"
  if (!finishedAt) return "In progress"
  const milliseconds = Math.max(0, new Date(finishedAt).getTime() - new Date(startedAt).getTime())
  if (milliseconds < 1_000) return `${milliseconds} ms`
  if (milliseconds < 60_000) return `${(milliseconds / 1_000).toFixed(1)} s`
  return `${Math.floor(milliseconds / 60_000)}m ${Math.floor((milliseconds % 60_000) / 1_000)}s`
}
