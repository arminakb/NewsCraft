"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Activity, LoaderCircle, Pencil, Plus, X } from "lucide-react"
import { useState } from "react"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"
import { useNotices } from "@/components/providers/notice-provider"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  activatePromptVersion,
  createPromptVersion,
  getPromptVersions,
} from "@/features/automations/telegram-api"
import type { PromptVersion } from "@/features/automations/telegram-types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import {
  Field,
  fieldClass,
  formatDate,
  SettingsSection,
  StatusBadge,
} from "./content-settings-primitives"

const promptPurposes = [
  {
    purpose: "canonical_story",
    label: "Canonical Story",
    pipeline: "Turns persisted evidence into the grounded canonical story used by every platform pack.",
    requiredVariables: ["story_title", "evidence_json"],
  },
  {
    purpose: "telegram_rewrite",
    label: "Telegram Automation Rewrite",
    pipeline: "Rewrites captured Telegram source material for Automation routes.",
    requiredVariables: ["source_text", "source_url", "source_channel", "language", "direction", "attribution_policy", "custom_footer"],
  },
  {
    purpose: "telegram_pack",
    label: "Telegram Pack",
    pipeline: "Builds operator-reviewed Telegram output from a locked canonical story.",
    requiredVariables: ["canonical_story_json", "brand_profile_json", "direction", "instruction"],
  },
  {
    purpose: "instagram_pack",
    label: "Instagram Pack",
    pipeline: "Builds the manual Instagram publishing package from canonical story evidence.",
    requiredVariables: ["canonical_story_json", "brand_profile_json", "platform_limits_json", "source_media_json", "instruction"],
  },
  {
    purpose: "x_pack",
    label: "X Pack",
    pipeline: "Builds the manual X publishing package from canonical story evidence.",
    requiredVariables: ["canonical_story_json", "brand_profile_json", "platform_limits_json", "source_media_json", "instruction"],
  },
  {
    purpose: "blog_pack",
    label: "Blog Pack",
    pipeline: "Builds the manual blog publishing package from canonical story evidence.",
    requiredVariables: ["canonical_story_json", "brand_profile_json", "platform_limits_json", "source_media_json", "instruction"],
  },
] as const

export function PromptGovernanceSection({ templates }: { templates: Array<{ id: string; purposeKey: string; name: string; description: string | null }> }) {
  return (
    <SettingsSection
      id="prompt-governance"
      icon={Activity}
      title="Prompt governance"
      description="Purpose, active version, status, impact, and immutable history."
    >
      <div className="grid gap-3">
        {promptPurposes.map((meta) => (
          <PromptPurpose key={meta.purpose} meta={meta} template={templates.find((item) => item.purposeKey === meta.purpose)} />
        ))}
      </div>
    </SettingsSection>
  )
}

function PromptPurpose({
  meta,
  template,
}: {
  meta: (typeof promptPurposes)[number]
  template?: { id: string; purposeKey: string; name: string; description: string | null }
}) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [editing, setEditing] = useState(false)
  const versions = useQuery({
    queryKey: template ? queryKeys.promptVersions(template.id) : ["settings", "prompt-purpose", meta.purpose, "missing"],
    queryFn: () => getPromptVersions(template!.id),
    enabled: Boolean(template),
  })
  const active = versions.data?.find((version) => version.is_active)
  return (
    <article className="rounded-lg border border-border/50 bg-background p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">{meta.label}</h3>
            <StatusBadge value={!template ? "not configured" : active ? "active" : "inactive"} />
          </div>
          <p className="mt-1 text-sm">{meta.pipeline}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {!template ? "No template configured." : active ? `Version ${active.version} · ${active.checksum_sha256.slice(0, 12)} · Follow-active jobs resolve this version; pinned jobs retain their selection.` : `${versions.data?.length ?? 0} immutable versions · no active version.`}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5" aria-label={`${meta.label} required variables`}>
            {meta.requiredVariables.map((variable) => <Badge key={variable} variant="secondary">{`{${variable}}`}</Badge>)}
          </div>
        </div>
        {template ? <Button variant="outline" onClick={() => setEditing((value) => !value)}>{editing ? <X aria-hidden="true" /> : <Pencil aria-hidden="true" />}{editing ? "Close" : "Manage"}</Button> : null}
      </div>
      {editing && template ? (
        <PromptAdvancedManager
          template={template}
          versions={versions.data ?? []}
          requiredVariables={[...meta.requiredVariables]}
          label={meta.label}
          onChanged={async () => {
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ["settings", "prompt-templates"] }),
              queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
            ])
            pushNotice({ tone: "success", title: "Prompt governance updated", message: meta.label })
          }}
        />
      ) : null}
    </article>
  )
}

