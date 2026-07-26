"use client"

import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  BrainCircuit,
  KeyRound,
  Pencil,
  Plus,
  RefreshCw,
  Route,
  ShieldCheck,
  Trash2,
} from "lucide-react"
import { useState } from "react"

import { useNotices } from "@/components/providers/notice-provider"
import { Button } from "@/components/ui/button"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import {
  createLLMProvider,
  deleteLLMProvider,
  getLLMProviderDependencies,
  rotateLLMProviderKey,
  setLLMProviderEnabled,
  testLLMProvider,
  updateLLMProvider,
} from "./content-settings-api"
import type { LLMProvider } from "./content-settings-api"
import {
  ActionButton,
  EmptyState,
  Field,
  fieldClass,
  formatDate,
  Metric,
  NumberField,
  ReadinessLabel,
  safeCode,
  SecretDialog,
  SettingsDialog,
  SettingsSection,
  StatusBadge,
} from "./content-settings-primitives"

export function LLMProvidersSection({ providers }: { providers: LLMProvider[] }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [editing, setEditing] = useState<LLMProvider | "new" | null>(null)
  const [rotating, setRotating] = useState<LLMProvider | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.llmProviders }),
    queryClient.invalidateQueries({ queryKey: queryKeys.editorialProviderOptions }),
  ])
  const run = async (provider: LLMProvider, action: "test" | "toggle" | "dependencies" | "delete") => {
    setBusy(`${provider.id}:${action}`)
    try {
      if (action === "test") {
        await testLLMProvider(provider.id)
        pushNotice({ tone: "success", title: "Connection tested", message: `${provider.name} diagnostics refreshed.` })
      } else if (action === "toggle") {
        await setLLMProviderEnabled(provider.id, !provider.enabled)
        pushNotice({ tone: "success", title: provider.enabled ? "Provider disabled" : "Provider enabled", message: provider.name })
      } else {
        const dependencies = await getLLMProviderDependencies(provider.id)
        const summary = `${dependencies.automations} automations, ${dependencies.generation_runs} generation runs, ${dependencies.research_runs} research runs, ${dependencies.active_jobs} active jobs`
        if (action === "dependencies") {
          pushNotice({ tone: dependencies.blocked ? "error" : "success", title: "Provider dependencies", message: summary })
        } else if (!dependencies.blocked && window.confirm(`Delete ${provider.name}? This cannot be undone.`)) {
          await deleteLLMProvider(provider.id)
          pushNotice({ tone: "success", title: "Provider deleted", message: provider.name })
        } else if (dependencies.blocked) {
          pushNotice({ tone: "error", title: "Provider cannot be deleted", message: summary })
        }
      }
      await refresh()
    } catch (cause) {
      pushNotice({ tone: "error", title: "Provider action failed", message: getApiErrorMessage(cause) })
    } finally {
      setBusy(null)
    }
  }
  return (
    <SettingsSection
      id="llm-providers"
      icon={BrainCircuit}
      title="LLM providers"
      description="OpenAI-compatible connections with separate generation and research readiness."
      action={<Button onClick={() => setEditing("new")}><Plus aria-hidden="true" /> Add provider</Button>}
    >
      {providers.length ? <div className="grid gap-3">
        {providers.filter((provider) => provider.protocol !== "fake").map((provider) => (
          <article key={provider.id} className="rounded-xl border bg-background p-4">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-semibold">{provider.name}</h3>
                  <StatusBadge value={provider.enabled ? "enabled" : "disabled"} />
                  <StatusBadge value={provider.health_status} />
                </div>
                <p className="mt-1 truncate text-sm text-muted-foreground">{provider.default_model} · {provider.base_url}</p>
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  <ReadinessLabel label="Generation" ready={provider.generation_ready} value={provider.generation_capability} />
                  <ReadinessLabel label="Research" ready={provider.research_ready} value={provider.research_capability} />
                  <span className="rounded-full bg-muted px-2.5 py-1">{provider.configured ? "API key configured" : "API key missing"}</span>
                  <span className="rounded-full bg-muted px-2.5 py-1">{formatDate(provider.last_checked_at, "Never checked")}</span>
                </div>
                {provider.failure_code ? <p className="mt-2 text-sm text-amber-800 dark:text-amber-300" role="status">{safeCode(provider.failure_code)}</p> : null}
              </div>
              <div className="flex flex-wrap gap-2">
                <ActionButton label="Test" busy={busy === `${provider.id}:test`} onClick={() => void run(provider, "test")} icon={RefreshCw} />
                <ActionButton label="Edit" onClick={() => setEditing(provider)} icon={Pencil} />
                <ActionButton label="Rotate key" onClick={() => setRotating(provider)} icon={KeyRound} />
                <ActionButton label={provider.enabled ? "Disable" : "Enable"} busy={busy === `${provider.id}:toggle`} onClick={() => void run(provider, "toggle")} icon={ShieldCheck} />
                <ActionButton label="Dependencies" busy={busy === `${provider.id}:dependencies`} onClick={() => void run(provider, "dependencies")} icon={Route} />
                <ActionButton label="Delete" busy={busy === `${provider.id}:delete`} onClick={() => void run(provider, "delete")} icon={Trash2} destructive />
              </div>
            </div>
            <details className="mt-3 rounded-lg bg-muted/60 p-3 text-sm">
              <summary className="cursor-pointer font-medium">Advanced diagnostics</summary>
              <dl className="mt-3 grid gap-2 sm:grid-cols-3">
                <Metric label="Timeout" value={`${provider.settings.timeout_seconds}s`} />
                <Metric label="Max input" value={provider.settings.max_input_tokens.toLocaleString()} />
                <Metric label="Max output" value={provider.settings.max_output_tokens.toLocaleString()} />
              </dl>
            </details>
          </article>
        ))}
      </div> : <EmptyState title="No LLM providers" detail="Add an OpenAI-compatible endpoint to begin generation." />}
      {editing ? <ProviderDialog provider={editing === "new" ? null : editing} onClose={() => setEditing(null)} /> : null}
      {rotating ? (
        <SecretDialog
          title={`Rotate key for ${rotating.name}`}
          label="New API key"
          onClose={() => setRotating(null)}
          onSave={async (secret) => {
            await rotateLLMProviderKey(rotating.id, secret)
            await refresh()
            pushNotice({ tone: "success", title: "API key rotated", message: "Secret field was cleared." })
          }}
        />
      ) : null}
    </SettingsSection>
  )
}

