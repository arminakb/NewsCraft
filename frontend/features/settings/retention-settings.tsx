"use client"

import { useEffect, useId, useRef, useState } from "react"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  createRetentionPreview,
  enqueueRetentionRun,
  updateRetentionPolicy,
} from "@/features/operations/api"
import { formatTehranTimestamp } from "@/features/operations/diagnostics-dashboard"
import { RETENTION_CONFIRMATION } from "@/features/operations/types"
import type {
  RetentionCategory,
  RetentionPolicy,
  RetentionPolicyValues,
  RetentionPreview,
} from "@/features/operations/types"
import { ApiError, getApiErrorMessage } from "@/lib/http"

type PolicyKey = keyof RetentionPolicyValues
type PolicyDraft = Record<PolicyKey, string>
type ActiveOperation = "save" | "preview" | "run" | null

const policyFields: Array<{
  description: string
  key: PolicyKey
  label: string
  max: number
  min: number
}> = [
  {
    key: "raw_payload_days",
    label: "Raw payload retention days",
    description: "Source response bodies and transport payloads.",
    min: 7,
    max: 3650,
  },
  {
    key: "completed_job_days",
    label: "Completed job retention days",
    description: "Terminal workflow job records.",
    min: 14,
    max: 3650,
  },
  {
    key: "attempt_metadata_days",
    label: "Attempt metadata retention days",
    description: "Research, generation, and publication attempt metadata.",
    min: 14,
    max: 3650,
  },
  {
    key: "export_artifact_days",
    label: "Export artifact retention days",
    description: "Generated export archives and package files.",
    min: 1,
    max: 3650,
  },
  {
    key: "unreferenced_media_days",
    label: "Unreferenced media retention days",
    description: "Media assets that no durable record still references.",
    min: 7,
    max: 3650,
  },
]

const categoryOrder: RetentionCategory[] = [
  "raw_payload",
  "completed_job",
  "attempt_metadata",
  "export_artifact",
  "unreferenced_media",
]

const categoryNames: Record<RetentionCategory, { singular: string; plural: string }> = {
  raw_payload: { singular: "raw payload", plural: "raw payloads" },
  completed_job: { singular: "completed job", plural: "completed jobs" },
  attempt_metadata: { singular: "attempt metadata record", plural: "attempt metadata records" },
  export_artifact: { singular: "export artifact", plural: "export artifacts" },
  unreferenced_media: { singular: "unreferenced media asset", plural: "unreferenced media assets" },
}

