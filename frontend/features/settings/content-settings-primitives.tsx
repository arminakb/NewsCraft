"use client"

import {
  Activity,
  LoaderCircle,
} from "lucide-react"
import { cloneElement, createContext, isValidElement, useContext, useId, useState } from "react"
import type React from "react"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { useNotices } from "@/components/providers/notice-provider"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { controlClassName } from "@/components/ui/input"
import { EmptyState as SharedEmptyState } from "@/components/ui/state-panel"
import { StatusBadge as SharedStatusBadge, type StatusTone } from "@/components/ui/status-badge"
import { guardedNavigation, useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"
import type { CodexConnection } from "./content-settings-api"
import { DEFAULT_TIME_ZONE, formatInTimeZone } from "@/lib/date-time"
import { getApiErrorMessage } from "@/lib/http"
import { cn } from "@/lib/utils"

export const fieldClass = controlClassName
const SettingsPanelContext = createContext(false)

export function SettingsPanel({ children }: { children: React.ReactNode }) {
  return <SettingsPanelContext.Provider value>{children}</SettingsPanelContext.Provider>
}

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
  const headingId = `${id}-heading`
  const embedded = useContext(SettingsPanelContext)

  return (
    <Card
      id={id}
      aria-labelledby={headingId}
      className={cn(
        "focus-visible:ring-2 focus-visible:ring-ring",
        embedded && "rounded-none border-0 bg-transparent shadow-none",
      )}
      role="region"
      tabIndex={-1}
    >
      {embedded ? (
        <>
          <h2 className="sr-only" id={headingId}>{title}</h2>
          {action ? <div className="flex justify-end border-b px-4 py-3 min-[700px]:px-7">{action}</div> : null}
        </>
      ) : (
        <CardHeader className="border-b">
          <div className="flex items-start gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground"><Icon className="size-5" aria-hidden="true" /></span>
            <div><CardTitle className="text-lg"><h2 id={headingId} className="text-lg font-semibold">{title}</h2></CardTitle><CardDescription className="mt-1">{description}</CardDescription></div>
          </div>
          {action ? <CardAction>{action}</CardAction> : null}
        </CardHeader>
      )}
      <CardContent className={cn("space-y-4", embedded && "p-4 min-[700px]:p-7")}>
        {children}
      </CardContent>
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
  const releaseDirty = useDirtyNavigation(dirty, "Discard unsaved settings changes?")
  const close = () => {
    if (pending) return
    guardedNavigation(() => {
      releaseDirty()
      onClose()
    }, "Discard unsaved settings changes?")
  }
  return (
    <Dialog
      open
      disablePointerDismissal={pending}
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      <DialogContent
        className="max-w-2xl p-0"
        overlayClassName="z-[100] bg-black/55"
        viewportClassName="z-[110]"
      >
        <form className="space-y-5 p-5" onSubmit={(event) => { event.preventDefault(); onSubmit() }}>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
        {children}
          <DialogFooter className="justify-between">
          <span className="text-xs text-muted-foreground">{dirty ? "Unsaved changes" : "No unsaved changes"}</span>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" disabled={!dirty || pending} onClick={onReset}>Reset</Button>
              <DialogClose className={buttonVariants({ variant: "outline" })} disabled={pending}>Cancel</DialogClose>
            <Button type="submit" disabled={!dirty || pending || submitDisabled}>{pending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : null}{pending ? "Saving…" : submitLabel}</Button>
          </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function SecretDialog({
  title,
  label,
  onClose,
  onSave,
  onError,
}: {
  title: string
  label: string
  onClose: () => void
  onSave: (secret: string) => Promise<void>
  onError?: (cause: unknown) => void
}) {
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
        void onSave(secret)
          .then(() => { setSecret(""); onClose() })
          .catch((cause) => {
            if (onError) onError(cause)
            else pushNotice({ tone: "error", title: "Secret rotation failed", message: getApiErrorMessage(cause) })
          })
          .finally(() => setPending(false))
      }}
      submitLabel="Rotate secret"
    >
      <Field label={label} required><input autoFocus type="password" autoComplete="new-password" className={fieldClass} value={secret} disabled={pending} onChange={(event) => setSecret(event.target.value)} /></Field>
    </SettingsDialog>
  )
}

export function OneTimeSecretDialog({ title, secret, command, onClose }: { title: string; secret: string; command?: string; onClose: () => void }) {
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent
        className="max-w-2xl space-y-4"
        overlayClassName="z-[100] bg-black/55"
        viewportClassName="z-[110]"
      >
        <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription className="text-warning">Shown once. Store it safely; never paste it into chat, logs, or Git.</DialogDescription></DialogHeader>
        <Field label="One-time pairing code or credential"><DirectionBoundary as="textarea" language="en" readOnly className={`${fieldClass} font-mono`} rows={3} value={secret} /></Field>
        {command ? <Field label="Local exchange command"><DirectionBoundary as="textarea" language="en" readOnly className={`${fieldClass} font-mono text-sm`} rows={5} value={command} /></Field> : null}
        <DialogFooter><DialogClose autoFocus className={buttonVariants()}>I stored it safely</DialogClose></DialogFooter>
      </DialogContent>
    </Dialog>
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
      <span>{label}{required ? <span className="text-destructive" aria-hidden="true"> *</span> : null}</span>
      {control}
      {error ? <span id={messageId} className="text-sm font-normal text-destructive" role="alert">{error}</span> : hint ? <span id={messageId} className="text-xs font-normal text-muted-foreground">{hint}</span> : null}
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
  const tone: StatusTone = bad ? "error" : good ? "success" : "neutral"
  return <SharedStatusBadge tone={tone}>{safeCode(value)}</SharedStatusBadge>
}

export function Metric({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs text-muted-foreground">{label}</dt><dd className="font-medium">{value}</dd></div>
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <SharedEmptyState className="border-dashed p-8" title={title} description={detail} />
}

export function safeCode(value: string) {
  return value.replaceAll("_", " ")
}

export function formatDate(value: string | null, fallback = "Unknown", timezone = DEFAULT_TIME_ZONE) {
  if (!value) return fallback
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? fallback : formatInTimeZone(parsed, timezone)
}

export function connectionColor(status: CodexConnection["status"]) {
  if (status === "green") return "bg-success"
  if (status === "yellow") return "bg-warning"
  if (status === "red") return "bg-destructive"
  return "bg-muted-foreground"
}

export function lines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean)
}

export function words(value: string) {
  return value.split(/\s+/).map((item) => item.trim()).filter(Boolean)
}