function PromptAdvancedManager({
  template,
  versions,
  requiredVariables,
  label,
  onChanged,
}: {
  template: { id: string; purposeKey: string }
  versions: PromptVersion[]
  requiredVariables: string[]
  label: string
  onChanged: () => Promise<void>
}) {
  const { timezone } = useDateTime()
  const { pushNotice } = useNotices()
  const active = versions.find((version) => version.is_active)
  const [systemTemplate, setSystemTemplate] = useState(active?.system_template ?? "")
  const [userTemplate, setUserTemplate] = useState(active?.user_template ?? "")
  const [activationTarget, setActivationTarget] = useState<string | null>(null)
  const [activationReason, setActivationReason] = useState("")
  const [confirmed, setConfirmed] = useState(false)
  const draftError = validatePromptDraft(systemTemplate, userTemplate, requiredVariables)
  const changedFromActive = Boolean(active) && (active!.system_template !== systemTemplate || active!.user_template !== userTemplate)
  const target = versions.find((version) => version.id === activationTarget)
  const create = useMutation({
    mutationFn: () => createPromptVersion(template.id, { system_template: systemTemplate, user_template: userTemplate }),
    onSuccess: async (created) => {
      setActivationTarget(created.id)
      setConfirmed(false)
      setActivationReason("")
      await onChanged()
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Prompt version failed", message: getApiErrorMessage(cause) }),
  })
  const activate = useMutation({
    mutationFn: () => activatePromptVersion(activationTarget!, activationReason.trim()),
    onSuccess: async (version) => {
      setConfirmed(false)
      setActivationTarget(null)
      setActivationReason("")
      setSystemTemplate(version.system_template)
      setUserTemplate(version.user_template)
      await onChanged()
      pushNotice({ tone: "success", title: `${label} activated`, message: `Version ${version.version} is active for future follow-active jobs.` })
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Prompt activation failed", message: getApiErrorMessage(cause) }),
  })
  const dirty = changedFromActive || Boolean(activationReason) || confirmed
  useDirtyNavigation(dirty, "Discard unsaved prompt changes?")
  const resetDraft = () => {
    setSystemTemplate(active?.system_template ?? "")
    setUserTemplate(active?.user_template ?? "")
  }
  return (
    <div className="mt-4 space-y-4 border-t pt-4">
      <details className="rounded-lg bg-muted/50 p-3">
        <summary className="cursor-pointer font-medium">Advanced: raw templates and immutable history</summary>
        <div className="mt-4 grid gap-4">
          <Field label="System template" hint={`${systemTemplate.length}/20,000 characters`} error={draftError?.field === "system" ? draftError.message : null}><DirectionBoundary as="textarea" language={null} className={fieldClass} rows={4} maxLength={20_000} value={systemTemplate} onBlur={() => undefined} onChange={(event) => setSystemTemplate(event.target.value)} /></Field>
          <Field label="User template" hint={`${userTemplate.length}/40,000 characters`} error={draftError?.field === "user" ? draftError.message : null}><DirectionBoundary as="textarea" language={null} className={`${fieldClass} font-mono text-sm`} rows={6} maxLength={40_000} value={userTemplate} onBlur={() => undefined} onChange={(event) => setUserTemplate(event.target.value)} /></Field>
          {changedFromActive && active ? <PromptDiff before={active} systemTemplate={systemTemplate} userTemplate={userTemplate} /> : null}
          <div className="flex flex-wrap gap-2">
            <Button disabled={!changedFromActive || Boolean(draftError) || create.isPending} onClick={() => create.mutate()}>{create.isPending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Plus aria-hidden="true" />}Create immutable version</Button>
            <Button variant="outline" disabled={!dirty || create.isPending} onClick={resetDraft}>Reset</Button>
          </div>
          {target && !target.is_active ? (
            <div className="space-y-3 rounded-lg border border-warning/30 bg-[var(--warning-surface)] p-3 text-foreground">
              <div><strong>Activate version {target.version}?</strong><p className="text-sm">Follow-active routes and new editorial jobs will resolve this version. Pinned routes and existing revisions remain unchanged.</p></div>
              {active ? <PromptDiff before={active} systemTemplate={target.system_template} userTemplate={target.user_template} /> : null}
              <Field label="Activation reason" required error={activationReason.length > 0 && activationReason.trim().length < 3 ? "Enter at least 3 characters." : null}>
                <input className={fieldClass} maxLength={500} value={activationReason} onChange={(event) => setActivationReason(event.target.value)} />
              </Field>
              <label className="flex min-h-11 items-center gap-2 rounded-lg border bg-background px-3 text-sm">
                <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
                Confirm activation changes prompt selection for future jobs
              </label>
              <div className="flex flex-wrap gap-2">
                <Button disabled={!confirmed || activationReason.trim().length < 3 || activate.isPending} onClick={() => activate.mutate()}>{activate.isPending ? "Activating" : `Activate version ${target.version}`}</Button>
                <Button variant="outline" disabled={activate.isPending} onClick={() => { setActivationTarget(null); setConfirmed(false); setActivationReason("") }}>Cancel</Button>
              </div>
            </div>
          ) : null}
          <ol className="space-y-2" aria-label={`${template.purposeKey} immutable history`}>
            {versions.map((version) => (
              <li key={version.id} className="rounded-lg border bg-background p-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <strong>Version {version.version}</strong>
                    <div className="break-all text-xs text-muted-foreground">{version.checksum_sha256} · {version.is_active ? "Active" : "Inactive"}</div>
                    {version.activation_reason ? (
                      <div className="mt-1 text-xs text-muted-foreground">
                        Activated {formatDate(version.activated_at, "Unknown", timezone)} by {version.activated_by_type} {version.activated_by_id} · {version.activation_reason}
                      </div>
                    ) : null}
                  </div>
                  <Button variant="outline" disabled={version.is_active || activate.isPending} onClick={() => { setActivationTarget(version.id); setConfirmed(false); setActivationReason("") }}>Review activation</Button>
                </div>
                <details className="mt-2"><summary className="cursor-pointer text-sm">Inspect raw template</summary><DirectionBoundary as="pre" language={null} className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">{version.system_template}{"\n\n"}{version.user_template}</DirectionBoundary></details>
              </li>
            ))}
          </ol>
        </div>
      </details>
    </div>
  )
}

function PromptDiff({ before, systemTemplate, userTemplate }: { before: PromptVersion; systemTemplate: string; userTemplate: string }) {
  return (
    <div className="grid gap-2 rounded-lg border bg-background p-3 text-xs md:grid-cols-2" aria-label={`Diff from version ${before.version}`}>
      <div><strong>Current version {before.version}</strong><pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--error-surface)] p-2 text-foreground">{before.system_template}{"\n\n"}{before.user_template}</pre></div>
      <div><strong>Proposed version</strong><pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--success-surface)] p-2 text-foreground">{systemTemplate}{"\n\n"}{userTemplate}</pre></div>
    </div>
  )
}

function validatePromptDraft(systemTemplate: string, userTemplate: string, requiredVariables: string[]) {
  if (!systemTemplate.trim()) return { field: "system" as const, message: "System template is required." }
  if (!userTemplate.trim()) return { field: "user" as const, message: "User template is required." }
  if (systemTemplate.length > 20_000) return { field: "system" as const, message: "System template exceeds 20,000 characters." }
  if (userTemplate.length > 40_000) return { field: "user" as const, message: "User template exceeds 40,000 characters." }
  if (systemTemplate.length + userTemplate.length > 50_000) return { field: "user" as const, message: "Combined templates exceed 50,000 characters." }
  const normalized = `${systemTemplate}\n${userTemplate}`.replaceAll("{{", "").replaceAll("}}", "")
  const variables = [...normalized.matchAll(/\{([^{}]+)\}/g)].map((match) => match[1])
  const unsupported = variables.filter((variable) => !requiredVariables.includes(variable))
  if (unsupported.length) return { field: "user" as const, message: `Unsupported variables: ${unsupported.join(", ")}.` }
  const missing = requiredVariables.filter((variable) => !variables.includes(variable))
  if (missing.length) return { field: "user" as const, message: `Missing required variables: ${missing.join(", ")}.` }
  return null
}
