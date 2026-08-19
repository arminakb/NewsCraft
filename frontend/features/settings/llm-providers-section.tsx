"use client"

import { Menu } from "@base-ui/react/menu"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  Ellipsis,
  KeyRound,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Route,
  ShieldCheck,
  Trash2,
} from "lucide-react"
import { useState } from "react"

import { useNotices } from "@/components/providers/notice-provider"
import { useDateTime } from "@/components/providers/date-time-provider"
import { Button, buttonVariants } from "@/components/ui/button"
import { ApiError, getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import { cn } from "@/lib/utils"
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
  EmptyState,
  Field,
  fieldClass,
  formatDate,
  Metric,
  NumberField,
  safeCode,
  SecretDialog,
  SettingsDialog,
  SettingsSection,
  StatusBadge,
} from "./content-settings-primitives"
import { ProviderBrandIcon } from "./provider-brand-icon"

const CREDENTIAL_REPLACEMENT_REQUIRED = "credential_replacement_required"

function capabilityLabel(value: string) {
  return {
    ready: "Healthy",
    unavailable: "Unavailable",
    unknown: "Not tested",
  }[value] ?? safeCode(value)
}

function providerReadiness(provider: LLMProvider) {
  return provider.ready_for_enablement ?? (
    provider.generation_capability === "ready" && Boolean(provider.last_checked_at)
  )
}

function providerReadinessMessage(provider: LLMProvider) {
  return provider.readiness_message ?? (
    providerReadiness(provider) ? "Ready for Generation" : "Run Test before enabling"
  )
}

function providerFailureMessage(code: string) {
  return {
    authentication_failed: "The provider rejected the API credential.",
    model_unavailable: "The configured model could not be used.",
    connection_failed: "The provider could not be reached.",
    provider_blocked:
      "The provider edge rejected the request with HTTP 403 before the model was reached. This is not a credential problem. Retry in a few minutes.",
    output_truncated:
      "The configured model ran out of output tokens before returning a valid response. Raise the output token allowance or choose a model with less reasoning overhead.",
    invalid_configuration: "Provider configuration is invalid.",
    credential_missing: "Provider credential is missing.",
  }[code] ?? `Failure code: ${safeCode(code)}`
}