export function RetentionSettings({
  onPolicySaved,
  policy,
  preview = null,
}: {
  onPolicySaved?: (policy: RetentionPolicy) => void | Promise<void>
  policy: RetentionPolicy
  preview?: RetentionPreview | null
}) {
  const instanceId = useId()
  const policySignature = retentionPolicySignature(policy)
  const previousPolicySignature = useRef(policySignature)
  const previewGeneration = useRef(0)
  const [savedPolicy, setSavedPolicy] = useState<RetentionPolicyValues>(() => policyValues(policy))
  const [draft, setDraft] = useState<PolicyDraft>(() => draftFromPolicy(policy))
  const [currentPreview, setCurrentPreview] = useState<RetentionPreview | null>(() =>
    preview && policiesEqual(preview.policy, policy) ? preview : null,
  )
  const [confirmation, setConfirmation] = useState("")
  const [activeOperation, setActiveOperation] = useState<ActiveOperation>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const parsedPolicy = parsePolicyDraft(draft)
  const policyIsSaved = parsedPolicy !== null && policiesEqual(parsedPolicy, savedPolicy)
  const policyCanSave = parsedPolicy !== null && !policyIsSaved
  const busy = activeOperation !== null

  useEffect(() => {
    if (previousPolicySignature.current === policySignature) return
    const incomingPolicy = policyValues(policy)
    const currentDraft = parsePolicyDraft(draft)
    const draftWasClean = currentDraft !== null && policiesEqual(currentDraft, savedPolicy)

    previousPolicySignature.current = policySignature
    setSavedPolicy(incomingPolicy)
    if (draftWasClean) setDraft(draftFromPolicy(incomingPolicy))
    previewGeneration.current += 1
    setCurrentPreview(null)
    setConfirmation("")
    setError(null)
    setSuccess(null)
  }, [policy, policySignature, draft, savedPolicy])

  function invalidatePreview() {
    previewGeneration.current += 1
    setCurrentPreview(null)
    setConfirmation("")
  }

  function changeField(key: PolicyKey, value: string) {
    setDraft((current) => ({ ...current, [key]: value }))
    invalidatePreview()
    setError(null)
    setSuccess(null)
  }

  async function savePolicy() {
    if (!parsedPolicy || !policyCanSave || busy) return
    invalidatePreview()
    setActiveOperation("save")
    setError(null)
    setSuccess(null)
    try {
      const saved = await updateRetentionPolicy(parsedPolicy)
      const values = policyValues(saved)
      setSavedPolicy(values)
      setDraft(draftFromPolicy(values))
      try {
        await onPolicySaved?.(saved)
      } catch {
        // Local server truth remains valid; a later query refresh can repair a cache update failure.
      }
      setSuccess("Retention policy saved. Create a fresh cleanup preview.")
    } catch (caught) {
      setError(getApiErrorMessage(caught, "Retention policy could not be saved"))
    } finally {
      setActiveOperation(null)
    }
  }

  async function createPreview() {
    if (!policyIsSaved || busy) return
    invalidatePreview()
    const requestGeneration = previewGeneration.current
    setActiveOperation("preview")
    setError(null)
    setSuccess(null)
    try {
      const created = await createRetentionPreview()
      if (requestGeneration !== previewGeneration.current || !policiesEqual(created.policy, savedPolicy)) {
        setError("Retention policy changed while previewing. Create a fresh preview.")
        return
      }
      setCurrentPreview(created)
      setSuccess("Cleanup preview is ready. Review every aggregate before confirming.")
    } catch (caught) {
      setError(getApiErrorMessage(caught, "Retention preview could not be created"))
    } finally {
      setActiveOperation(null)
    }
  }

  async function runCleanup() {
    if (!currentPreview || confirmation !== RETENTION_CONFIRMATION || busy) return
    const previewToken = currentPreview.preview_token
    invalidatePreview()
    setActiveOperation("run")
    setError(null)
    setSuccess(null)
    try {
      const accepted = await enqueueRetentionRun(previewToken)
      setSuccess(`Cleanup job ${accepted.job_id} was queued.`)
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status === 409
          ? "Preview expired or changed. Create a fresh preview before cleanup."
          : getApiErrorMessage(caught, "Retention cleanup could not be queued"),
      )
    } finally {
      setActiveOperation(null)
    }
  }

  return (
    <div className="space-y-5">
      <Card className="rounded-md" size="sm">
        <CardHeader>
          <CardTitle>Retention policy</CardTitle>
          <CardDescription>
            Save bounded retention periods before creating a server-authoritative cleanup preview.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <fieldset className="grid gap-3 md:grid-cols-2" disabled={busy}>
            <legend className="sr-only">Retention periods</legend>
            {policyFields.map((field) => {
              const inputId = `${instanceId}-${field.key}`
              const parsed = parseBoundedInteger(draft[field.key], field.min, field.max)
              const invalid = parsed === null
              return (
                <div className="space-y-1" key={field.key}>
                  <label className="block font-medium" htmlFor={inputId}>{field.label}</label>
                  <Input
                    aria-describedby={`${inputId}-description${invalid ? ` ${inputId}-error` : ""}`}
                    aria-invalid={invalid}
                    className="tabular-nums"
                    id={inputId}
                    inputMode="numeric"
                    max={field.max}
                    min={field.min}
                    onChange={(event) => changeField(field.key, event.target.value)}
                    required
                    step={1}
                    type="number"
                    value={draft[field.key]}
                  />
                  <p className="text-xs text-muted-foreground" id={`${inputId}-description`}>
                    {field.description} Range: {field.min}–{field.max} days.
                  </p>
                  {invalid ? (
                    <p className="text-xs text-destructive" id={`${inputId}-error`} role="alert">
                      Enter a whole number from {field.min} to {field.max}.
                    </p>
                  ) : null}
                </div>
              )
            })}
          </fieldset>

          <div className="flex flex-wrap gap-2">
            <Button
              disabled={busy || !policyCanSave}
              onClick={() => void savePolicy()}
              type="button"
            >
              {activeOperation === "save" ? "Saving retention policy…" : "Save retention policy"}
            </Button>
            <Button
              disabled={busy || !policyIsSaved}
              onClick={() => void createPreview()}
              type="button"
              variant="outline"
            >
              {activeOperation === "preview" ? "Creating cleanup preview…" : "Preview cleanup"}
            </Button>
          </div>
          {!policyIsSaved ? (
            <Alert tone="warning" role="status">
              <AlertDescription>Save valid policy changes before creating a cleanup preview.</AlertDescription>
            </Alert>
          ) : null}
        </CardContent>
      </Card>

      {currentPreview ? (
        <RetentionPreviewCard
          confirmation={confirmation}
          disabled={busy}
          instanceId={instanceId}
          onConfirmationChange={setConfirmation}
          onRun={() => void runCleanup()}
          preview={currentPreview}
        />
      ) : (
        <Card className="rounded-md" size="sm">
          <CardContent className="p-5 text-sm text-muted-foreground">
            No executable cleanup preview is loaded. Create a fresh preview after every policy change or run.
          </CardContent>
        </Card>
      )}

      {activeOperation ? (
        <p aria-label={operationLabel(activeOperation)} role="status">{operationLabel(activeOperation)}…</p>
      ) : null}
      {error ? (
        <Alert tone="error" role="alert" dir="auto">
          <div>
            <AlertTitle>Retention action failed</AlertTitle>
            <AlertDescription>
              <DirectionBoundary direction="auto">{error}</DirectionBoundary>
            </AlertDescription>
          </div>
        </Alert>
      ) : null}
      {success ? (
        <Alert tone="success" role="status">
          <AlertDescription>{success}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  )
}

function RetentionPreviewCard({
  confirmation,
  disabled,
  instanceId,
  onConfirmationChange,
  onRun,
  preview,
}: {
  confirmation: string
  disabled: boolean
  instanceId: string
  onConfirmationChange: (value: string) => void
  onRun: () => void
  preview: RetentionPreview
}) {
  const summaries = categoryOrder.flatMap((category) => {
    const summary = preview.counts[category]
    return summary ? [{ category, summary }] : []
  })
  const confirmationId = `${instanceId}-cleanup-confirmation`

  return (
    <Card aria-label="Executable cleanup preview" className="rounded-md border-warning/40" role="region" size="sm">
      <CardHeader>
        <CardTitle>Cleanup preview</CardTitle>
        <CardDescription>
          Previewed {formatTehranTimestamp(preview.previewed_at)} · expires {formatTehranTimestamp(preview.preview_expires_at)}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Alert tone="warning" role="note">
          <div>
            <AlertTitle>Destructive cleanup</AlertTitle>
            <AlertDescription>
              Running this preview permanently removes the candidate records summarized below. Review counts and expiry before confirming.
            </AlertDescription>
          </div>
        </Alert>
        {summaries.length ? (
          <ul aria-label="Cleanup candidate aggregates" className="divide-y rounded-md border">
            {summaries.map(({ category, summary }) => (
              <li className="px-3 py-2" key={category}>
                {formatSummary(category, summary.count, summary.byte_length ?? null)}
              </li>
            ))}
          </ul>
        ) : (
          <p>No cleanup candidate aggregates were returned.</p>
        )}

        <div className="space-y-1">
          <label className="block font-medium" htmlFor={confirmationId}>
            Type {RETENTION_CONFIRMATION}
          </label>
          <Input
            autoComplete="off"
            disabled={disabled}
            id={confirmationId}
            onChange={(event) => onConfirmationChange(event.target.value)}
            spellCheck={false}
            value={confirmation}
          />
          <p className="text-xs text-muted-foreground">
            The phrase must match exactly. The browser submits only the opaque preview token.
          </p>
        </div>
        <Button
          disabled={disabled || confirmation !== RETENTION_CONFIRMATION}
          onClick={onRun}
          type="button"
          variant="destructive"
        >
          Run cleanup
        </Button>
      </CardContent>
    </Card>
  )
}

function draftFromPolicy(policy: RetentionPolicyValues): PolicyDraft {
  return {
    raw_payload_days: String(policy.raw_payload_days),
    completed_job_days: String(policy.completed_job_days),
    attempt_metadata_days: String(policy.attempt_metadata_days),
    export_artifact_days: String(policy.export_artifact_days),
    unreferenced_media_days: String(policy.unreferenced_media_days),
  }
}

function policyValues(policy: RetentionPolicyValues): RetentionPolicyValues {
  return {
    raw_payload_days: policy.raw_payload_days,
    completed_job_days: policy.completed_job_days,
    attempt_metadata_days: policy.attempt_metadata_days,
    export_artifact_days: policy.export_artifact_days,
    unreferenced_media_days: policy.unreferenced_media_days,
  }
}

function retentionPolicySignature(policy: RetentionPolicy): string {
  return [
    policy.updated_at,
    policy.raw_payload_days,
    policy.completed_job_days,
    policy.attempt_metadata_days,
    policy.export_artifact_days,
    policy.unreferenced_media_days,
  ].join(":")
}

function parsePolicyDraft(draft: PolicyDraft): RetentionPolicyValues | null {
  const rawPayloadDays = parseBoundedInteger(draft.raw_payload_days, 7, 3650)
  const completedJobDays = parseBoundedInteger(draft.completed_job_days, 14, 3650)
  const attemptMetadataDays = parseBoundedInteger(draft.attempt_metadata_days, 14, 3650)
  const exportArtifactDays = parseBoundedInteger(draft.export_artifact_days, 1, 3650)
  const unreferencedMediaDays = parseBoundedInteger(draft.unreferenced_media_days, 7, 3650)
  if (
    rawPayloadDays === null
    || completedJobDays === null
    || attemptMetadataDays === null
    || exportArtifactDays === null
    || unreferencedMediaDays === null
  ) return null
  return {
    raw_payload_days: rawPayloadDays,
    completed_job_days: completedJobDays,
    attempt_metadata_days: attemptMetadataDays,
    export_artifact_days: exportArtifactDays,
    unreferenced_media_days: unreferencedMediaDays,
  }
}

function parseBoundedInteger(value: string, min: number, max: number): number | null {
  if (!/^\d+$/.test(value)) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed >= min && parsed <= max ? parsed : null
}

function policiesEqual(left: RetentionPolicyValues, right: RetentionPolicyValues): boolean {
  return policyFields.every((field) => left[field.key] === right[field.key])
}

function formatSummary(category: RetentionCategory, count: number, byteLength: number | null): string {
  const names = categoryNames[category]
  const label = count === 1 ? names.singular : names.plural
  return `${count.toLocaleString("en-US")} ${label} · ${formatBytes(byteLength)}`
}

function formatBytes(byteLength: number | null): string {
  if (byteLength === null) return "size unknown"
  if (byteLength < 1024) return `${byteLength.toLocaleString("en-US")} B`
  const units = ["KB", "MB", "GB", "TB"]
  let value = byteLength / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)} ${units[unitIndex]}`
}

function operationLabel(operation: Exclude<ActiveOperation, null>): string {
  if (operation === "save") return "Saving retention policy"
  if (operation === "preview") return "Creating cleanup preview"
  return "Starting retention cleanup"
}
