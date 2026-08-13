"use client"

import { useDateTime } from "@/components/providers/date-time-provider"
import { formatInTimeZone } from "@/lib/date-time"

type RevisionTimelineItem = {
  id: string
  revisionNumber: number
  parentRevisionId: string | null
  approvalState: string
  origin?: string
  createdBy?: string
  createdAt?: string
  providerProfile?: { name: string; providerType: string } | null
  resolvedModel?: string | null
  validationResults?: Array<{ gate: string; ok: boolean; reason: string | null }>
  validation?: Array<{ code: string; message: string; severity: string }>
}

export function RevisionTimeline<T extends RevisionTimelineItem>({ revisions, activeRevisionId, onSelect, disabled = false }: { revisions: T[]; activeRevisionId: string; onSelect?: (revision: T) => void; disabled?: boolean }) {
  const { timezone } = useDateTime()
  return <section aria-labelledby="revision-history-heading" className="space-y-3">
    <h2 id="revision-history-heading" className="text-lg font-semibold">Immutable revision history</h2>
    {revisions.length ? <ol className="space-y-2">{revisions.map((revision) => <li key={revision.id}>
      <button type="button" disabled={disabled} aria-current={revision.id === activeRevisionId ? "true" : undefined} onClick={() => onSelect?.(revision)} className="w-full rounded-lg border p-3 text-left">
        <strong>Revision {revision.revisionNumber}</strong> · {revision.approvalState.replaceAll("_", " ")}
        <div className="text-xs text-muted-foreground">{revision.parentRevisionId ? `Parent ${revision.parentRevisionId}` : "Initial revision"} · {revision.origin ?? "unknown origin"} · {revision.createdBy ?? "unknown actor"} · {revision.createdAt ? formatInTimeZone(revision.createdAt, timezone) : "time unavailable"}</div>
        {revision.providerProfile ? <div className="text-xs">{revision.providerProfile.name} · {revision.providerProfile.providerType} · {revision.resolvedModel ?? "default model"}</div> : <div className="text-xs">Operator revision</div>}
        {(revision.validationResults ?? []).map((result) => <div key={result.gate} className="text-xs">{result.gate}: {result.ok ? "passed" : result.reason ?? "failed"}</div>)}
        {(revision.validation ?? []).map((issue) => <div key={`${issue.code}-${issue.message}`} className="text-xs">{issue.code}: {issue.message}</div>)}
      </button>
    </li>)}</ol> : <p className="text-muted-foreground">No revisions yet.</p>}
  </section>
}
