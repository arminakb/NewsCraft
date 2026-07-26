"use client"

import {
  Activity,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  LoaderCircle,
  X,
} from "lucide-react"
import { cloneElement, isValidElement, useId, useRef, useState } from "react"
import type React from "react"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { useNotices } from "@/components/providers/notice-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"
import { useEditorialModal } from "@/components/editorial/use-editorial-modal"
import type { CodexConnection } from "./content-settings-api"
import { getApiErrorMessage } from "@/lib/http"

export const fieldClass =
  "min-h-11 w-full rounded-lg border bg-background px-3 py-2 text-base outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:bg-muted disabled:text-muted-foreground"

export function SettingsSection({
  id,
  icon: Icon,
  title,
  description,
  action,
  children,
}: {
  id: string
  icon: typeof Activity
  title: string
  description: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Card id={id} className="scroll-mt-20">
      <CardHeader className="border-b">
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground"><Icon className="size-5" aria-hidden="true" /></span>
          <div><CardTitle className="text-lg"><h2 className="text-lg font-semibold">{title}</h2></CardTitle><CardDescription className="mt-1">{description}</CardDescription></div>
        </div>
        {action ? <CardAction>{action}</CardAction> : null}
      </CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  )
}

export function SettingsDialog({
  title,
  description,
  dirty,
  pending,
  submitLabel,
  submitDisabled = false,
  onClose,
  onReset,
  onSubmit,
  children,
}: {
  title: string
  description: string
  dirty: boolean
  pending: boolean
  submitLabel: string
  submitDisabled?: boolean
  onClose: () => void
  onReset: () => void
  onSubmit: () => void
  children: React.ReactNode
}) {
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const initialRef = useRef<HTMLElement>(null)
  const releaseDirty = useDirtyNavigation(dirty, "Discard unsaved settings changes?")
  const close = () => {
    if (pending) return
    if (!dirty || window.confirm("Discard unsaved settings changes?")) {
      releaseDirty()
      onClose()
    }
  }
  useEditorialModal({ open: true, containerRef: dialogRef, initialFocusRef: initialRef, onClose: close, canClose: !pending })
  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} tabIndex={-1} className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-slate-950/50 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) close() }}>
      <form className="my-auto w-full max-w-2xl space-y-5 rounded-xl border bg-background p-5 shadow-2xl" onSubmit={(event) => { event.preventDefault(); onSubmit() }}>
        <div className="flex items-start justify-between gap-4">
          <div><h2 id={titleId} className="text-xl font-semibold">{title}</h2><p id={descriptionId} className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p></div>
          <Button type="button" size="icon" variant="ghost" aria-label="Close dialog" disabled={pending} onClick={close}><X aria-hidden="true" /></Button>
        </div>
        {children}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <span className="text-xs text-muted-foreground">{dirty ? "Unsaved changes" : "No unsaved changes"}</span>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" disabled={!dirty || pending} onClick={onReset}>Reset</Button>
            <Button type="button" variant="outline" disabled={pending} onClick={close}>Cancel</Button>
            <Button type="submit" disabled={!dirty || pending || submitDisabled}>{pending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : null}{pending ? "Saving…" : submitLabel}</Button>
          </div>
        </div>
      </form>
    </div>
  )
}

export function SecretDialog({ title, label, onClose, onSave }: { title: string; label: string; onClose: () => void; onSave: (secret: string) => Promise<void> }) {
  const { pushNotice } = useNotices()
  const [secret, setSecret] = useState("")
  const [pending, setPending] = useState(false)
  return (
    <SettingsDialog
      title={title}
      description="Write-only secret. It is cleared immediately after the mutation."
      dirty={Boolean(secret)}
      pending={pending}
      onClose={onClose}
      onReset={() => setSecret("")}
      onSubmit={() => {
        if (!secret) return
        setPending(true)
        void onSave(secret).then(() => { setSecret(""); onClose() }).catch((cause) => pushNotice({ tone: "error", title: "Secret rotation failed", message: getApiErrorMessage(cause) })).finally(() => setPending(false))
      }}
      submitLabel="Rotate secret"
    >
      <Field label={label} required><input autoFocus type="password" autoComplete="new-password" className={fieldClass} value={secret} disabled={pending} onChange={(event) => setSecret(event.target.value)} /></Field>
    </SettingsDialog>
  )
}

export function OneTimeSecretDialog({ title, secret, command, onClose }: { title: string; secret: string; command?: string; onClose: () => void }) {
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  useEditorialModal({ open: true, containerRef: dialogRef, initialFocusRef: closeRef, onClose })
  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4">
      <div className="w-full max-w-2xl space-y-4 rounded-xl border bg-background p-5 shadow-2xl">
        <div><h2 id={titleId} className="text-xl font-semibold">{title}</h2><p className="mt-1 text-sm text-amber-800 dark:text-amber-300">Shown once. Store it safely; never paste it into chat, logs, or Git.</p></div>
        <Field label="One-time pairing code or credential"><DirectionBoundary as="textarea" language="en" readOnly className={`${fieldClass} font-mono`} rows={3} value={secret} /></Field>
        {command ? <Field label="Local exchange command"><DirectionBoundary as="textarea" language="en" readOnly className={`${fieldClass} font-mono text-sm`} rows={5} value={command} /></Field> : null}
        <div className="flex justify-end"><Button ref={closeRef} onClick={onClose}>I stored it safely</Button></div>
      </div>
    </div>
  )
}

