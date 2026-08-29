"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Activity, LoaderCircle, Pencil, Plus, X } from "lucide-react"
import { useState } from "react"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"
import { useNotices } from "@/components/providers/notice-provider"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Button } from "@/components/ui/button"
import {
  activatePromptVersion,
  createPromptTemplate,
  createPromptVersion,
  getPromptVersions,
} from "@/features/automations/telegram-api"
import type { PromptTemplate, PromptVersion } from "@/features/automations/telegram-types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import {
  Field,
  fieldClass,
  formatDate,
  SettingsSection,
  StatusBadge,
} from "./content-settings-primitives"

export function PromptGovernanceSection({ templates }: { templates: PromptTemplate[] }) {
  return (
    <SettingsSection
      id="prompt-governance"
      icon={Activity}
      title="Prompts"
      description="Reusable system prompts. Create one here and select it in any AI workflow step."
    >
      <NewPromptCard />
      <div className="grid gap-3">
        {templates.length === 0 ? (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No saved prompts yet. Create your first reusable system prompt above.</p>
        ) : null}
        {templates.map((template) => (
          <PromptPurpose key={template.id} template={template} />
        ))}
      </div>
    </SettingsSection>
  )
}

function NewPromptCard() {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [systemTemplate, setSystemTemplate] = useState("")
  const [userTemplate, setUserTemplate] = useState("")
  const reset = () => {
    setName("")
    setDescription("")
    setSystemTemplate("")
    setUserTemplate("")
  }
  const refreshPrompts = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["settings", "prompt-templates"] }),
      queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
      queryClient.invalidateQueries({ queryKey: ["settings", "prompt-template-versions"] }),
    ])
  }
  const create = useMutation({
    mutationFn: async () => {
      const template = await createPromptTemplate({
        name: name.trim(),
        description: description.trim() || null,
      })
      return createPromptVersion(template.id, {
        system_template: systemTemplate,
        user_template: userTemplate,
      })
    },
    onSuccess: async (version) => {
      try {
        // ponytail: auto-activate v1 so the prompt is immediately selectable in nodes
        await activatePromptVersion(version.id, "Initial version")
      } catch {
        // activation is optional; the version stays available for manual activation
      }
      await refreshPrompts()
      pushNotice({ tone: "success", title: "Prompt created", message: name.trim() })
      reset()
      setOpen(false)
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Prompt creation failed", message: getApiErrorMessage(cause) }),
  })
  const draftError = validatePromptDraft(systemTemplate, userTemplate)
  if (!open) {
    return (
      <div>
        <Button onClick={() => setOpen(true)} variant="outline"><Plus aria-hidden="true" />New prompt</Button>
      </div>
    )
  }
  return (
    <div className="grid gap-4 rounded-lg border border-border/50 bg-background p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">Create a reusable system prompt</h3>
        <Button aria-label="Close prompt creation" onClick={() => { reset(); setOpen(false) }} size="icon" variant="ghost"><X aria-hidden="true" /></Button>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Name" required><input className={fieldClass} maxLength={120} required value={name} onChange={(event) => setName(event.target.value)} /></Field>
        <Field label="Description" hint="What this prompt is for."><input className={fieldClass} maxLength={500} value={description} onChange={(event) => setDescription(event.target.value)} /></Field>
      </div>
      <Field label="System prompt" hint={`${systemTemplate.length}/20,000 characters · instructions, output schemas, evidence, tone, length`} error={draftError?.field === "system" ? draftError.message : null}>
        <DirectionBoundary as="textarea" language={null} className={fieldClass} maxLength={20_000} onBlur={() => undefined} onChange={(event) => setSystemTemplate(event.target.value)} rows={8} value={systemTemplate} />
      </Field>
      <Field label="Runtime input template" hint={`${userTemplate.length}/40,000 characters · describes what the node passes at runtime`} error={draftError?.field === "user" ? draftError.message : null}>
        <DirectionBoundary as="textarea" language={null} className={`${fieldClass} font-mono text-sm`} maxLength={40_000} onBlur={() => undefined} onChange={(event) => setUserTemplate(event.target.value)} rows={3} value={userTemplate} />
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button disabled={!name.trim() || Boolean(draftError) || create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? <LoaderCircle aria-hidden="true" className="animate-spin" /> : <Plus aria-hidden="true" />}
          {create.isPending ? "Creating" : "Create prompt"}
        </Button>
        <Button disabled={create.isPending} onClick={() => { reset(); setOpen(false) }} variant="outline">Cancel</Button>
      </div>
    </div>
  )
}

function PromptPurpose({ template }: { template: PromptTemplate }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [editing, setEditing] = useState(false)
  const versions = useQuery({
    queryKey: queryKeys.promptVersions(template.id),
    queryFn: () => getPromptVersions(template.id),
  })
  const active = versions.data?.find((version) => version.is_active)
  return (
    <article className="rounded-lg border border-border/50 bg-background p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">{template.name}</h3>
            <StatusBadge value={active ? "active" : versions.data?.length ? "inactive" : "empty"} />
          </div>
          <p className="mt-1 text-sm">{template.description || "Reusable system prompt."}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {active
              ? `Version ${active.version} · ${active.checksum_sha256.slice(0, 12)} · Selectable in workflow steps while active.`
              : `${versions.data?.length ?? 0} immutable versions · no active version.`}
          </p>
        </div>
        <Button variant="outline" onClick={() => setEditing((value) => !value)}>{editing ? <X aria-hidden="true" /> : <Pencil aria-hidden="true" />}{editing ? "Close" : "Manage"}</Button>
      </div>
      {editing ? (
        <PromptAdvancedManager
          template={template}
          versions={versions.data ?? []}
          label={template.name}
          onChanged={async () => {
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ["settings", "prompt-templates"] }),
              queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
            ])
            pushNotice({ tone: "success", title: "Prompt updated", message: template.name })
          }}
        />
      ) : null}
    </article>
  )
}

function PromptAdvancedManager({
  template,
  versions,
  label,
  onChanged,
}: {
  template: PromptTemplate
  versions: PromptVersion[]
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
  const draftError = validatePromptDraft(systemTemplate, userTemplate)
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
      <div className="grid gap-4">
        <Field label="System prompt" hint={`${systemTemplate.length}/20,000 characters`} error={draftError?.field === "system" ? draftError.message : null}><DirectionBoundary as="textarea" language={null} className={fieldClass} rows={6} maxLength={20_000} value={systemTemplate} onBlur={() => undefined} onChange={(event) => setSystemTemplate(event.target.value)} /></Field>
        <Field label="User template" hint={`${userTemplate.length}/40,000 characters`} error={draftError?.field === "user" ? draftError.message : null}><DirectionBoundary as="textarea" language={null} className={`${fieldClass} font-mono text-sm`} rows={4} maxLength={40_000} value={userTemplate} onBlur={() => undefined} onChange={(event) => setUserTemplate(event.target.value)} /></Field>
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

function validatePromptDraft(systemTemplate: string, userTemplate: string) {
  if (!systemTemplate.trim()) return { field: "system" as const, message: "System prompt is required." }
  if (!userTemplate.trim()) return { field: "user" as const, message: "Runtime input template is required." }
  if (systemTemplate.length > 20_000) return { field: "system" as const, message: "System prompt exceeds 20,000 characters." }
  if (userTemplate.length > 40_000) return { field: "user" as const, message: "Runtime input template exceeds 40,000 characters." }
  if (systemTemplate.length + userTemplate.length > 50_000) return { field: "user" as const, message: "Combined templates exceed 50,000 characters." }
  return null
}
