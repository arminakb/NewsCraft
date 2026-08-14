"use client"

import { LoaderCircle, Trash2 } from "lucide-react"
import { cloneElement, isValidElement, useEffect, useId, useRef, useState } from "react"

import { EditorialDialog } from "@/components/editorial/editorial-dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import type { CreateSourceInput, SourceSummary } from "@/features/operations/ingestion-types"

export type NewSourceInput = CreateSourceInput

const initialForm = {
  platform: "rss" as const,
  name: "",
  url: "",
  category: "",
  language: "en",
  fetchIntervalMinutes: 30,
}

export function AddSourceDialog({
  error,
  isSubmitting = false,
  onClose,
  onSubmit,
  open,
}: {
  error?: string | null
  isSubmitting?: boolean
  onClose: () => void
  onSubmit: (input: NewSourceInput) => void
  open: boolean
}) {
  const [form, setForm] = useState<NewSourceInput>(initialForm)
  const [touched, setTouched] = useState(false)
  const nameRef = useRef<HTMLInputElement>(null)
  const titleId = useId()
  const descriptionId = useId()
  const validationError = validateSource(form)

  useEffect(() => {
    if (!open) return
    setForm(initialForm)
    setTouched(false)
  }, [open])

  return (
    <EditorialDialog
      canClose={!isSubmitting}
      className="overflow-y-auto"
      describedBy={descriptionId}
      initialFocusRef={nameRef}
      labelledBy={titleId}
      onClose={onClose}
      open={open}
    >
      <form
        aria-busy={isSubmitting}
        className="nc-dialog my-auto w-full max-w-xl space-y-5 p-5"
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
            Add an RSS or Atom feed or public Telegram channel to this source list.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Source type">
            <Select
              onChange={(event) => setForm((current) => ({
                ...current,
                platform: event.target.value as NewSourceInput["platform"],
                url: "",
              }))}
              value={form.platform}
            >
              <option value="rss">RSS feed</option>
              <option value="atom">Atom feed</option>
              <option value="telegram_public">Telegram channel</option>
            </Select>
          </Field>
          <Field
            error={touched && validationError?.field === "name" ? validationError.message : null}
            label="Name"
            required
          >
            <Input
              autoComplete="off"
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
              hint={form.platform === "rss" || form.platform === "atom" ? "Use a complete http:// or https:// feed URL." : "Use @channel, channel name, or a t.me URL."}
              label={form.platform === "rss" || form.platform === "atom" ? "Feed URL" : "Telegram channel"}
              required
            >
              <Input
                autoComplete="url"
                onBlur={() => setTouched(true)}
                onChange={(event) => setForm((current) => ({ ...current, url: event.target.value }))}
                placeholder={form.platform === "rss" || form.platform === "atom" ? "https://example.com/feed.xml" : "@channel"}
                value={form.url}
              />
            </Field>
          </div>
          <Field label="Category">
            <Input
              autoComplete="off"
              onChange={(event) => setForm((current) => ({ ...current, category: event.target.value }))}
              placeholder="General"
              value={form.category}
            />
          </Field>
          <Field label="Language">
            <Input
              autoComplete="off"
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
              <Input
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

        {error ? (
          <p className="rounded-lg border border-destructive/30 bg-[var(--error-surface)] p-3 text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-2 border-t pt-4">
          <Button disabled={isSubmitting} onClick={onClose} type="button" variant="outline">Cancel</Button>
          <Button
            aria-label={isSubmitting ? "Adding source" : "Add source"}
            disabled={Boolean(validationError) || isSubmitting}
            type="submit"
          >
            {isSubmitting ? (
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
            ) : null}
            {isSubmitting ? "Adding" : "Add source"}
          </Button>
        </div>
      </form>
    </EditorialDialog>
  )
}

export function DeleteSourceDialog({
  error,
  isDeleting = false,
  onClose,
  onConfirm,
  source,
}: {
  error?: string | null
  isDeleting?: boolean
  onClose: () => void
  onConfirm: () => void
  source: SourceSummary | null
}) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const descriptionId = useId()

  if (!source) return null

  return (
    <EditorialDialog
      canClose={!isDeleting}
      describedBy={descriptionId}
      initialFocusRef={cancelRef}
      labelledBy={titleId}
      onClose={onClose}
      open
    >
      <div className="nc-dialog w-full max-w-md space-y-5 p-5">
        <div>
          <h2 className="text-xl font-semibold" id={titleId}>Delete source?</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground" id={descriptionId}>
            Remove <strong className="font-semibold text-foreground">{source.name}</strong> from source management.
            Collected items remain unchanged.
          </p>
        </div>
        {error ? (
          <p className="rounded-lg border border-destructive/30 bg-[var(--error-surface)] p-3 text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button disabled={isDeleting} onClick={onClose} ref={cancelRef} type="button" variant="outline">Cancel</Button>
          <Button
            aria-label={isDeleting ? `Deleting ${source.name}` : "Delete source"}
            disabled={isDeleting}
            onClick={onConfirm}
            type="button"
            variant="destructive"
          >
            {isDeleting ? (
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
            ) : (
              <Trash2 className="size-4" aria-hidden="true" />
            )}
            {isDeleting ? "Deleting" : "Delete source"}
          </Button>
        </div>
      </div>
    </EditorialDialog>
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
        {required ? <span className="text-destructive" aria-hidden="true"> *</span> : null}
      </span>
      {control}
      {error ? <span className="text-sm font-normal text-destructive" id={messageId} role="alert">{error}</span> : null}
      {!error && hint ? <span className="text-xs font-normal text-muted-foreground" id={messageId}>{hint}</span> : null}
    </label>
  )
}

function validateSource(form: NewSourceInput): { field: "name" | "url" | "fetchIntervalMinutes"; message: string } | null {
  if (!form.name.trim()) return { field: "name", message: "Enter a source name." }
  if (!isValidSourceUrl(form.platform, form.url)) {
    return {
      field: "url",
        message: form.platform === "rss" || form.platform === "atom"
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
  if (platform === "rss" || platform === "atom") return trimmed
  if (/^https?:\/\/t\.me\//.test(trimmed)) return trimmed
  return `https://t.me/${trimmed.replace(/^@/, "")}`
}
