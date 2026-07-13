"use client"

import { useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { createManualStory } from "@/lib/editorial-api"
import type { JobAccepted } from "@/lib/editorial-types"
import { getApiErrorMessage } from "@/lib/http"
import { useEditorialModal } from "./use-editorial-modal"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"

const field = "min-h-10 w-full rounded-lg border bg-background px-3 py-2"

export function ManualIntakeDialog({ open, onClose }: { open: boolean; onClose: (result?: JobAccepted) => void }) {
  const [kind, setKind] = useState<"url" | "text">("url")
  const [url, setUrl] = useState("")
  const [title, setTitle] = useState("")
  const [text, setText] = useState("")
  const [sourceLabel, setSourceLabel] = useState("")
  const [sourceUrl, setSourceUrl] = useState("")
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const initialFocusRef = useRef<HTMLInputElement>(null)
  useEditorialModal({ open, containerRef: dialogRef, initialFocusRef, onClose: () => onClose(), canClose: !pending })
  if (!open) return null
  const valid = kind === "url" ? /^https?:\/\//i.test(url) : title.trim().length > 0 && sourceLabel.trim().length > 0 && text.trim().length >= 20 && (!sourceUrl || /^https?:\/\//i.test(sourceUrl))

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!valid) return
    setPending(true); setError(null)
    try {
      const result = await createManualStory(kind === "url" ? { kind, url: url.trim(), title: title.trim() || null } : { kind, title: title.trim(), text: text.trim(), sourceLabel: sourceLabel.trim(), sourceUrl: sourceUrl.trim() || null })
      onClose(result)
    } catch (cause) { setError(getApiErrorMessage(cause, "Manual story could not be queued")) }
    finally { setPending(false) }
  }

  return <div ref={dialogRef} tabIndex={-1} className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-3 sm:p-4" role="dialog" aria-modal="true" aria-label="Add story manually">
    <form className="max-h-[calc(100dvh-1.5rem)] w-full max-w-lg space-y-4 overflow-y-auto rounded-xl bg-white p-4 shadow-xl sm:max-h-[calc(100dvh-2rem)] sm:p-5" onSubmit={submit}>
      <div><h2 className="text-lg font-semibold">Add story manually</h2><p className="text-sm text-muted-foreground">A durable intake job preserves the submitted source.</p></div>
      <div role="tablist" aria-label="Intake type" className="flex gap-2">
        {(["url", "text"] as const).map((value) => <Button key={value} type="button" role="tab" aria-selected={kind === value} variant={kind === value ? "default" : "outline"} onClick={() => setKind(value)}>{value === "url" ? "URL" : "Text"}</Button>)}
      </div>
      {kind === "url" ? <>
        <Field label="Story URL"><input ref={initialFocusRef} className={field} type="url" value={url} onChange={(event) => setUrl(event.target.value)} required /></Field>
        <Field label="Story title (optional)"><DirectionBoundary as="input" language={null} className={field} value={title} maxLength={300} onChange={(event) => setTitle(event.target.value)} /></Field>
      </> : <>
        <Field label="Story title"><DirectionBoundary as="input" language={null} className={field} value={title} maxLength={300} onChange={(event) => setTitle(event.target.value)} required /></Field>
        <Field label="Source label"><DirectionBoundary as="input" language={null} className={field} value={sourceLabel} maxLength={160} onChange={(event) => setSourceLabel(event.target.value)} required /></Field>
        <Field label="Source URL (optional)"><input className={field} type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} /></Field>
        <Field label="Story text"><DirectionBoundary as="textarea" language={null} className={field} rows={7} value={text} onChange={(event) => setText(event.target.value)} minLength={20} required /></Field>
        {text.length > 0 && text.trim().length < 20 ? <div role="alert" className="text-sm text-amber-800">Story text must contain at least 20 characters.</div> : null}
      </>}
      {error ? <div role="alert" dir="auto" className="text-sm text-red-700">{error}</div> : null}
      <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => onClose()} disabled={pending}>Cancel</Button><Button type="submit" disabled={!valid || pending}>{pending ? "Queuing…" : "Add story"}</Button></div>
    </form>
  </div>
}

function Field({ label, children }: { label: string; children: React.ReactElement }) { return <label className="grid gap-1 text-sm font-medium"><span>{label}</span>{children}</label> }
