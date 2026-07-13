"use client"

import { useEffect, useMemo, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import {
  createContentPackageExport,
  getExportOutcome,
  getRenderedRevisionHtml,
} from "@/features/packages/api"
import type {
  ExportFormat,
  ExportJobStatus,
  ExportOutcome,
  PlatformRevision,
} from "@/features/packages/types"
import { API_BASE_URL, ApiError, getApiErrorMessage } from "@/lib/http"

const FORMAT_OPTIONS: Array<{ value: ExportFormat; label: string }> = [
  { value: "json", label: "JSON" },
  { value: "markdown", label: "Markdown" },
  { value: "html", label: "HTML" },
  { value: "zip", label: "ZIP" },
]

type CopyChoice = {
  label: string
  success: string
  resolveContent: () => string | Promise<string>
}

export type IntendedExportRevision = {
  variantId: string
  revisionId: string | null
  approvalState: PlatformRevision["approvalState"] | null
}

export type CopyExportActionsProps = {
  revision: PlatformRevision
  intendedRevisions: IntendedExportRevision[]
  pollIntervalMs?: number
}

const MAX_TRANSIENT_POLL_RETRIES = 3

export function CopyExportActions({
  revision,
  intendedRevisions,
  pollIntervalMs = 3_000,
}: CopyExportActionsProps) {
  const copyChoices = useMemo(() => copyChoicesFor(revision), [revision])
  const fallbackRef = useRef<HTMLTextAreaElement>(null)
  const transientPollFailuresRef = useRef(0)
  const exportBindingRef = useRef<{
    exportId: string
    contentPackId: string
    expectedRevisionIdsKey: string
  } | null>(null)
  const [copyStatus, setCopyStatus] = useState<string | null>(null)
  const [copyError, setCopyError] = useState<string | null>(null)
  const [manualCopy, setManualCopy] = useState<string | null>(null)
  const [copyPending, setCopyPending] = useState(false)
  const [formats, setFormats] = useState<ExportFormat[]>(["markdown"])
  const [includeMedia, setIncludeMedia] = useState(false)
  const [submitPending, setSubmitPending] = useState(false)
  const [exportId, setExportId] = useState<string | null>(null)
  const [acceptedStatus, setAcceptedStatus] = useState<ExportJobStatus | null>(null)
  const [outcome, setOutcome] = useState<ExportOutcome | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const revisionIds = intendedRevisions.flatMap((item) => item.revisionId === null ? [] : [item.revisionId])
  const hasExactRevisionSet = intendedRevisions.length > 0
    && revisionIds.length === intendedRevisions.length
    && new Set(intendedRevisions.map((item) => item.variantId)).size === intendedRevisions.length
    && new Set(revisionIds).size === revisionIds.length
  const allIntendedRevisionsApproved = hasExactRevisionSet
    && intendedRevisions.every((item) => item.approvalState === "approved")

  useEffect(() => {
    if (manualCopy === null) return
    fallbackRef.current?.focus()
    fallbackRef.current?.select()
  }, [manualCopy])

  useEffect(() => {
    if (exportId === null || isTerminal(outcome?.status)) return
    let cancelled = false
    let timeout: ReturnType<typeof setTimeout> | undefined

    async function poll() {
      try {
        const next = await getExportOutcome(exportId!)
        if (cancelled) return
        const binding = exportBindingRef.current
        if (binding === null || binding.exportId !== exportId) {
          throw new Error("Export revision binding is unavailable")
        }
        transientPollFailuresRef.current = 0
        setExportError(null)
        if (next.status === "succeeded") {
          const artifact = next.artifact
          if (artifact === null || artifact.contentPackId !== binding.contentPackId) {
            throw new Error("Export content package identity mismatch")
          }
          if (artifact.state === "complete") {
            const returnedIds = artifact.manifest.variants.map((item) => item.revisionId)
            if (canonicalStringSet(returnedIds) !== binding.expectedRevisionIdsKey) throw new Error("Export revision identity mismatch")
          }
        }
        setOutcome(next)
        if (next.status === "failed" || next.status === "needs_review" || next.status === "cancelled") {
          setExportError(next.errorMessage ?? `Export ended with status ${next.status.replaceAll("_", " ")}`)
        }
        if (!isTerminal(next.status)) timeout = setTimeout(() => void poll(), pollIntervalMs)
      } catch (caught) {
        if (cancelled) return
        const message = getApiErrorMessage(caught, "Export status could not be loaded")
        if (isTransientPollFailure(caught) && transientPollFailuresRef.current < MAX_TRANSIENT_POLL_RETRIES) {
          transientPollFailuresRef.current += 1
          setExportError(`${message}. Retrying export status…`)
          timeout = setTimeout(
            () => void poll(),
            pollIntervalMs * (2 ** (transientPollFailuresRef.current - 1)),
          )
        } else {
          setExportError(message)
        }
      }
    }

    timeout = setTimeout(() => void poll(), 0)
    return () => {
      cancelled = true
      if (timeout !== undefined) clearTimeout(timeout)
    }
  }, [exportId, outcome?.status, pollIntervalMs])

  async function copy(choice: CopyChoice) {
    if (copyPending) return
    setCopyPending(true)
    setCopyStatus(null)
    setCopyError(null)
    setManualCopy(null)
    try {
      const content = await choice.resolveContent()
      try {
        if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable")
        await navigator.clipboard.writeText(content)
        setCopyStatus(choice.success)
      } catch {
        setManualCopy(content)
        setCopyError("Clipboard access failed. The exact content is selected below for manual copying.")
      }
    } catch (caught) {
      setCopyError(getApiErrorMessage(caught, "Exact copy content could not be loaded"))
    } finally {
      setCopyPending(false)
    }
  }

  function toggleFormat(format: ExportFormat) {
    setFormats((current) => current.includes(format)
      ? current.filter((value) => value !== format)
      : FORMAT_OPTIONS.map(({ value }) => value).filter((value) => value === format || current.includes(value)))
  }

  async function submitExport() {
    if (submitPending || formats.length === 0 || !allIntendedRevisionsApproved) return
    const requestedRevisionIds = [...revisionIds]
    const requestedContentPackId = revision.contentPackId
    setSubmitPending(true)
    setExportError(null)
    setOutcome(null)
    setExportId(null)
    setAcceptedStatus(null)
    transientPollFailuresRef.current = 0
    exportBindingRef.current = null
    try {
      const accepted = await createContentPackageExport(requestedContentPackId, {
        revisionIds: requestedRevisionIds,
        formats,
        includeMedia,
      })
      exportBindingRef.current = {
        exportId: accepted.jobId,
        contentPackId: requestedContentPackId,
        expectedRevisionIdsKey: canonicalStringSet(requestedRevisionIds),
      }
      setAcceptedStatus(accepted.status)
      setExportId(accepted.jobId)
    } catch (caught) {
      setExportError(getApiErrorMessage(caught, "Export could not be submitted"))
    } finally {
      setSubmitPending(false)
    }
  }

  const visibleStatus = outcome?.status ?? acceptedStatus
  const visibleExportId = outcome?.exportId ?? exportId
  const completeArtifact = outcome?.status === "succeeded" && outcome.artifact?.state === "complete"
    ? outcome.artifact
    : null
  const expiredArtifact = outcome?.status === "succeeded" && outcome.artifact?.state === "expired"
    ? outcome.artifact
    : null

  return (
    <section aria-labelledby="copy-export-heading" className="space-y-5">
      <div>
        <h2 id="copy-export-heading" className="text-lg font-semibold">Copy and export</h2>
        <p className="text-sm text-muted-foreground">Use exact copy from revision {revision.revisionNumber}, or build a durable package export.</p>
      </div>

      <div className="flex flex-wrap gap-2" aria-label="Exact platform copy actions">
        {copyChoices.map((choice) => (
          <Button
            key={choice.label}
            type="button"
            variant="outline"
            disabled={copyPending}
            onClick={() => void copy(choice)}
          >
            {choice.label}
          </Button>
        ))}
      </div>
      {copyStatus ? <div role="status" className="text-sm text-green-700">{copyStatus}</div> : null}
      {copyError ? <div role="alert" className="text-sm text-red-700">{copyError}</div> : null}
      {manualCopy !== null ? (
        <label className="grid gap-1">
          <span>Manual copy content</span>
          <DirectionBoundary
            as="textarea"
            language={null}
            ref={fallbackRef}
            aria-label="Manual copy content"
            className="min-h-32 rounded-lg border p-2 font-mono text-sm"
            readOnly
            value={manualCopy}
            onFocus={(event) => event.currentTarget.select()}
          />
        </label>
      ) : null}

      <fieldset className="space-y-3 rounded-lg border p-4" disabled={submitPending}>
        <legend className="px-1 font-medium">Package export</legend>
        {!hasExactRevisionSet ? (
          <p className="text-sm text-amber-800">Every package variant needs one current revision before export.</p>
        ) : !allIntendedRevisionsApproved ? (
          <p className="text-sm text-amber-800">Approve every intended package revision before exporting.</p>
        ) : null}
        <div className="flex flex-wrap gap-4">
          {FORMAT_OPTIONS.map((option) => (
            <label key={option.value} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={formats.includes(option.value)}
                onChange={() => toggleFormat(option.value)}
              />
              <span>{option.label}</span>
            </label>
          ))}
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={includeMedia}
              onChange={(event) => setIncludeMedia(event.target.checked)}
            />
            <span>Include media</span>
          </label>
        </div>
        <Button
          type="button"
          disabled={formats.length === 0 || submitPending || !allIntendedRevisionsApproved}
          onClick={() => void submitExport()}
        >
          {submitPending ? "Submitting export…" : "Export package"}
        </Button>
      </fieldset>

      {visibleStatus && visibleExportId ? (
        <div role="status" aria-label="Export status" className="break-all rounded-lg border p-3 text-sm">
          {completeArtifact ? <div className="font-medium text-green-700">Export ready</div> : null}
          {expiredArtifact ? (
            <>
              <div className="font-medium text-amber-800">Export expired</div>
              <div>{outcome?.errorMessage ?? "The downloadable export files are no longer available."}</div>
              <div>Expired <time dateTime={expiredArtifact.expiredAt}>{new Date(expiredArtifact.expiredAt).toLocaleString()}</time></div>
            </>
          ) : null}
          <div>{visibleStatus} · {visibleExportId}</div>
        </div>
      ) : null}
      {exportError ? <div role="alert" className="text-sm text-red-700">{exportError}</div> : null}
      {completeArtifact ? (
        <div className="flex flex-wrap gap-3" aria-label="Export downloads">
          {outcome?.downloads.map((download) => (
            <a
              key={download}
              className="text-primary underline"
              href={`${API_BASE_URL}${download}`}
            >
              Download {download.split("/").at(-1)}
            </a>
          ))}
        </div>
      ) : null}
    </section>
  )
}

function copyChoicesFor(revision: PlatformRevision): CopyChoice[] {
  switch (revision.platform) {
    case "telegram":
      return [{
        label: "Copy Telegram formatted message",
        success: "Copied Telegram formatted message",
        resolveContent: () => revision.payload.body,
      }]
    case "instagram": {
      const hashtags = revision.payload.hashtags.join(" ")
      return [{
        label: "Copy Instagram caption and hashtags",
        success: "Copied Instagram caption and hashtags",
        resolveContent: () => [revision.payload.hook, revision.payload.caption, revision.payload.cta, hashtags].filter(Boolean).join("\n\n"),
      }]
    }
    case "x": {
      const posts = [...revision.payload.posts].sort((left, right) => left.order - right.order)
      const fullThread = posts.length === 1
        ? posts[0]?.text ?? ""
        : posts.map((post, index) => `${index + 1}/${posts.length} ${post.text}`).join("\n\n")
      return [
        { label: "Copy full X thread", success: "Copied X thread", resolveContent: () => fullThread },
        ...posts.map((post, index) => ({
          label: `Copy X post ${index + 1}`,
          success: `Copied X post ${index + 1}`,
          resolveContent: () => post.text,
        })),
      ]
    }
    case "blog":
      return [
        { label: "Copy Blog Markdown", success: "Copied Blog Markdown", resolveContent: () => revision.payload.bodyMarkdown },
        {
          label: "Copy Blog HTML",
          success: "Copied Blog HTML",
          resolveContent: () => getRenderedRevisionHtml(revision.id, revision.contentHash),
        },
      ]
  }
}

function isTerminal(status: ExportJobStatus | undefined): boolean {
  return status === "succeeded" || status === "failed" || status === "needs_review" || status === "cancelled"
}

function isTransientPollFailure(caught: unknown): boolean {
  return caught instanceof ApiError
    ? caught.status === 429 || caught.status >= 500
    : caught instanceof TypeError
}

function canonicalStringSet(values: string[]): string {
  return [...values].sort().join(",")
}
