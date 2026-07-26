"use client"

import { Trash2 } from "lucide-react"
import { cloneElement, isValidElement, useEffect, useId, useRef, useState } from "react"

import { useEditorialModal } from "@/components/editorial/use-editorial-modal"
import { Button } from "@/components/ui/button"
import type { SourceSummary } from "@/features/operations/ingestion-types"

export type NewSourceInput = {
  platform: "rss" | "telegram_public"
  name: string
  url: string
  category: string
  language: string
  fetchIntervalMinutes: number
}

const fieldClass =
  "min-h-11 w-full rounded-lg border bg-background px-3 py-2 text-base outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30"

const initialForm = {
  platform: "rss" as const,
  name: "",
  url: "",
  category: "",
  language: "en",
  fetchIntervalMinutes: 30,
}

export function AddSourceDialog({
  onClose,
  onSubmit,
  open,
}: {
  onClose: () => void
  onSubmit: (input: NewSourceInput) => void
  open: boolean
}) {
  const [form, setForm] = useState<NewSourceInput>(initialForm)
  const [touched, setTouched] = useState(false)
  const dialogRef = useRef<HTMLDivElement>(null)
  const nameRef = useRef<HTMLInputElement>(null)
  const titleId = useId()
  const descriptionId = useId()
  const validationError = validateSource(form)

  useEffect(() => {
    if (!open) return
    setForm(initialForm)
    setTouched(false)
  }, [open])

  useEditorialModal({
    open,
    containerRef: dialogRef,
    initialFocusRef: nameRef,
    onClose,
  })

  if (!open) return null

  return (
    <div
      aria-describedby={descriptionId}
      aria-labelledby={titleId}
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-slate-950/45 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      ref={dialogRef}
      role="dialog"
      tabIndex={-1}
    >
      <form
        className="my-auto w-full max-w-xl space-y-5 rounded-xl border bg-background p-5 shadow-xl"
        onSubmit={(event) => {
          event.preventDefault()
          setTouched(true)
          if (validationError) return
          onSubmit({
            ...form,
            name: form.name.trim(),
            url: normalizeSourceUrl(form.platform, form.url),
            category: form.category.trim() || "General",
            language: form.language.trim().toLowerCase() || "en",
          })
        }}
      >
        <div>
          <h2 className="text-xl font-semibold" id={titleId}>Add source</h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground" id={descriptionId}>
            Add an RSS feed or public Telegram channel to this source list.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Source type">
            <select
              className={fieldClass}
              onChange={(event) => setForm((current) => ({
                ...current,
                platform: event.target.value as NewSourceInput["platform"],
                url: "",
              }))}
              value={form.platform}
            >
              <option value="rss">RSS feed</option>
              <option value="telegram_public">Telegram channel</option>
            </select>
          </Field>
          <Field
            error={touched && validationError?.field === "name" ? validationError.message : null}
            label="Name"
            required
          >
            <input
              autoComplete="off"
              className={fieldClass}
              maxLength={100}
              onBlur={() => setTouched(true)}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              ref={nameRef}
              value={form.name}
            />
          </Field>
          <div className="sm:col-span-2">
            <Field
              error={touched && validationError?.field === "url" ? validationError.message : null}
              hint={form.platform === "rss" ? "Use a complete http:// or https:// feed URL." : "Use @channel, channel name, or a t.me URL."}
              label={form.platform === "rss" ? "Feed URL" : "Telegram channel"}
              required
            >
              <input
                autoComplete="url"
                className={fieldClass}
                onBlur={() => setTouched(true)}
                onChange={(event) => setForm((current) => ({ ...current, url: event.target.value }))}
                placeholder={form.platform === "rss" ? "https://example.com/feed.xml" : "@channel"}
                value={form.url}
              />
            </Field>
          </div>
          <Field label="Category">
            <input
              autoComplete="off"
              className={fieldClass}
              onChange={(event) => setForm((current) => ({ ...current, category: event.target.value }))}
              placeholder="General"
              value={form.category}
            />
          </Field>
          <Field label="Language">
            <input
              autoComplete="off"
              className={fieldClass}
              maxLength={12}
              onChange={(event) => setForm((current) => ({ ...current, language: event.target.value }))}
              value={form.language}
            />
          </Field>
          <div className="sm:col-span-2">
            <Field
              error={touched && validationError?.field === "fetchIntervalMinutes" ? validationError.message : null}
              hint="Between 5 minutes and 7 days."
              label="Fetch interval (minutes)"
              required
            >
              <input
                className={fieldClass}
                max={10_080}
                min={5}
                onBlur={() => setTouched(true)}
                onChange={(event) => setForm((current) => ({
                  ...current,
                  fetchIntervalMinutes: Number(event.target.value),
                }))}
                type="number"
                value={form.fetchIntervalMinutes}
              />
            </Field>
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t pt-4">
          <Button onClick={onClose} type="button" variant="outline">Cancel</Button>
          <Button disabled={Boolean(validationError)} type="submit">Add source</Button>
        </div>
      </form>
    </div>
  )
}