function ProviderDialog({ provider, onClose }: { provider: LLMProvider | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const initial = {
    name: provider?.name ?? "",
    baseUrl: provider?.base_url ?? "https://api.openai.com/v1",
    model: provider?.default_model ?? "",
    apiKey: "",
    timeout: provider?.settings.timeout_seconds ?? 60,
    maxInput: provider?.settings.max_input_tokens ?? 60_000,
    maxOutput: provider?.settings.max_output_tokens ?? 12_000,
  }
  const [form, setForm] = useState(initial)
  const [touched, setTouched] = useState(false)
  const dirty = JSON.stringify(form) !== JSON.stringify(initial)
  const urlValid = /^https:\/\/[^?\s#]+$/i.test(form.baseUrl)
  const error = !form.name.trim() ? "Enter a connection name." : !urlValid ? "Use a credential-free HTTPS base URL." : !form.model.trim() ? "Enter a model name." : !provider && !form.apiKey ? "Enter an API key." : null
  const mutation = useMutation({
    mutationFn: () => provider
      ? updateLLMProvider(provider.id, {
        name: form.name.trim(),
        baseUrl: form.baseUrl.trim(),
        defaultModel: form.model.trim(),
        settings: { timeoutSeconds: form.timeout, maxInputTokens: form.maxInput, maxOutputTokens: form.maxOutput },
      })
      : createLLMProvider({
        name: form.name.trim(),
        baseUrl: form.baseUrl.trim(),
        defaultModel: form.model.trim(),
        apiKey: form.apiKey,
        settings: { timeoutSeconds: form.timeout, maxInputTokens: form.maxInput, maxOutputTokens: form.maxOutput },
      }),
    onSuccess: async () => {
      setForm({ ...form, apiKey: "" })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.llmProviders }),
        queryClient.invalidateQueries({ queryKey: queryKeys.editorialProviderOptions }),
      ])
      pushNotice({ tone: "success", title: provider ? "Provider updated" : "Provider created", message: "Connection saved. Test it before enabling." })
      onClose()
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Provider could not be saved", message: getApiErrorMessage(cause) }),
  })
  return (
    <SettingsDialog
      title={provider ? `Edit ${provider.name}` : "Add LLM provider"}
      description="Generic OpenAI-compatible connection. API keys are accepted once and never repopulated."
      dirty={dirty}
      pending={mutation.isPending}
      submitDisabled={Boolean(error)}
      onClose={onClose}
      onReset={() => setForm(initial)}
      onSubmit={() => { setTouched(true); if (!error) mutation.mutate() }}
      submitLabel={provider ? "Save provider" : "Add provider"}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Connection name" required error={touched && !form.name.trim() ? error : null}>
          <input autoFocus className={fieldClass} value={form.name} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        </Field>
        <Field label="Model name" required>
          <input className={fieldClass} value={form.model} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, model: event.target.value })} />
        </Field>
      </div>
      <Field label="Base URL" required error={touched && !urlValid ? "Use a credential-free HTTPS base URL." : null}>
        <input type="url" className={fieldClass} value={form.baseUrl} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, baseUrl: event.target.value })} />
      </Field>
      {!provider ? <Field label="API key" required hint="Write-only. Cleared after save."><input type="password" autoComplete="new-password" className={fieldClass} value={form.apiKey} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, apiKey: event.target.value })} /></Field> : null}
      <details className="rounded-lg border p-3">
        <summary className="cursor-pointer font-medium">Advanced limits</summary>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <NumberField label="Timeout (seconds)" value={form.timeout} min={1} max={300} onChange={(timeout) => setForm({ ...form, timeout })} />
          <NumberField label="Max input tokens" value={form.maxInput} min={1000} max={500000} onChange={(maxInput) => setForm({ ...form, maxInput })} />
          <NumberField label="Max output tokens" value={form.maxOutput} min={500} max={100000} onChange={(maxOutput) => setForm({ ...form, maxOutput })} />
        </div>
      </details>
    </SettingsDialog>
  )
}