export function LLMProvidersSection({ providers }: { providers: LLMProvider[] }) {
  const { timezone } = useDateTime()
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [editing, setEditing] = useState<LLMProvider | "new" | null>(null)
  const [rotating, setRotating] = useState<LLMProvider | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const handleMutationError = (cause: unknown, fallbackTitle = "Provider action failed") => {
    const errorCode = providerApiErrorCode(cause)
    if (cause instanceof ApiError && cause.status === 401) {
      pushNotice({
        tone: "error",
        title: "Application sign-in required",
        message: "Your application session is unavailable. Sign in to NewsCraft, then retry.",
      })
      return
    }
    if (cause instanceof ApiError && cause.status === 403) {
      pushNotice({
        tone: "error",
        title: "Insufficient permission",
        message: "Authenticated principal does not have permission for this Settings mutation.",
      })
      return
    }
    const secretFailure = errorCode ? PROVIDER_SECRET_FAILURES[errorCode] : undefined
    if (secretFailure) {
      pushNotice({
        tone: "error",
        title: secretFailure.title,
        message: secretFailure.message,
      })
      return
    }
    if (errorCode === "llm_provider_has_dependencies") {
      pushNotice({
        tone: "error",
        title: "Provider cannot be deleted",
        message: "This provider is still referenced. Review dependencies before deleting it.",
      })
      return
    }
    if (errorCode === "llm_provider_not_ready") {
      pushNotice({
        tone: "error",
        title: "Provider is not ready",
        message: getApiErrorMessage(cause),
      })
      return
    }
    pushNotice({ tone: "error", title: fallbackTitle, message: getApiErrorMessage(cause) })
  }
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.llmProviders }),
    queryClient.invalidateQueries({ queryKey: queryKeys.editorialProviderOptions }),
  ])
  const run = async (provider: LLMProvider, action: "test" | "toggle" | "dependencies" | "delete") => {
    setBusy(`${provider.id}:${action}`)
    try {
      if (action === "test") {
        const tested = await testLLMProvider(provider.id)
        const research = capabilityLabel(tested.research_capability)
        pushNotice({
          tone: "success",
          title: tested.health_status === "degraded" ? "Connection partially healthy" : "Connection healthy",
          message: `${tested.name} authenticated and ${tested.default_model} returned a valid response. Generation Healthy. Research ${research}.`,
        })
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
      handleMutationError(cause, action === "test" ? "Provider test failed" : undefined)
      if (action === "test") {
        await refresh()
      }
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
          <article
            className="min-w-0 max-w-full overflow-hidden rounded-xl border border-border/60 bg-card p-3 shadow-xs"
            data-testid="llm-provider-card"
            key={provider.id}
          >
            <div className="flex min-w-0 items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground">
                <ProviderBrandIcon
                  baseUrl={provider.base_url}
                  className="size-[18px]"
                  name={provider.name}
                  providerType={provider.protocol}
                />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <h3 className="mr-0.5 truncate text-sm font-semibold">{provider.name}</h3>
                  <StatusBadge value={provider.enabled ? "enabled" : "disabled"} />
                  <StatusBadge value={provider.health_status} />
                </div>
                <p
                  className="mt-1 truncate text-xs text-muted-foreground"
                  title={provider.base_url ?? undefined}
                >
                  <span className="font-medium text-foreground">{provider.default_model}</span>
                  <span aria-hidden="true"> · </span>
                  {provider.base_url ?? "Base URL unavailable"}
                </p>
              </div>
              <ProviderOverflowMenu
                busy={busy}
                onDependencies={() => void run(provider, "dependencies")}
                onDelete={() => void run(provider, "delete")}
                onRotate={() => setRotating(provider)}
                provider={provider}
              />
            </div>

            <dl className="mt-2 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border/60 bg-border/60 sm:grid-cols-3 xl:grid-cols-6">
              <ProviderFact
                label="Generation"
                ready={provider.generation_capability === "ready"}
                value={capabilityLabel(provider.generation_capability)}
              />
              <ProviderFact
                label="Research"
                ready={provider.research_capability === "ready"}
                status={Boolean(provider.failure_code)}
                value={capabilityLabel(provider.research_capability)}
              />
              <ProviderFact
                icon={CheckCircle2}
                label="Readiness"
                ready={providerReadiness(provider)}
                value={providerReadinessMessage(provider)}
              />
              <ProviderFact
                label="API key"
                ready={provider.configured && provider.failure_code !== CREDENTIAL_REPLACEMENT_REQUIRED}
                status={provider.failure_code === CREDENTIAL_REPLACEMENT_REQUIRED}
                value={provider.failure_code === CREDENTIAL_REPLACEMENT_REQUIRED
                  ? "Replacement required"
                  : provider.configured ? "Configured" : "Missing"}
              />
              <ProviderFact
                icon={Clock3}
                label="Last checked"
                value={formatDate(provider.last_checked_at, "Never checked", timezone)}
              />
              <ProviderFact
                icon={Clock3}
                label="Latency"
                value={provider.last_test_latency_ms == null ? "Not tested" : `${provider.last_test_latency_ms} ms`}
              />
            </dl>

            {provider.failure_code === CREDENTIAL_REPLACEMENT_REQUIRED ? (
              <div className="mt-2 rounded-lg border border-warning/30 bg-[var(--warning-surface)] p-3 text-foreground" role="alert">
                <p className="flex items-start gap-1.5 text-sm font-medium text-warning">
                  <KeyRound aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  Credential replacement required
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  This provider credential can no longer be decrypted. Re-enter the API key to restore the provider connection.
                </p>
                <Button className="mt-2" onClick={() => setRotating(provider)} size="sm" type="button" variant="outline">
                  Replace API key
                </Button>
              </div>
            ) : null}

            {provider.failure_code && provider.failure_code !== CREDENTIAL_REPLACEMENT_REQUIRED ? (
              <div className="mt-2 rounded-lg border border-destructive/30 bg-[var(--error-surface)] p-3 text-foreground" role="alert">
                <p className="flex items-start gap-1.5 text-sm font-medium text-destructive">
                  <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  Provider test failed
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {provider.failure_message ?? providerFailureMessage(provider.failure_code)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Generation: {capabilityLabel(provider.generation_capability)} · Research: {capabilityLabel(provider.research_capability)}
                </p>
              </div>
            ) : null}

            {provider.generation_capability === "ready" && provider.last_successful_test_at ? (
              <p className="mt-2 flex items-center gap-1.5 text-xs text-success" role="status">
                <CheckCircle2 aria-hidden="true" className="size-3.5 shrink-0" />
                Live test passed for {provider.last_tested_model ?? provider.default_model}.
                {provider.last_test_latency_ms == null ? "" : ` ${provider.last_test_latency_ms} ms.`}
                {` Research ${capabilityLabel(provider.research_capability)}.`}
              </p>
            ) : null}

            <div
              aria-label={`Primary actions for ${provider.name}`}
              className="mt-2 grid grid-cols-3 gap-2 border-t border-border/60 pt-2"
              role="group"
            >
              <ProviderActionButton
                busy={busy === `${provider.id}:test`}
                icon={RefreshCw}
                label="Test"
                onClick={() => void run(provider, "test")}
              />
              <ProviderActionButton
                icon={Pencil}
                label="Edit"
                onClick={() => setEditing(provider)}
              />
              <ProviderActionButton
                busy={busy === `${provider.id}:toggle`}
                className={provider.enabled ? "text-warning hover:text-warning" : undefined}
                icon={ShieldCheck}
                label={provider.enabled ? "Disable" : "Enable"}
                onClick={() => void run(provider, "toggle")}
                variant={provider.enabled ? "ghost" : "secondary"}
              />
            </div>

            <details className="group mt-1 border-t border-border/60 pt-1 text-sm">
              <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1.5 rounded-md px-1 text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring min-[900px]:min-h-0 min-[900px]:py-1.5 [&::-webkit-details-marker]:hidden">
                <ChevronDown
                  aria-hidden="true"
                  className="size-3.5 transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none"
                />
                Advanced diagnostics
              </summary>
              <dl className="mt-1 grid gap-2 rounded-lg bg-muted/45 p-2.5 sm:grid-cols-3">
                <Metric label="Timeout" value={`${provider.settings.timeout_seconds}s`} />
                <Metric label="Max input" value={provider.settings.max_input_tokens.toLocaleString()} />
                <Metric label="Max output" value={provider.settings.max_output_tokens.toLocaleString()} />
              </dl>
            </details>
          </article>
        ))}
      </div> : <EmptyState title="No LLM providers" detail="Add an OpenAI-compatible endpoint to begin generation." />}
      {editing ? (
        <ProviderDialog
          onClose={() => setEditing(null)}
          onError={handleMutationError}
          provider={editing === "new" ? null : editing}
        />
      ) : null}
      {rotating ? (
        <SecretDialog
          submitLabel={rotating.failure_code === CREDENTIAL_REPLACEMENT_REQUIRED ? "Save API key" : "Rotate secret"}
          title={`${rotating.failure_code === CREDENTIAL_REPLACEMENT_REQUIRED ? "Replace API key for" : "Rotate key for"} ${rotating.name}`}
          label="New API key"
          onClose={() => setRotating(null)}
          onError={(cause) => handleMutationError(cause, "Secret rotation failed")}
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

const PROVIDER_SECRET_FAILURES: Record<string, { title: string; message: string }> = {
  secret_store_unavailable: {
    title: "Secret storage unavailable",
    message: "Secure secret storage is unavailable.",
  },
  secret_store_configuration_invalid: {
    title: "Secret storage not configured",
    message: "Secure secret storage is not configured.",
  },
  secret_database_unavailable: {
    title: "Secret database unavailable",
    message: "Secure secret storage database is unavailable.",
  },
  secret_schema_unavailable: {
    title: "Secret schema unavailable",
    message: "Secure secret storage database schema is unavailable.",
  },
  secret_encryption_failed: {
    title: "Credential encryption failed",
    message: "The credential could not be encrypted.",
  },
  secret_decryption_failed: {
    title: "Credential replacement required",
    message: "This provider credential can no longer be decrypted. Re-enter the API key to restore the provider connection.",
  },
  secret_rotation_failed: {
    title: "Credential rotation failed",
    message: "The credential could not be rotated. Existing credential remains unchanged.",
  },
}

function providerApiErrorCode(cause: unknown) {
  if (!(cause instanceof ApiError) || !cause.body) return null
  try {
    const payload = JSON.parse(cause.body) as { detail?: { code?: unknown } }
    return typeof payload.detail?.code === "string" ? payload.detail.code : null
  } catch {
    return null
  }
}

function ProviderFact({
  icon: Icon,
  label,
  ready,
  status,
  value,
}: {
  icon?: typeof BrainCircuit
  label: string
  ready?: boolean
  status?: boolean
  value: string
}) {
  const StateIcon = ready === undefined ? Icon : ready ? CheckCircle2 : CircleAlert
  return (
    <div className="min-w-0 bg-muted/35 px-2.5 py-2">
      <dt className="text-[11px] leading-4 text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "mt-0.5 flex min-w-0 items-center gap-1 text-xs font-medium",
          ready === true && "text-success",
          ready === false && "text-warning",
        )}
      >
        {StateIcon ? <StateIcon aria-hidden="true" className="size-3.5 shrink-0" /> : null}
        <span
          className="min-w-0 flex-1 truncate"
          role={status ? "status" : undefined}
          title={value}
        >
          {ready === undefined ? value : safeCode(value)}
        </span>
      </dd>
    </div>
  )
}