export function Field({ label, hint, error, required, children }: { label: string; hint?: string; error?: string | null; required?: boolean; children: React.ReactNode }) {
  const messageId = useId()
  const control = isValidElement<Record<string, unknown>>(children)
    ? cloneElement(children, {
      ...(error ? { "aria-invalid": true } : {}),
      ...((error || hint) ? { "aria-describedby": messageId } : {}),
    })
    : children
  return (
    <label className="grid gap-1.5 text-sm font-medium">
      <span>{label}{required ? <span className="text-red-700 dark:text-red-300" aria-hidden="true"> *</span> : null}</span>
      {control}
      {error ? <span id={messageId} className="text-sm font-normal text-red-700 dark:text-red-300" role="alert">{error}</span> : hint ? <span id={messageId} className="text-xs font-normal text-muted-foreground">{hint}</span> : null}
    </label>
  )
}

export function NumberField({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  return <Field label={label}><input type="number" className={fieldClass} value={value} min={min} max={max} onChange={(event) => onChange(Number(event.target.value))} /></Field>
}

export function ActionButton({ label, icon: Icon, busy, destructive, onClick }: { label: string; icon: typeof Activity; busy?: boolean; destructive?: boolean; onClick: () => void }) {
  return <Button size="sm" variant={destructive ? "destructive" : "outline"} disabled={busy} onClick={onClick}>{busy ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Icon aria-hidden="true" />}{label}</Button>
}

export function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase()
  const bad = ["unhealthy", "unavailable", "red", "revoked", "disabled", "failed", "not configured"].includes(normalized)
  const good = ["healthy", "ready", "green", "active", "enabled", "reachable", "verified", "administrator"].includes(normalized)
  return <Badge variant={bad ? "error" : good ? "success" : "neutral"}>{safeCode(value)}</Badge>
}

export function ReadinessLabel({ label, ready, value }: { label: string; ready: boolean; value: string }) {
  return <Badge className="h-auto gap-1.5 px-2.5 py-1" variant={ready ? "success" : "warning"}>{ready ? <CheckCircle2 className="size-3.5" aria-hidden="true" /> : <CircleAlert className="size-3.5" aria-hidden="true" />}{label}: {safeCode(value)}</Badge>
}

export function HealthStage({ label, value }: { label: string; value: string }) {
  const healthy = ["healthy", "reachable", "authenticated", "resolved", "administrator", "ready", "direct"].includes(value)
  return <div className="rounded-lg bg-muted/60 p-2 text-xs"><div className="font-medium">{label}</div><div className={`mt-1 flex items-center gap-1 ${healthy ? "text-emerald-800 dark:text-emerald-300" : "text-muted-foreground"}`}>{healthy ? <CheckCircle2 className="size-3.5" aria-hidden="true" /> : <CircleDashed className="size-3.5" aria-hidden="true" />}{safeCode(value)}</div></div>
}

export function Metric({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs text-muted-foreground">{label}</dt><dd className="font-medium">{value}</dd></div>
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="rounded-xl border border-dashed p-8 text-center"><h3 className="font-semibold">{title}</h3><p className="mt-1 text-sm text-muted-foreground">{detail}</p></div>
}

export function SettingsSkeleton() {
  return <section className="space-y-5 p-4 md:p-6" role="status" aria-label="Loading content settings"><div className="h-9 w-64 animate-pulse rounded bg-muted" /><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }, (_, index) => <div key={index} className="h-20 animate-pulse rounded-xl bg-muted" />)}</div><div className="h-72 animate-pulse rounded-xl bg-muted" /><span className="sr-only">Loading content settings</span></section>
}

export function safeCode(value: string) {
  return value.replaceAll("_", " ")
}

export function formatDate(value: string | null, fallback = "Unknown") {
  if (!value) return fallback
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? fallback : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parsed)
}

export function connectionColor(status: CodexConnection["status"]) {
  if (status === "green") return "bg-emerald-600"
  if (status === "yellow") return "bg-amber-500"
  if (status === "red") return "bg-red-600"
  return "bg-slate-400"
}

export function lines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean)
}

export function words(value: string) {
  return value.split(/\s+/).map((item) => item.trim()).filter(Boolean)
}

export function parseJsonObject(value: string): { value: Record<string, unknown>; error: string | null } {
  if (!value.trim()) return { value: {}, error: null }
  try {
    const parsed: unknown = JSON.parse(value)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      return { value: {}, error: "Enter a JSON object using braces." }
    }
    return { value: parsed as Record<string, unknown>, error: null }
  } catch {
    return { value: {}, error: "Enter valid JSON with quoted keys and values." }
  }
}

export function formatJsonObject(value: Record<string, unknown>) {
  return JSON.stringify(value, null, 2)
}

export function compactJson(value: Record<string, unknown>) {
  return Object.keys(value).length ? JSON.stringify(value) : "None"
}
