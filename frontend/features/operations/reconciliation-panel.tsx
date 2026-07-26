"use client"

import { useId, useState } from "react"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { getApiErrorMessage } from "@/lib/http"

import { submitReconciliationDecision } from "./api"
import { formatTehranTimestamp } from "./diagnostics-dashboard"
import type {
  ReconciliationCase,
  ReconciliationDecision,
  ReconciliationDecisionResult,
} from "./types"

type SelectedOutcome = ReconciliationDecision["outcome"]

export function ReconciliationPanel({
  onResolved,
  value,
}: {
  onResolved?: (result: ReconciliationDecisionResult) => void | Promise<void>
  value: ReconciliationCase
}) {
  const instanceId = useId()
  const [selectedOutcome, setSelectedOutcome] = useState<SelectedOutcome | null>(null)
  const [remoteIdsInput, setRemoteIdsInput] = useState("")
  const [permalink, setPermalink] = useState("")
  const [operatorNote, setOperatorNote] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const operations = [...value.operations].sort(
    (left, right) => left.operation_index - right.operation_index,
  )
  const ambiguousOperation = operations.find(
    (operation) => operation.operation_key === value.ambiguous_operation_key,
  )
  const canConfirmPublished = ambiguousOperation?.status === "ambiguous"
    && operations.every(
      (operation) => operation.operation_key === value.ambiguous_operation_key || operation.status === "succeeded",
    )
  const publishedBlockedReasonId = `${instanceId}-published-blocked-reason`
  const allowsMultipleIds = ambiguousOperation?.method === "sendMediaGroup"
  const remoteIds = parseRemoteIds(remoteIdsInput)
  const remoteIdsValid = remoteIds.valid
    && (allowsMultipleIds ? remoteIds.values.length >= 2 : remoteIds.values.length === 1)
  const noteValid = operatorNote.trim().length >= 5

  function selectOutcome(outcome: SelectedOutcome) {
    setSelectedOutcome(outcome)
    setError(null)
    setSuccessMessage(null)
  }

  async function submitDecision(decision: ReconciliationDecision) {
    if (isSubmitting) return
    setIsSubmitting(true)
    setError(null)
    setSuccessMessage(null)
    try {
      const result = await submitReconciliationDecision(value.publish_job_id, decision)
      setSuccessMessage(resultMessage(result))
      try {
        await onResolved?.(result)
      } catch {
        // The decision is already durable; polling can recover a failed local refresh.
      }
    } catch (caught) {
      setError(getApiErrorMessage(caught, "Reconciliation decision could not be saved"))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Card
      aria-busy={isSubmitting}
      aria-label={`Telegram reconciliation for ${value.destination.target_ref}`}
      className="rounded-md py-0"
      role="region"
      size="sm"
    >
      <CardHeader className="border-b px-3 py-3">
        <CardTitle className="text-base">Telegram reconciliation</CardTitle>
        <p className="text-sm text-muted-foreground">
          Automatic retry is blocked until an operator verifies the durable evidence below.
        </p>
      </CardHeader>

      <CardContent className="space-y-5 p-4">
        <section aria-labelledby={`${instanceId}-destination`} className="grid gap-3 sm:grid-cols-2">
          <div>
            <h2 className="text-xs font-medium text-muted-foreground" id={`${instanceId}-destination`}>
              Destination
            </h2>
            <DirectionBoundary className="mt-1 font-medium" direction="auto">
              {value.destination.name}
            </DirectionBoundary>
            <bdi className="block text-sm text-muted-foreground" dir="ltr">
              {value.destination.target_ref}
            </bdi>
          </div>
          <div>
            <h2 className="text-xs font-medium text-muted-foreground">Ambiguity</h2>
            <DirectionBoundary className="mt-1" direction="auto">
              {value.ambiguity_reason}
            </DirectionBoundary>
            {value.ambiguous_at ? (
              <time className="block text-xs text-muted-foreground" dateTime={value.ambiguous_at}>
                Ambiguous at {formatTehranTimestamp(value.ambiguous_at)}
              </time>
            ) : (
              <p className="text-xs text-muted-foreground">No ambiguity timestamp was persisted.</p>
            )}
          </div>
        </section>

        <section aria-labelledby={`${instanceId}-operations`} className="space-y-2">
          <h2 className="font-medium" id={`${instanceId}-operations`}>Persisted operations</h2>
          <ol className="space-y-2">
            {operations.map((operation) => (
              <li
                className="grid gap-3 rounded-md border bg-slate-50 p-3 text-sm md:grid-cols-2"
                data-testid="reconciliation-operation"
                key={operation.operation_key}
              >
                <dl className="space-y-2">
                  <div>
                    <dt className="text-xs text-muted-foreground">Operation key</dt>
                    <dd><code className="break-all" dir="ltr">{operation.operation_key}</code></dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Request hash</dt>
                    <dd><code className="break-all" dir="ltr">{operation.request_hash}</code></dd>
                  </div>
                </dl>
                <dl className="space-y-2">
                  <div>
                    <dt className="text-xs text-muted-foreground">Method and status</dt>
                    <dd>{operation.method} · {humanize(operation.status)} · attempt {operation.attempt_count}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Durable send time</dt>
                    <dd>
                      {operation.sent_at ? (
                        <time dateTime={operation.sent_at}>{formatTehranTimestamp(operation.sent_at)}</time>
                      ) : (
                        "No durable send time recorded"
                      )}
                    </dd>
                  </div>
                </dl>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby={`${instanceId}-verification`} className="space-y-2 rounded-md border border-amber-300 bg-amber-50 p-3">
          <h2 className="font-medium" id={`${instanceId}-verification`}>
            Verify in Telegram before choosing an outcome
          </h2>
          <ol className="list-decimal space-y-1 ps-5 text-sm">
            <li>Open <bdi dir="ltr">{value.destination.target_ref}</bdi> in Telegram.</li>
            <li>
              Locate messages around {formatTehranTimestamp(ambiguousOperation?.sent_at ?? value.ambiguous_at ?? "")}.
            </li>
            <li>Compare the persisted operation key and request hash with the intended Telegram payload.</li>
            <li>Choose published only when the remote message IDs can be verified exactly.</li>
          </ol>
        </section>

        <fieldset className="space-y-3" disabled={isSubmitting || successMessage !== null}>
          <legend className="font-medium">Choose the verified outcome</legend>
          <p className="text-sm text-muted-foreground">Choosing an outcome only reveals its confirmation controls.</p>
          <div className="flex flex-wrap gap-2">
            <Button
              aria-describedby={!canConfirmPublished ? publishedBlockedReasonId : undefined}
              aria-pressed={selectedOutcome === "published"}
              disabled={!canConfirmPublished}
              onClick={() => selectOutcome("published")}
              type="button"
              variant={selectedOutcome === "published" ? "default" : "outline"}
            >
              Confirm published
            </Button>
            <Button
              aria-pressed={selectedOutcome === "not_published"}
              onClick={() => selectOutcome("not_published")}
              type="button"
              variant={selectedOutcome === "not_published" ? "default" : "outline"}
            >
              Confirm not published
            </Button>
          </div>
          {!canConfirmPublished ? (
            <p className="text-sm text-amber-800" id={publishedBlockedReasonId}>
              Published confirmation is unavailable until every other operation has succeeded.
            </p>
          ) : null}

          {selectedOutcome === "published" ? (
            <PublishedConfirmation
              allowsMultipleIds={allowsMultipleIds}
              isSubmitting={isSubmitting}
              noteValid={noteValid}
              noteId={`${instanceId}-verification-note`}
              onNoteChange={setOperatorNote}
              onPermalinkChange={setPermalink}
              onRemoteIdsChange={setRemoteIdsInput}
              onSubmit={() => void submitDecision({
                outcome: "published",
                remoteMessageIds: remoteIds.values,
                permalink: permalink.trim() || null,
                operatorNote: operatorNote.trim(),
              })}
              operatorNote={operatorNote}
              permalink={permalink}
              permalinkId={`${instanceId}-permalink`}
              remoteIdsInput={remoteIdsInput}
              remoteIdsId={`${instanceId}-remote-ids`}
              remoteIdsValid={remoteIdsValid}
              syntaxValid={remoteIds.valid}
            />
          ) : null}

          {selectedOutcome === "not_published" ? (
            <NotPublishedConfirmation
              isSubmitting={isSubmitting}
              noteValid={noteValid}
              noteId={`${instanceId}-verification-note`}
              onNoteChange={setOperatorNote}
              onSubmit={() => void submitDecision({
                outcome: "not_published",
                operatorNote: operatorNote.trim(),
              })}
              operatorNote={operatorNote}
            />
          ) : null}
        </fieldset>

        {error ? <DirectionBoundary as="div" className="text-red-700" direction="auto" role="alert">{error}</DirectionBoundary> : null}
        {successMessage ? <div role="status">{successMessage}</div> : null}
      </CardContent>
    </Card>
  )
}

type PublishedConfirmationProps = {
  allowsMultipleIds: boolean
  isSubmitting: boolean
  noteValid: boolean
  noteId: string
  onNoteChange: (value: string) => void
  onPermalinkChange: (value: string) => void
  onRemoteIdsChange: (value: string) => void
  onSubmit: () => void
  operatorNote: string
  permalink: string
  permalinkId: string
  remoteIdsInput: string
  remoteIdsId: string
  remoteIdsValid: boolean
  syntaxValid: boolean
}

function PublishedConfirmation({
  allowsMultipleIds,
  isSubmitting,
  noteValid,
  noteId,
  onNoteChange,
  onPermalinkChange,
  onRemoteIdsChange,
  onSubmit,
  operatorNote,
  permalink,
  permalinkId,
  remoteIdsInput,
  remoteIdsId,
  remoteIdsValid,
  syntaxValid,
}: PublishedConfirmationProps) {
  const showRemoteIdError = remoteIdsInput.trim().length > 0 && !remoteIdsValid
  const errorMessage = syntaxValid
    ? allowsMultipleIds
      ? "Enter at least two remote message IDs for this media group."
      : "Enter exactly one remote message ID for this operation."
    : "Enter positive, unique integers separated by commas."

  return (
    <section aria-label="Confirm published evidence" className="space-y-3 rounded-md border p-3">
      <label className="block space-y-1" htmlFor={remoteIdsId}>
        <span>Verified remote message IDs</span>
        <input
          aria-describedby={showRemoteIdError ? `${remoteIdsId}-error` : undefined}
          aria-invalid={showRemoteIdError}
          className="min-h-11 w-full rounded-md border bg-white px-3"
          dir="ltr"
          id={remoteIdsId}
          inputMode="numeric"
          onChange={(event) => onRemoteIdsChange(event.target.value)}
          placeholder={allowsMultipleIds ? "9201, 9202" : "9201"}
          value={remoteIdsInput}
        />
      </label>
      {showRemoteIdError ? <p className="text-sm text-red-700" id={`${remoteIdsId}-error`} role="alert">{errorMessage}</p> : null}

      <label className="block space-y-1" htmlFor={permalinkId}>
        <span>Telegram permalink (optional)</span>
        <input
          className="min-h-11 w-full rounded-md border bg-white px-3"
          dir="ltr"
          id={permalinkId}
          onChange={(event) => onPermalinkChange(event.target.value)}
          placeholder="https://t.me/channel/9201"
          type="url"
          value={permalink}
        />
      </label>

      <VerificationNote id={noteId} onChange={onNoteChange} value={operatorNote} />
      <Button disabled={isSubmitting || !noteValid || !remoteIdsValid} onClick={onSubmit} type="button">
        {isSubmitting
          ? "Saving confirmation…"
          : allowsMultipleIds
            ? "Confirm published messages"
            : "Confirm published message"}
      </Button>
    </section>
  )
}

type NotPublishedConfirmationProps = {
  isSubmitting: boolean
  noteValid: boolean
  noteId: string
  onNoteChange: (value: string) => void
  onSubmit: () => void
  operatorNote: string
}

function NotPublishedConfirmation({
  isSubmitting,
  noteValid,
  noteId,
  onNoteChange,
  onSubmit,
  operatorNote,
}: NotPublishedConfirmationProps) {
  return (
    <section aria-label="Confirm no remote publication" className="space-y-3 rounded-md border p-3">
      <p className="text-sm">This queues the existing publication job for retry; it does not send during confirmation.</p>
      <VerificationNote id={noteId} onChange={onNoteChange} value={operatorNote} />
      <Button disabled={isSubmitting || !noteValid} onClick={onSubmit} type="button">
        {isSubmitting ? "Queuing retry…" : "Confirm and queue retry"}
      </Button>
    </section>
  )
}

function VerificationNote({ id, onChange, value }: { id: string; onChange: (value: string) => void; value: string }) {
  const invalid = value.length > 0 && value.trim().length < 5
  return (
    <div className="space-y-1">
      <label className="block" htmlFor={id}>Verification note</label>
      <textarea
        aria-describedby={invalid ? `${id}-error` : undefined}
        aria-invalid={invalid}
        className="min-h-24 w-full rounded-md border bg-white px-3 py-2"
        dir="auto"
        id={id}
        maxLength={1000}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      />
      {invalid ? <span className="block text-sm text-red-700" id={`${id}-error`}>Enter at least 5 characters.</span> : null}
    </div>
  )
}

function parseRemoteIds(value: string): { valid: boolean; values: number[] } {
  const tokens = value.split(",").map((token) => token.trim())
  const values = tokens.map(Number)
  const valid = value.trim().length > 0
    && tokens.every((token) => /^\d+$/.test(token))
    && values.every((remoteId) => Number.isSafeInteger(remoteId) && remoteId > 0)
    && new Set(values).size === values.length
  return { valid, values: valid ? values : [] }
}

function resultMessage(result: ReconciliationDecisionResult): string {
  return result.reconciliationStatus === "requeued"
    ? "Publication was queued for a safe retry."
    : "Publication was confirmed."
}

function humanize(value: string): string {
  return value.replaceAll("_", " ")
}