function ProviderActionButton({
  busy,
  className,
  icon: Icon,
  label,
  onClick,
  variant = "outline",
}: {
  busy?: boolean
  className?: string
  icon: typeof BrainCircuit
  label: string
  onClick: () => void
  variant?: "ghost" | "outline" | "secondary"
}) {
  return (
    <Button
      className={cn("min-w-0 px-1.5", className)}
      disabled={busy}
      onClick={onClick}
      size="sm"
      type="button"
      variant={variant}
    >
      {busy
        ? <LoaderCircle aria-hidden="true" className="animate-spin" />
        : <Icon aria-hidden="true" />}
      {label}
    </Button>
  )
}

function ProviderOverflowMenu({
  busy,
  onDelete,
  onDependencies,
  onRotate,
  provider,
}: {
  busy: string | null
  onDelete: () => void
  onDependencies: () => void
  onRotate: () => void
  provider: LLMProvider
}) {
  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label={`More actions for ${provider.name}`}
        className={buttonVariants({ size: "icon-sm", variant: "ghost" })}
      >
        <Ellipsis aria-hidden="true" />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner align="end" className="z-[100] outline-hidden" sideOffset={6}>
          <Menu.Popup className="w-52 origin-[var(--transform-origin)] rounded-lg border border-border/70 bg-popover p-1 text-popover-foreground shadow-md outline-hidden transition-[transform,opacity] duration-150 ease-out data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0 motion-reduce:transition-none">
            <ProviderMenuItem icon={KeyRound} label="Rotate key" onClick={onRotate} sensitive />
            <ProviderMenuItem
              busy={busy === `${provider.id}:dependencies`}
              icon={Route}
              label="Dependencies"
              onClick={onDependencies}
            />
            <Menu.Separator className="mx-1 my-1 h-px bg-border/70" />
            <ProviderMenuItem
              busy={busy === `${provider.id}:delete`}
              destructive
              icon={Trash2}
              label="Delete provider"
              onClick={onDelete}
            />
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  )
}

function ProviderMenuItem({
  busy,
  destructive,
  icon: Icon,
  label,
  onClick,
  sensitive,
}: {
  busy?: boolean
  destructive?: boolean
  icon: typeof BrainCircuit
  label: string
  onClick: () => void
  sensitive?: boolean
}) {
  return (
    <Menu.Item
      className={cn(
        "flex min-h-11 cursor-default items-center gap-2 rounded-md px-2.5 text-sm outline-none select-none data-disabled:opacity-50 data-highlighted:bg-muted min-[900px]:min-h-9",
        sensitive && "text-warning data-highlighted:bg-[var(--warning-surface)]",
        destructive && "text-destructive data-highlighted:bg-[var(--error-surface)]",
      )}
      disabled={busy}
      onClick={onClick}
    >
      {busy
        ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
        : <Icon aria-hidden="true" className="size-4" />}
      {label}
    </Menu.Item>
  )
}

function ProviderDialog({
  provider,
  onClose,
  onError,
}: {
  provider: LLMProvider | null
  onClose: () => void
  onError: (cause: unknown, fallbackTitle?: string) => void
}) {
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
    onError: (cause) => onError(cause, "Provider could not be saved"),
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