export function DeleteSourceDialog({
  onClose,
  onConfirm,
  source,
}: {
  onClose: () => void
  onConfirm: () => void
  source: SourceSummary | null
}) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const descriptionId = useId()

  useEditorialModal({
    open: Boolean(source),
    containerRef: dialogRef,
    initialFocusRef: cancelRef,
    onClose,
  })

  if (!source) return null

  return (
    <div
      aria-describedby={descriptionId}
      aria-labelledby={titleId}
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-slate-950/45 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      ref={dialogRef}
      role="dialog"
      tabIndex={-1}
    >
      <div className="w-full max-w-md space-y-5 rounded-xl border bg-background p-5 shadow-xl">
        <div>
          <h2 className="text-xl font-semibold" id={titleId}>Delete source?</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground" id={descriptionId}>
            Remove <strong className="font-semibold text-foreground">{source.name}</strong> from source management.
            Collected items remain unchanged.
          </p>
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose} ref={cancelRef} type="button" variant="outline">Cancel</Button>
          <Button onClick={onConfirm} type="button" variant="destructive">
            <Trash2 className="size-4" aria-hidden="true" />
            Delete source
          </Button>
        </div>
      </div>
    </div>
  )
}

function Field({
  children,
  error,
  hint,
  label,
  required,
}: {
  children: React.ReactNode
  error?: string | null
  hint?: string
  label: string
  required?: boolean
}) {
  const messageId = useId()
  const control = isValidElement<Record<string, unknown>>(children)
    ? cloneElement(children, {
      "aria-label": label,
      ...(error ? { "aria-invalid": true } : {}),
      ...((error || hint) ? { "aria-describedby": messageId } : {}),
    })
    : children

  return (
    <label className="grid gap-1.5 text-sm font-medium">
      <span>
        {label}
        {required ? <span className="text-red-700" aria-hidden="true"> *</span> : null}
      </span>
      {control}
      {error ? <span className="text-sm font-normal text-red-700" id={messageId} role="alert">{error}</span> : null}
      {!error && hint ? <span className="text-xs font-normal text-muted-foreground" id={messageId}>{hint}</span> : null}
    </label>
  )
}

function validateSource(form: NewSourceInput): { field: "name" | "url" | "fetchIntervalMinutes"; message: string } | null {
  if (!form.name.trim()) return { field: "name", message: "Enter a source name." }
  if (!isValidSourceUrl(form.platform, form.url)) {
    return {
      field: "url",
      message: form.platform === "rss"
        ? "Enter a valid http:// or https:// feed URL."
        : "Enter a public Telegram channel or t.me URL.",
    }
  }
  if (!Number.isInteger(form.fetchIntervalMinutes) || form.fetchIntervalMinutes < 5 || form.fetchIntervalMinutes > 10_080) {
    return { field: "fetchIntervalMinutes", message: "Fetch interval must be between 5 and 10,080 minutes." }
  }
  return null
}

function isValidSourceUrl(platform: NewSourceInput["platform"], value: string) {
  const trimmed = value.trim()
  if (platform === "telegram_public") {
    return /^(?:https?:\/\/t\.me\/|@)?[A-Za-z0-9_]{5,}$/.test(trimmed)
  }
  try {
    const url = new URL(trimmed)
    return url.protocol === "http:" || url.protocol === "https:"
  } catch {
    return false
  }
}

function normalizeSourceUrl(platform: NewSourceInput["platform"], value: string) {
  const trimmed = value.trim()
  if (platform === "rss") return trimmed
  if (/^https?:\/\/t\.me\//.test(trimmed)) return trimmed
  return `https://t.me/${trimmed.replace(/^@/, "")}`
}
