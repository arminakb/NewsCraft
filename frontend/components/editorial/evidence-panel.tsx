"use client"

import { useEffect, useState } from "react"
import type {
  EvidenceCitation,
  EvidenceDetail,
} from "@/features/editorial/types"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"

export function EvidencePanel({ evidence, activeCitation, onSelectCitation }: { evidence: EvidenceDetail[]; activeCitation: EvidenceCitation | null; onSelectCitation?: (citation: EvidenceCitation) => void }) {
  const selected = activeCitation ? evidence.find((item) => item.id === activeCitation.evidenceSnapshotId && item.evidenceKey === activeCitation.evidenceKey) : evidence[0]
  const match = activeCitation?.locator.match(/^chars:(\d+)-(\d+)$/)
  const start = match ? Number(match[1]) : -1
  const end = match ? Number(match[2]) : -1
  const excerpt = selected && match && start >= 0 && end > start && end <= selected.contentText.length ? selected.contentText.slice(start, end) : null
  const [integrity, setIntegrity] = useState<"idle" | "checking" | "verified" | "failed">("idle")
  useEffect(() => {
    let active = true
    if (!activeCitation) { setIntegrity("idle"); return () => { active = false } }
    if (excerpt === null || !globalThis.crypto?.subtle) { setIntegrity("failed"); return () => { active = false } }
    setIntegrity("checking")
    void globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(excerpt)).then((digest) => {
      const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")
      if (active) setIntegrity(actual === activeCitation.excerptSha256 ? "verified" : "failed")
    }).catch(() => { if (active) setIntegrity("failed") })
    return () => { active = false }
  }, [activeCitation, excerpt])
  return (
    <section aria-labelledby="evidence-heading" className="min-w-0 space-y-3">
      <h2 id="evidence-heading" className="text-lg font-semibold">Evidence</h2>
      {!selected ? <p role={activeCitation ? "alert" : undefined} className="text-muted-foreground">{activeCitation ? `Evidence snapshot ${activeCitation.evidenceSnapshotId} is unavailable; the citation was not resolved.` : "No captured evidence is available."}</p> : (
        <article className="min-w-0 space-y-2 rounded-lg border p-3">
          <DirectionBoundary language={null} className="font-medium">{selected.title ?? (selected.sourceUrl ? "Captured source" : "Operator-provided text")}</DirectionBoundary>
          {!selected.sourceUrl ? <div className="text-sm text-muted-foreground">Operator-provided text</div> : null}
          {integrity === "checking" ? <div role="status">Verifying citation integrity…</div> : null}
          {integrity === "verified" && excerpt !== null ? <DirectionBoundary language={null}><blockquote data-testid="evidence-excerpt" tabIndex={-1} className="border-s-4 ps-3 font-medium">{excerpt}</blockquote></DirectionBoundary> : null}
          {integrity === "failed" ? <div role="alert" className="text-destructive">Citation integrity verification failed. Approval-safe excerpt and source link are hidden.</div> : null}
          <DirectionBoundary as="p" language={null} className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-sm">{selected.contentText}</DirectionBoundary>
          <dl className="grid gap-1 break-all text-xs text-muted-foreground">
            {activeCitation ? <>
              <dt>Locator</dt><dd>{activeCitation.locator}</dd>
              <dt>Excerpt hash</dt><dd>{activeCitation.excerptSha256}</dd>
            </> : null}
            <dt>Snapshot hash</dt><dd>{selected.contentSha256}</dd>
            <dt>Captured</dt><dd>{new Date(selected.capturedAt).toLocaleString()}</dd>
          </dl>
          {selected.sourceUrl && (!activeCitation || integrity === "verified") ? <a href={selected.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex text-primary underline">Open original source</a> : null}
        </article>
      )}
      {onSelectCitation && activeCitation ? <button type="button" className="sr-only" onClick={() => onSelectCitation(activeCitation)}>Focus citation</button> : null}
    </section>
  )
}
