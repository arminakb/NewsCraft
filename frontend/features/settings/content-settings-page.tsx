"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Activity,
  Bot,
  BrainCircuit,
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  ExternalLink,
  KeyRound,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  RotateCw,
  Route,
  ShieldCheck,
  Trash2,
  UserRound,
  X,
} from "lucide-react"
import { cloneElement, isValidElement, useId, useRef, useState } from "react"

import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import { useNotices } from "@/components/providers/notice-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"
import { useEditorialModal } from "@/components/editorial/use-editorial-modal"
import {
  activatePromptVersion,
  createBrandProfile,
  createPromptVersion,
  getBrandProfiles,
  getPromptTemplates,
  getPromptVersions,
  updateBrandProfile,
} from "@/features/automations/telegram-api"
import type { BrandProfile, PromptVersion } from "@/features/automations/telegram-types"
import {
  createCodexPairingSession,
  createLLMProvider,
  createTelegramDestination,
  createTelegramProxy,
  deleteLLMProvider,
  deleteTelegramDestination,
  deleteTelegramProxy,
  getCodexActivity,
  getCodexConnections,
  getLLMProviderDependencies,
  getLLMProviders,
  getTelegramDestinationDependencies,
  getTelegramDestinations,
  getTelegramProxies,
  getTelegramProxyDependencies,
  recheckTelegramDestination,
  recheckTelegramProxy,
  revokeCodexConnection,
  rotateCodexConnection,
  rotateLLMProviderKey,
  rotateTelegramToken,
  rotateTelegramProxyCredentials,
  setLLMProviderEnabled,
  setTelegramDestinationEnabled,
  setTelegramProxyEnabled,
  testLLMProvider,
  updateLLMProvider,
  updateTelegramDestination,
  updateTelegramProxy,
} from "./content-settings-api"
import type {
  CodexConnection,
  LLMProvider,
  TelegramDestination,
  TelegramProxy,
} from "./content-settings-api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

const fieldClass =
  "min-h-11 w-full rounded-lg border bg-background px-3 py-2 text-base outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:bg-muted disabled:text-muted-foreground"
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
const readScopes = [
  "settings:read",
  "providers:read",
  "destinations:read",
  "prompts:read",
  "automations:read",
  "jobs:read",
]

export function ContentSettingsPage() {
  const brands = useQuery({ queryKey: queryKeys.brandProfiles, queryFn: getBrandProfiles })
  const templates = useQuery({ queryKey: queryKeys.promptTemplates, queryFn: getPromptTemplates })
  const providers = useQuery({ queryKey: queryKeys.llmProviders, queryFn: getLLMProviders })
  const destinations = useQuery({
    queryKey: queryKeys.telegramDestinations,
    queryFn: getTelegramDestinations,
    refetchInterval: (query) => query.state.data?.some((item) =>
      [item.healthStatus, item.proxyHealthStatus, item.telegramHealthStatus].includes("checking")
    ) ? 3_000 : false,
  })
  const proxies = useQuery({
    queryKey: queryKeys.telegramProxies,
    queryFn: getTelegramProxies,
    refetchInterval: (query) => query.state.data?.some((item) => item.reachabilityStatus === "checking") ? 3_000 : false,
  })
  const connections = useQuery({
    queryKey: queryKeys.codexConnections,
    queryFn: getCodexConnections,
    refetchInterval: (query) => query.state.error ? false : 20_000,
  })
  const activity = useQuery({
    queryKey: queryKeys.codexActivity,
    queryFn: () => getCodexActivity(),
    refetchInterval: (query) => query.state.error ? false : 20_000,
  })
  const requiredQueries = [brands, templates, providers, destinations, proxies]
  const codexError = connections.error ?? activity.error
  const codexPending = connections.isPending || activity.isPending
  const codexRefreshing = connections.isFetching || activity.isFetching

  if (requiredQueries.some((query) => query.isPending)) return <SettingsSkeleton />
  const failed = requiredQueries.filter((query) => query.isError)
  if (failed.length) {
    return (
      <section className="space-y-4 p-4 md:p-6" aria-labelledby="content-settings-error">
        <h1 id="content-settings-error" className="text-xl font-semibold">Content settings unavailable</h1>
        <p role="alert" dir="auto" className="text-sm text-red-700 dark:text-red-300">
          {getApiErrorMessage(failed[0].error, "Content settings could not be loaded.")}
        </p>
        <Button variant="outline" onClick={() => void Promise.all(requiredQueries.map((query) => query.refetch()))}>
          <RefreshCw aria-hidden="true" /> Retry settings
        </Button>
      </section>
    )
  }

  const enabledProviders = providers.data?.filter((item) => item.enabled) ?? []
  const healthyDestinations = destinations.data?.filter((item) => item.healthStatus === "healthy") ?? []
  const greenConnections = connections.data?.filter((item) => item.status === "green") ?? []
  const activePrompts = templates.data?.length ?? 0
  const codexSummary = codexError
    ? "Authentication required"
    : codexPending
      ? "Checking"
      : greenConnections.length
        ? `${greenConnections.length} connected`
        : "No live heartbeat"

  return (
    <section className="min-w-0 space-y-6 p-4 md:p-6" aria-labelledby="content-settings-heading">
      <header className="max-w-3xl">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Configuration</p>
        <h1 id="content-settings-heading" className="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">
          Content settings
        </h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Manage editorial behavior, model connections, Codex access, publishing destinations, and prompt history.
          Secrets stay write-only.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Content readiness summary">
        <SummaryCard icon={BrainCircuit} label="LLM providers" value={`${enabledProviders.length} enabled`} ready={enabledProviders.some((item) => item.generationReady)} />
        <SummaryCard icon={Bot} label="Telegram" value={`${healthyDestinations.length}/${destinations.data?.length ?? 0} healthy`} ready={healthyDestinations.length > 0} />
        <SummaryCard icon={ShieldCheck} label="Codex" value={codexSummary} ready={!codexError && greenConnections.length > 0} />
        <SummaryCard icon={Activity} label="Prompt purposes" value={`${activePrompts} configured`} ready={activePrompts > 0} />
      </div>

      <nav className="sticky top-0 z-20 -mx-4 flex gap-1 overflow-x-auto border-y bg-background/95 px-4 py-2 backdrop-blur md:-mx-6 md:px-6" aria-label="Content settings sections">
        {[
          ["editorial-profiles", "Editorial profiles"],
          ["llm-providers", "LLM providers"],
          ["codex-connection", "Codex"],
          ["telegram-destinations", "Telegram"],
          ["prompt-governance", "Prompts"],
        ].map(([href, label]) => (
          <a key={href} className="min-h-10 shrink-0 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring" href={`#${href}`}>
            {label}
          </a>
        ))}
      </nav>

      <EditorialProfilesSection profiles={brands.data ?? []} />
      <LLMProvidersSection providers={providers.data ?? []} />
      <CodexSection
        connections={connections.data ?? []}
        activity={activity.data ?? []}
        error={codexError ? getApiErrorMessage(codexError, "Codex settings could not be loaded.") : null}
        loading={codexPending}
        refreshing={codexRefreshing}
        onRetry={() => void Promise.all([connections.refetch(), activity.refetch()])}
      />
      <TelegramSection destinations={destinations.data ?? []} proxies={proxies.data ?? []} />
      <PromptGovernanceSection templates={templates.data ?? []} />
    </section>
  )
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  ready,
}: {
  icon: typeof Activity
  label: string
  value: string
  ready: boolean
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border bg-card p-4 shadow-sm">
      <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-muted text-primary">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        <div className="truncate font-semibold">{value}</div>
      </div>
      <span className={`ml-auto size-2.5 shrink-0 rounded-full ${ready ? "bg-emerald-600" : "bg-slate-400"}`} aria-label={ready ? "Ready" : "Needs attention"} />
    </div>
  )
}

function EditorialProfilesSection({ profiles }: { profiles: BrandProfile[] }) {
  const [editing, setEditing] = useState<BrandProfile | "new" | null>(null)
  const defaultProfile = profiles.find((profile) => profile.isDefault)
  return (
    <SettingsSection
      id="editorial-profiles"
      icon={UserRound}
      title="Editorial profiles"
      description="Reusable language, tone, attribution, and platform defaults."
      action={<Button onClick={() => setEditing("new")}><Plus aria-hidden="true" /> New profile</Button>}
    >
      <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm leading-6 text-blue-950 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-100" role="note">
        <strong>{defaultProfile ? `${defaultProfile.name} is the default.` : "No default profile is selected."}</strong>{" "}
        Requests that omit a profile use this default. Profile edits can affect queued jobs that have not executed;
        existing revisions remain unchanged.
      </div>
      {profiles.length ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {profiles.map((profile) => (
            <article key={profile.id} className="rounded-xl border bg-background p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold">{profile.name}</h3>
                    {profile.isDefault ? <Badge variant="secondary">Default</Badge> : null}
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">{profile.outputLanguage.toUpperCase()} · {profile.tone}</p>
                </div>
                <Button variant="outline" size="sm" onClick={() => setEditing(profile)}>
                  <Pencil aria-hidden="true" /> Edit
                </Button>
              </div>
              <details className="mt-3 rounded-lg bg-muted/60 p-3 text-sm">
                <summary className="cursor-pointer font-medium">Advanced profile details</summary>
                <dl className="mt-3 grid gap-2 text-muted-foreground">
                  <div><dt className="font-medium text-foreground">Editorial rules</dt><dd>{profile.editorialRules.length ? profile.editorialRules.join(" · ") : "None"}</dd></div>
                  <div><dt className="font-medium text-foreground">Attribution policy</dt><dd className="break-words font-mono text-xs">{compactJson(profile.attributionRules)}</dd></div>
                  <div><dt className="font-medium text-foreground">Default hashtags</dt><dd>{profile.defaultHashtags.length ? profile.defaultHashtags.join(" ") : "None"}</dd></div>
                  <div><dt className="font-medium text-foreground">Per-platform preferences</dt><dd className="break-words font-mono text-xs">{compactJson(profile.platformPreferences)}</dd></div>
                </dl>
              </details>
            </article>
          ))}
        </div>
      ) : <EmptyState title="No editorial profiles" detail="Create one to set output language and editorial voice." />}
      {editing ? <EditorialProfileDialog profile={editing === "new" ? null : editing} onClose={() => setEditing(null)} /> : null}
    </SettingsSection>
  )
}

function EditorialProfileDialog({ profile, onClose }: { profile: BrandProfile | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const initial = {
    name: profile?.name ?? "",
    outputLanguage: profile?.outputLanguage ?? "fa",
    tone: profile?.tone ?? "neutral",
    editorialRules: profile?.editorialRules.join("\n") ?? "",
    attributionRules: formatJsonObject(profile?.attributionRules ?? {}),
    defaultHashtags: profile?.defaultHashtags.join(" ") ?? "",
    platformPreferences: formatJsonObject(profile?.platformPreferences ?? {}),
    isDefault: profile?.isDefault ?? false,
  }
  const [form, setForm] = useState(initial)
  const [touched, setTouched] = useState(false)
  const [jsonTouched, setJsonTouched] = useState({ attribution: false, platforms: false })
  const dirty = JSON.stringify(form) !== JSON.stringify(initial)
  const attribution = parseJsonObject(form.attributionRules)
  const platformPreferences = parseJsonObject(form.platformPreferences)
  const error = !form.name.trim()
    ? "Enter a profile name."
    : !form.outputLanguage.trim()
      ? "Enter an output language."
      : !form.tone.trim()
        ? "Enter an editorial tone."
        : attribution.error ?? platformPreferences.error
  const mutation = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name.trim(),
        outputLanguage: form.outputLanguage.trim(),
        tone: form.tone.trim(),
        editorialRules: lines(form.editorialRules),
        attributionRules: attribution.value,
        defaultHashtags: words(form.defaultHashtags),
        platformPreferences: platformPreferences.value,
        isDefault: form.isDefault,
      }
      return profile ? updateBrandProfile(profile.id, body) : createBrandProfile(body)
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.brandProfiles }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
        queryClient.invalidateQueries({ queryKey: queryKeys.editorialBrandOptions }),
      ])
      pushNotice({
        tone: "success",
        title: profile ? "Profile updated" : "Profile created",
        message: "Future jobs will use the saved profile. Existing revisions were not changed.",
      })
      onClose()
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Profile could not be saved", message: getApiErrorMessage(cause) }),
  })
  return (
    <SettingsDialog
      title={profile ? `Edit ${profile.name}` : "New editorial profile"}
      description="Primary editorial defaults stay visible; detailed rules remain optional."
      dirty={dirty}
      pending={mutation.isPending}
      submitDisabled={Boolean(error)}
      onClose={onClose}
      onReset={() => {
        setForm(initial)
        setTouched(false)
        setJsonTouched({ attribution: false, platforms: false })
      }}
      onSubmit={() => {
        setTouched(true)
        setJsonTouched({ attribution: true, platforms: true })
        if (!error) mutation.mutate()
      }}
      submitLabel={profile ? "Save profile" : "Create profile"}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Profile name" required error={touched && !form.name.trim() ? error : null}>
          <input autoFocus className={fieldClass} value={form.name} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        </Field>
        <Field label="Output language" required hint="BCP 47 language code, such as fa, en, or en-GB.">
          <input className={fieldClass} maxLength={12} autoCapitalize="none" value={form.outputLanguage} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, outputLanguage: event.target.value })} />
        </Field>
        <Field label="Editorial tone" required hint="Short voice direction, such as neutral, direct, or analytical.">
          <input className={fieldClass} maxLength={120} value={form.tone} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, tone: event.target.value })} />
        </Field>
        <label className="flex min-h-11 items-center gap-2 self-end rounded-lg border px-3 text-sm">
          <input type="checkbox" checked={form.isDefault} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, isDefault: event.target.checked })} />
          Default editorial profile
        </label>
      </div>
      <p className="rounded-lg bg-muted/60 p-3 text-sm leading-6 text-muted-foreground">
        Selecting a default changes profile resolution for future requests that do not choose one explicitly.
        Automation routes keep their selected profile. Saved revisions are immutable.
      </p>
      <details className="rounded-lg border p-3">
        <summary className="cursor-pointer font-medium">Advanced policies and platform preferences</summary>
        <div className="mt-4 grid gap-4">
          <Field label="Editorial rules" hint="One rule per line">
            <textarea className={fieldClass} rows={5} value={form.editorialRules} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, editorialRules: event.target.value })} />
          </Field>
          <Field label="Default hashtags" hint="Separated by spaces">
            <input className={fieldClass} value={form.defaultHashtags} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, defaultHashtags: event.target.value })} />
          </Field>
          <Field
            label="Attribution policy (JSON)"
            hint="Structured source-credit rules passed to future generation jobs."
            error={jsonTouched.attribution ? attribution.error : null}
          >
            <textarea
              className={`${fieldClass} font-mono text-sm`}
              rows={5}
              dir="ltr"
              spellCheck={false}
              value={form.attributionRules}
              disabled={mutation.isPending}
              onBlur={() => setJsonTouched({ ...jsonTouched, attribution: true })}
              onChange={(event) => setForm({ ...form, attributionRules: event.target.value })}
            />
          </Field>
          <Field
            label="Per-platform preferences (JSON)"
            hint='Advanced generation preferences keyed by platform, for example {"telegram":{"direction":"rtl"}}.'
            error={jsonTouched.platforms ? platformPreferences.error : null}
          >
            <textarea
              className={`${fieldClass} font-mono text-sm`}
              rows={6}
              dir="ltr"
              spellCheck={false}
              value={form.platformPreferences}
              disabled={mutation.isPending}
              onBlur={() => setJsonTouched({ ...jsonTouched, platforms: true })}
              onChange={(event) => setForm({ ...form, platformPreferences: event.target.value })}
            />
          </Field>
        </div>
      </details>
    </SettingsDialog>
  )
}

function LLMProvidersSection({ providers }: { providers: LLMProvider[] }) {
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
        const summary = `${dependencies.automations} automations, ${dependencies.generationRuns} generation runs, ${dependencies.researchRuns} research runs, ${dependencies.activeJobs} active jobs`
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
                  <StatusBadge value={provider.healthStatus} />
                </div>
                <p className="mt-1 truncate text-sm text-muted-foreground">{provider.defaultModel} · {provider.baseUrl}</p>
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  <ReadinessLabel label="Generation" ready={provider.generationReady} value={provider.generationCapability} />
                  <ReadinessLabel label="Research" ready={provider.researchReady} value={provider.researchCapability} />
                  <span className="rounded-full bg-muted px-2.5 py-1">{provider.configured ? "API key configured" : "API key missing"}</span>
                  <span className="rounded-full bg-muted px-2.5 py-1">{formatDate(provider.lastCheckedAt, "Never checked")}</span>
                </div>
                {provider.failureCode ? <p className="mt-2 text-sm text-amber-800 dark:text-amber-300" role="status">{safeCode(provider.failureCode)}</p> : null}
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
                <Metric label="Timeout" value={`${provider.settings.timeoutSeconds}s`} />
                <Metric label="Max input" value={provider.settings.maxInputTokens.toLocaleString()} />
                <Metric label="Max output" value={provider.settings.maxOutputTokens.toLocaleString()} />
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
    baseUrl: provider?.baseUrl ?? "https://api.openai.com/v1",
    model: provider?.defaultModel ?? "",
    apiKey: "",
    timeout: provider?.settings.timeoutSeconds ?? 60,
    maxInput: provider?.settings.maxInputTokens ?? 60_000,
    maxOutput: provider?.settings.maxOutputTokens ?? 12_000,
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

function CodexSection({
  connections,
  activity,
  error,
  loading,
  refreshing,
  onRetry,
}: {
  connections: CodexConnection[]
  activity: Array<{ id: string; action: string; outcome: string; reasonCode: string | null; createdAt: string }>
  error: string | null
  loading: boolean
  refreshing: boolean
  onRetry: () => void
}) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [pairing, setPairing] = useState(false)
  const [issued, setIssued] = useState<{ title: string; secret: string; command?: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.codexConnections }),
    queryClient.invalidateQueries({ queryKey: queryKeys.codexActivity }),
  ])
  const rotate = async (connection: CodexConnection) => {
    setBusy(`${connection.id}:rotate`)
    try {
      const result = await rotateCodexConnection(connection.id)
      setIssued({ title: `Rotated credential for ${connection.deviceName}`, secret: result.credential })
      await refresh()
    } catch (cause) {
      pushNotice({ tone: "error", title: "Credential rotation failed", message: getApiErrorMessage(cause) })
    } finally { setBusy(null) }
  }
  const revoke = async (connection: CodexConnection) => {
    if (!window.confirm(`Revoke ${connection.deviceName}? Access stops immediately.`)) return
    setBusy(`${connection.id}:revoke`)
    try {
      await revokeCodexConnection(connection.id)
      await refresh()
      pushNotice({ tone: "success", title: "Codex connection revoked", message: connection.deviceName })
    } catch (cause) {
      pushNotice({ tone: "error", title: "Revocation failed", message: getApiErrorMessage(cause) })
    } finally { setBusy(null) }
  }
  return (
    <SettingsSection
      id="codex-connection"
      icon={ShieldCheck}
      title="Codex connection"
      description="Paired, scoped access. Green requires a recent authenticated heartbeat."
      action={!error && !loading ? <Button onClick={() => setPairing(true)}><Plus aria-hidden="true" /> Pair Codex</Button> : undefined}
    >
      {error ? (
        <div role="alert" className="flex flex-col gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100 sm:flex-row sm:items-center">
          <CircleAlert className="size-5 shrink-0" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold">Codex management unavailable</h3>
            <p dir="auto" className="mt-1 text-sm">{error}</p>
          </div>
          <Button variant="outline" disabled={refreshing} onClick={onRetry}>
            <RefreshCw className={refreshing ? "animate-spin" : undefined} aria-hidden="true" />
            {refreshing ? "Retrying" : "Retry Codex"}
          </Button>
        </div>
      ) : loading ? (
        <div role="status" className="flex min-h-24 items-center justify-center gap-2 rounded-xl border text-sm text-muted-foreground">
          <LoaderCircle className="animate-spin" aria-hidden="true" /> Checking Codex access
        </div>
      ) : connections.length ? <div className="grid gap-3">
        {connections.map((connection) => (
          <article key={connection.id} className="rounded-xl border bg-background p-4">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`size-2.5 rounded-full ${connectionColor(connection.status)}`} aria-hidden="true" />
                  <h3 className="font-semibold">{connection.deviceName}</h3>
                  <StatusBadge value={connection.connectionState} />
                  <StatusBadge value={connection.status} />
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  Last seen {formatDate(connection.lastHeartbeatAt, "never")} · Expires {formatDate(connection.expiresAt)}
                </p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {connection.scopes.map((scope) => <Badge key={scope} variant="outline">{scope}</Badge>)}
                </div>
                {connection.failureCode ? <p className="mt-2 text-sm text-amber-800 dark:text-amber-300">{safeCode(connection.failureCode)}</p> : null}
              </div>
              <div className="flex flex-wrap gap-2">
                <ActionButton label="Rotate" icon={RotateCw} busy={busy === `${connection.id}:rotate`} onClick={() => void rotate(connection)} />
                <ActionButton label="Revoke" icon={Trash2} destructive busy={busy === `${connection.id}:revoke`} onClick={() => void revoke(connection)} />
              </div>
            </div>
          </article>
        ))}
      </div> : <EmptyState title="No Codex connection" detail="Pair a device with least-privilege read scopes." />}
      {!error && !loading ? <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
        <div className="rounded-xl border bg-muted/40 p-4">
          <h3 className="font-semibold">Recent safe activity</h3>
          {activity.length ? <ol className="mt-3 divide-y">
            {activity.map((event) => (
              <li key={event.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span>{safeCode(event.action)} · {safeCode(event.outcome)}</span>
                <time className="text-muted-foreground">{formatDate(event.createdAt)}</time>
              </li>
            ))}
          </ol> : <p className="mt-2 text-sm text-muted-foreground">No recent gateway activity.</p>}
        </div>
        <a className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 text-sm font-medium hover:bg-muted" href="https://github.com/arminakb/NewsCraft/blob/main/docs/codex/skill.md" target="_blank" rel="noreferrer">
          Open skill.md <ExternalLink aria-hidden="true" />
        </a>
      </div> : null}
      {pairing ? <CodexPairingDialog onClose={() => setPairing(false)} onIssued={(result) => { setPairing(false); setIssued(result); void refresh() }} /> : null}
      {issued ? <OneTimeSecretDialog {...issued} onClose={() => setIssued(null)} /> : null}
    </SettingsSection>
  )
}

function CodexPairingDialog({ onClose, onIssued }: { onClose: () => void; onIssued: (result: { title: string; secret: string; command?: string }) => void }) {
  const { pushNotice } = useNotices()
  const initial = { deviceName: "", scopes: readScopes }
  const [form, setForm] = useState(initial)
  const [touched, setTouched] = useState(false)
  const dirty = form.deviceName !== "" || form.scopes.length !== readScopes.length
  const mutation = useMutation({
    mutationFn: () => createCodexPairingSession(form.deviceName.trim(), form.scopes),
    onSuccess: (session) => onIssued({ title: `Pair ${session.deviceName}`, secret: session.pairingCode, command: session.localCommand }),
    onError: (cause) => pushNotice({ tone: "error", title: "Pairing session failed", message: getApiErrorMessage(cause) }),
  })
  return (
    <SettingsDialog
      title="Pair Codex"
      description="Create a five-minute, one-time pairing code. Start with least-privilege read scopes."
      dirty={dirty}
      pending={mutation.isPending}
      submitDisabled={!form.deviceName.trim() || !form.scopes.length}
      onClose={onClose}
      onReset={() => setForm(initial)}
      onSubmit={() => { setTouched(true); if (form.deviceName.trim() && form.scopes.length) mutation.mutate() }}
      submitLabel="Create pairing code"
    >
      <Field label="Agent or device name" required error={touched && !form.deviceName.trim() ? "Enter a device name." : null}>
        <input autoFocus className={fieldClass} value={form.deviceName} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, deviceName: event.target.value })} />
      </Field>
      <fieldset className="rounded-lg border p-3">
        <legend className="px-1 text-sm font-medium">Granted read scopes</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {readScopes.map((scope) => (
            <label key={scope} className="flex min-h-10 items-center gap-2 rounded-md px-2 hover:bg-muted">
              <input type="checkbox" checked={form.scopes.includes(scope)} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, scopes: event.target.checked ? [...form.scopes, scope] : form.scopes.filter((item) => item !== scope) })} />
              <span className="text-sm">{scope}</span>
            </label>
          ))}
        </div>
      </fieldset>
    </SettingsDialog>
  )
}

function TelegramSection({ destinations, proxies }: { destinations: TelegramDestination[]; proxies: TelegramProxy[] }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [editing, setEditing] = useState<TelegramDestination | "new" | null>(null)
  const [rotating, setRotating] = useState<TelegramDestination | null>(null)
  const [proxyEditing, setProxyEditing] = useState<TelegramProxy | "new" | null>(null)
  const [proxyRotating, setProxyRotating] = useState<TelegramProxy | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.telegramDestinations }),
    queryClient.invalidateQueries({ queryKey: queryKeys.telegramProxies }),
    queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
  ])
  const destinationAction = async (destination: TelegramDestination, action: "recheck" | "toggle" | "dependencies" | "delete") => {
    setBusy(`${destination.id}:${action}`)
    try {
      if (action === "recheck") {
        await recheckTelegramDestination(destination.id)
        pushNotice({ tone: "success", title: "Destination check queued", message: "Health updates automatically." })
      } else if (action === "toggle") {
        await setTelegramDestinationEnabled(destination.id, !destination.enabled)
      } else {
        const deps = await getTelegramDestinationDependencies(destination.id)
        const summary = `${deps.automations} automations, ${deps.publishJobs} publish jobs, ${deps.publications} publications, ${deps.activeJobs} active jobs`
        if (action === "dependencies") pushNotice({ tone: deps.blocked ? "error" : "success", title: "Destination dependencies", message: summary })
        else if (!deps.blocked && window.confirm(`Delete ${destination.name}? This cannot be undone.`)) await deleteTelegramDestination(destination.id)
        else if (deps.blocked) pushNotice({ tone: "error", title: "Destination cannot be deleted", message: summary })
      }
      await refresh()
    } catch (cause) {
      pushNotice({ tone: "error", title: "Destination action failed", message: getApiErrorMessage(cause) })
    } finally { setBusy(null) }
  }
  const proxyAction = async (proxy: TelegramProxy, action: "recheck" | "toggle" | "delete") => {
    setBusy(`${proxy.id}:${action}`)
    try {
      if (action === "recheck") await recheckTelegramProxy(proxy.id)
      else if (action === "toggle") await setTelegramProxyEnabled(proxy.id, !proxy.enabled)
      else {
        const deps = await getTelegramProxyDependencies(proxy.id)
        if (deps.blocked) pushNotice({ tone: "error", title: "Proxy cannot be deleted", message: `Assigned to ${deps.destinations} destinations.` })
        else if (window.confirm(`Delete ${proxy.name}?`)) await deleteTelegramProxy(proxy.id)
      }
      await refresh()
    } catch (cause) {
      pushNotice({ tone: "error", title: "Proxy action failed", message: getApiErrorMessage(cause) })
    } finally { setBusy(null) }
  }
  return (
    <SettingsSection
      id="telegram-destinations"
      icon={Bot}
      title="Telegram destinations"
      description="Bot API destinations and reusable direct or proxy connection routes."
      action={<Button onClick={() => setEditing("new")}><Plus aria-hidden="true" /> Add destination</Button>}
    >
      {destinations.length ? <div className="grid gap-3">
        {destinations.map((destination) => (
          <article key={destination.id} className="rounded-xl border bg-background p-4">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-semibold">{destination.name}</h3>
                  <StatusBadge value={destination.enabled ? "enabled" : "disabled"} />
                  <StatusBadge value={destination.healthStatus} />
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{destination.canonicalTarget} · {destination.connectionRoute}</p>
                <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                  <HealthStage label="Proxy" value={destination.proxyHealthStatus} />
                  <HealthStage label="Telegram API" value={destination.telegramHealthStatus} />
                  <HealthStage label="Bot" value={destination.botHealthStatus} />
                  <HealthStage label="Target" value={destination.targetHealthStatus} />
                  <HealthStage label="Administrator" value={destination.administratorStatus} />
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  {destination.verifiedChatTitle ?? "Target not verified"} · {destination.verifiedBotUsername ? `@${destination.verifiedBotUsername}` : "Bot not verified"} · {formatDate(destination.lastCheckedAt, "Never checked")}
                </p>
                {destination.failureCode ? <p className="mt-2 text-sm text-amber-800 dark:text-amber-300">{safeCode(destination.failureCode)}</p> : null}
              </div>
              <div className="flex flex-wrap gap-2 xl:max-w-md xl:justify-end">
                <ActionButton label="Edit" icon={Pencil} onClick={() => setEditing(destination)} />
                <ActionButton label="Rotate token" icon={KeyRound} onClick={() => setRotating(destination)} />
                <ActionButton label="Recheck" icon={RefreshCw} busy={busy === `${destination.id}:recheck`} onClick={() => void destinationAction(destination, "recheck")} />
                <ActionButton label={destination.enabled ? "Disable" : "Enable"} icon={ShieldCheck} busy={busy === `${destination.id}:toggle`} onClick={() => void destinationAction(destination, "toggle")} />
                <ActionButton label="Dependencies" icon={Route} busy={busy === `${destination.id}:dependencies`} onClick={() => void destinationAction(destination, "dependencies")} />
                <ActionButton label="Delete" icon={Trash2} destructive busy={busy === `${destination.id}:delete`} onClick={() => void destinationAction(destination, "delete")} />
              </div>
            </div>
          </article>
        ))}
      </div> : <EmptyState title="No Telegram destinations" detail="Add a bot token and channel or group identifier." />}

      <details className="rounded-xl border bg-muted/30 p-4">
        <summary className="cursor-pointer font-semibold">Manage proxy profiles ({proxies.length})</summary>
        <div className="mt-4 space-y-3">
          <Button variant="outline" onClick={() => setProxyEditing("new")}><Plus aria-hidden="true" /> New proxy profile</Button>
          {proxies.map((proxy) => (
            <div key={proxy.id} className="flex flex-col gap-3 rounded-lg border bg-background p-3 lg:flex-row lg:items-center">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2"><strong>{proxy.name}</strong><StatusBadge value={proxy.enabled ? "enabled" : "disabled"} /><StatusBadge value={proxy.reachabilityStatus} /></div>
                <div className="mt-1 text-sm text-muted-foreground">{proxy.proxyType === "http_connect" ? "HTTP CONNECT" : "SOCKS5"} · {proxy.host}:{proxy.port} · {proxy.credentialsConfigured ? "Credentials configured" : "No credentials"}</div>
              </div>
              <div className="flex flex-wrap gap-2">
                <ActionButton label="Edit" icon={Pencil} onClick={() => setProxyEditing(proxy)} />
                <ActionButton label="Credentials" icon={KeyRound} onClick={() => setProxyRotating(proxy)} />
                <ActionButton label="Test" icon={RefreshCw} busy={busy === `${proxy.id}:recheck`} onClick={() => void proxyAction(proxy, "recheck")} />
                <ActionButton label={proxy.enabled ? "Disable" : "Enable"} icon={ShieldCheck} busy={busy === `${proxy.id}:toggle`} onClick={() => void proxyAction(proxy, "toggle")} />
                <ActionButton label="Delete" icon={Trash2} destructive busy={busy === `${proxy.id}:delete`} onClick={() => void proxyAction(proxy, "delete")} />
              </div>
            </div>
          ))}
        </div>
      </details>
      {editing ? <DestinationDialog destination={editing === "new" ? null : editing} proxies={proxies} onClose={() => setEditing(null)} /> : null}
      {proxyEditing ? <ProxyDialog proxy={proxyEditing === "new" ? null : proxyEditing} onClose={() => setProxyEditing(null)} /> : null}
      {proxyRotating ? <ProxyCredentialsDialog proxy={proxyRotating} onClose={() => setProxyRotating(null)} /> : null}
      {rotating ? <SecretDialog title={`Rotate token for ${rotating.name}`} label="New bot token" onClose={() => setRotating(null)} onSave={async (secret) => { await rotateTelegramToken(rotating.id, secret); await refresh(); pushNotice({ tone: "success", title: "Bot token rotated", message: "Destination check queued." }) }} /> : null}
    </SettingsSection>
  )
}

function DestinationDialog({
  destination,
  proxies,
  onClose,
}: {
  destination: TelegramDestination | null
  proxies: TelegramProxy[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const initial = { name: destination?.name ?? "", target: destination?.targetRef ?? "", botToken: "", proxyProfileId: destination?.proxyProfileId ?? "" }
  const [form, setForm] = useState(initial)
  const [showProxyCreate, setShowProxyCreate] = useState(false)
  const [newProxy, setNewProxy] = useState({
    name: "",
    proxyType: "http_connect" as TelegramProxy["proxyType"],
    host: "",
    port: 8080,
    username: "",
    password: "",
  })
  const [touched, setTouched] = useState(false)
  const dirty = JSON.stringify(form) !== JSON.stringify(initial) || showProxyCreate
  const error = !form.name.trim() ? "Enter a destination name." : !form.target.trim() ? "Enter a channel or group identifier." : !destination && !form.botToken ? "Enter a bot token." : null
  const mutation = useMutation({
    mutationFn: () => destination
      ? updateTelegramDestination(destination.id, { name: form.name.trim(), target: form.target.trim(), proxyProfileId: form.proxyProfileId || null })
      : createTelegramDestination({ name: form.name.trim(), target: form.target.trim(), botToken: form.botToken, proxyProfileId: form.proxyProfileId || null }),
    onSuccess: async () => {
      setForm({ ...form, botToken: "" })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramDestinations }),
        queryClient.invalidateQueries({ queryKey: queryKeys.telegramOptions }),
      ])
      pushNotice({ tone: "success", title: destination ? "Destination updated" : "Destination created", message: "Route-specific health check queued." })
      onClose()
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Destination could not be saved", message: getApiErrorMessage(cause) }),
  })
  const createProxy = useMutation({
    mutationFn: () => createTelegramProxy({
      name: newProxy.name.trim(),
      proxyType: newProxy.proxyType,
      host: newProxy.host.trim(),
      port: newProxy.port,
      ...(newProxy.username ? { username: newProxy.username, password: newProxy.password } : {}),
    }),
    onSuccess: async (result) => {
      setForm((current) => ({ ...current, proxyProfileId: result.proxy.id }))
      setShowProxyCreate(false)
      setNewProxy({ name: "", proxyType: "http_connect", host: "", port: 8080, username: "", password: "" })
      await queryClient.invalidateQueries({ queryKey: queryKeys.telegramProxies })
      pushNotice({ tone: "success", title: "Proxy profile created", message: "Selected for this destination. Reachability check queued." })
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Proxy could not be created", message: getApiErrorMessage(cause) }),
  })
  const proxyCredentialsInvalid = Boolean(newProxy.username) !== Boolean(newProxy.password)
  const proxyInvalid = !newProxy.name.trim() || !newProxy.host.trim() || newProxy.host.includes("://") || proxyCredentialsInvalid
  return (
    <SettingsDialog
      title={destination ? `Edit ${destination.name}` : "Add Telegram destination"}
      description="The same selected route is used for health checks and every publish request."
      dirty={dirty}
      pending={mutation.isPending || createProxy.isPending}
      submitDisabled={Boolean(error) || showProxyCreate}
      onClose={onClose}
      onReset={() => { setForm(initial); setShowProxyCreate(false) }}
      onSubmit={() => { setTouched(true); if (!error) mutation.mutate() }}
      submitLabel={destination ? "Save destination" : "Add destination"}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Destination name" required error={touched && !form.name.trim() ? error : null}>
          <input autoFocus className={fieldClass} value={form.name} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        </Field>
        <Field label="Channel or group identifier" required hint="@channel or numeric ID">
          <input className={fieldClass} value={form.target} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, target: event.target.value })} />
        </Field>
      </div>
      {!destination ? <Field label="Bot token" required hint="Write-only. Never shown again."><input type="password" autoComplete="new-password" className={fieldClass} value={form.botToken} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, botToken: event.target.value })} /></Field> : null}
      <Field label="Connection route">
        <div className="flex gap-2">
          <select className={fieldClass} value={form.proxyProfileId} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, proxyProfileId: event.target.value })}>
            <option value="">Direct connection</option>
            {proxies.filter((proxy) => proxy.enabled).map((proxy) => <option key={proxy.id} value={proxy.id}>{proxy.name} · {proxy.proxyType === "http_connect" ? "HTTP CONNECT" : "SOCKS5"}</option>)}
          </select>
          <Button type="button" variant="outline" onClick={() => setShowProxyCreate((value) => !value)}>{showProxyCreate ? "Cancel proxy" : "New proxy"}</Button>
        </div>
      </Field>
      {showProxyCreate ? (
        <fieldset className="space-y-4 rounded-lg border bg-muted/30 p-4">
          <legend className="px-1 font-medium">Create proxy inline</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Proxy name" required><input className={fieldClass} value={newProxy.name} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, name: event.target.value })} /></Field>
            <Field label="Proxy type"><select className={fieldClass} value={newProxy.proxyType} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, proxyType: event.target.value as TelegramProxy["proxyType"] })}><option value="http_connect">HTTP CONNECT</option><option value="socks5">SOCKS5</option></select></Field>
            <Field label="Host" required error={newProxy.host.includes("://") ? "Use a plain host without a scheme." : null}><input className={fieldClass} value={newProxy.host} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, host: event.target.value })} /></Field>
            <NumberField label="Port" value={newProxy.port} min={1} max={65535} onChange={(port) => setNewProxy({ ...newProxy, port })} />
            <Field label="Username" error={proxyCredentialsInvalid ? "Username and password must be supplied together." : null}><input className={fieldClass} autoComplete="off" value={newProxy.username} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, username: event.target.value })} /></Field>
            <Field label="Password"><input type="password" className={fieldClass} autoComplete="new-password" value={newProxy.password} disabled={createProxy.isPending} onChange={(event) => setNewProxy({ ...newProxy, password: event.target.value })} /></Field>
          </div>
          <Button type="button" disabled={proxyInvalid || createProxy.isPending} onClick={() => createProxy.mutate()}>{createProxy.isPending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Plus aria-hidden="true" />}Create and select proxy</Button>
        </fieldset>
      ) : null}
    </SettingsDialog>
  )
}

function ProxyDialog({ proxy, onClose }: { proxy: TelegramProxy | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const initial = { name: proxy?.name ?? "", proxyType: proxy?.proxyType ?? "http_connect" as const, host: proxy?.host ?? "", port: proxy?.port ?? 8080, username: "", password: "" }
  const [form, setForm] = useState(initial)
  const [touched, setTouched] = useState(false)
  const dirty = JSON.stringify(form) !== JSON.stringify(initial)
  const credentialsInvalid = Boolean(form.username) !== Boolean(form.password)
  const error = !form.name.trim() ? "Enter a proxy name." : !form.host.trim() ? "Enter a plain hostname." : form.host.includes("://") ? "Host must not include a scheme." : credentialsInvalid ? "Username and password must be supplied together." : null
  const mutation = useMutation({
    mutationFn: () => proxy
      ? updateTelegramProxy(proxy.id, { name: form.name.trim(), proxyType: form.proxyType, host: form.host.trim(), port: form.port })
      : createTelegramProxy({ name: form.name.trim(), proxyType: form.proxyType, host: form.host.trim(), port: form.port, ...(form.username ? { username: form.username, password: form.password } : {}) }),
    onSuccess: async () => {
      setForm({ ...form, username: "", password: "" })
      await queryClient.invalidateQueries({ queryKey: queryKeys.telegramProxies })
      pushNotice({ tone: "success", title: proxy ? "Proxy updated" : "Proxy created", message: "Reachability check queued." })
      onClose()
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Proxy could not be saved", message: getApiErrorMessage(cause) }),
  })
  return (
    <SettingsDialog
      title={proxy ? `Edit ${proxy.name}` : "New proxy profile"}
      description="Supported transport: HTTP/HTTPS CONNECT or SOCKS5. MTProto is not supported."
      dirty={dirty}
      pending={mutation.isPending}
      submitDisabled={Boolean(error)}
      onClose={onClose}
      onReset={() => setForm(initial)}
      onSubmit={() => { setTouched(true); if (!error) mutation.mutate() }}
      submitLabel={proxy ? "Save proxy" : "Create proxy"}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Profile name" required error={touched && error?.includes("name") ? error : null}><input autoFocus className={fieldClass} value={form.name} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field>
        <Field label="Proxy type"><select className={fieldClass} value={form.proxyType} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, proxyType: event.target.value as "http_connect" | "socks5" })}><option value="http_connect">HTTP CONNECT</option><option value="socks5">SOCKS5</option></select></Field>
        <Field label="Host" required error={touched && (form.host.includes("://") || !form.host.trim()) ? error : null}><input className={fieldClass} value={form.host} disabled={mutation.isPending} onBlur={() => setTouched(true)} onChange={(event) => setForm({ ...form, host: event.target.value })} /></Field>
        <NumberField label="Port" value={form.port} min={1} max={65535} onChange={(port) => setForm({ ...form, port })} />
      </div>
      {!proxy ? <details className="rounded-lg border p-3"><summary className="cursor-pointer font-medium">Optional proxy credentials</summary><div className="mt-4 grid gap-4 sm:grid-cols-2"><Field label="Username" error={touched && credentialsInvalid ? error : null}><input className={fieldClass} autoComplete="off" value={form.username} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, username: event.target.value })} /></Field><Field label="Password"><input type="password" autoComplete="new-password" className={fieldClass} value={form.password} disabled={mutation.isPending} onChange={(event) => setForm({ ...form, password: event.target.value })} /></Field></div></details> : null}
    </SettingsDialog>
  )
}

function ProxyCredentialsDialog({ proxy, onClose }: { proxy: TelegramProxy; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { pushNotice } = useNotices()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [remove, setRemove] = useState(false)
  const [pending, setPending] = useState(false)
  const dirty = Boolean(username || password || remove)
  const invalid = Boolean(username) !== Boolean(password)
  return (
    <SettingsDialog
      title={`Proxy credentials for ${proxy.name}`}
      description="Submit both values to rotate credentials, or leave both blank and save to remove them."
      dirty={dirty}
      pending={pending}
      submitDisabled={invalid}
      onClose={onClose}
      onReset={() => { setUsername(""); setPassword(""); setRemove(false) }}
      onSubmit={() => {
        if (invalid) return
        setPending(true)
        void rotateTelegramProxyCredentials(proxy.id, remove ? undefined : username || undefined, remove ? undefined : password || undefined)
          .then(async () => {
            setUsername("")
            setPassword("")
            await queryClient.invalidateQueries({ queryKey: queryKeys.telegramProxies })
            pushNotice({ tone: "success", title: "Proxy credentials updated", message: "Reachability check queued." })
            onClose()
          })
          .catch((cause) => pushNotice({ tone: "error", title: "Credential rotation failed", message: getApiErrorMessage(cause) }))
          .finally(() => setPending(false))
      }}
      submitLabel={remove ? "Remove credentials" : "Rotate credentials"}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Username" error={invalid ? "Username and password must be supplied together." : null}>
          <input autoFocus className={fieldClass} autoComplete="off" value={username} disabled={pending || remove} onChange={(event) => setUsername(event.target.value)} />
        </Field>
        <Field label="Password">
          <input type="password" className={fieldClass} autoComplete="new-password" value={password} disabled={pending || remove} onChange={(event) => setPassword(event.target.value)} />
        </Field>
      </div>
      {proxy.credentialsConfigured ? <label className="flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm"><input type="checkbox" checked={remove} disabled={pending} onChange={(event) => { setRemove(event.target.checked); if (event.target.checked) { setUsername(""); setPassword("") } }} />Remove configured credentials</label> : null}
    </SettingsDialog>
  )
}

function PromptGovernanceSection({ templates }: { templates: Array<{ id: string; purposeKey: string; name: string; description: string | null }> }) {
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
  const active = versions.data?.find((version) => version.isActive)
  return (
    <article className="rounded-xl border bg-background p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">{meta.label}</h3>
            <StatusBadge value={!template ? "not configured" : active ? "active" : "inactive"} />
          </div>
          <p className="mt-1 text-sm">{meta.pipeline}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {!template ? "No template configured." : active ? `Version ${active.version} · ${active.checksumSha256.slice(0, 12)} · Follow-active jobs resolve this version; pinned jobs retain their selection.` : `${versions.data?.length ?? 0} immutable versions · no active version.`}
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
              queryClient.invalidateQueries({ queryKey: queryKeys.editorialPromptOptions }),
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
  const { pushNotice } = useNotices()
  const active = versions.find((version) => version.isActive)
  const [systemTemplate, setSystemTemplate] = useState(active?.systemTemplate ?? "")
  const [userTemplate, setUserTemplate] = useState(active?.userTemplate ?? "")
  const [activationTarget, setActivationTarget] = useState<string | null>(null)
  const [activationReason, setActivationReason] = useState("")
  const [confirmed, setConfirmed] = useState(false)
  const draftError = validatePromptDraft(systemTemplate, userTemplate, requiredVariables)
  const changedFromActive = Boolean(active) && (active!.systemTemplate !== systemTemplate || active!.userTemplate !== userTemplate)
  const target = versions.find((version) => version.id === activationTarget)
  const create = useMutation({
    mutationFn: () => createPromptVersion(template.id, { systemTemplate, userTemplate }),
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
      setSystemTemplate(version.systemTemplate)
      setUserTemplate(version.userTemplate)
      await onChanged()
      pushNotice({ tone: "success", title: `${label} activated`, message: `Version ${version.version} is active for future follow-active jobs.` })
    },
    onError: (cause) => pushNotice({ tone: "error", title: "Prompt activation failed", message: getApiErrorMessage(cause) }),
  })
  const dirty = changedFromActive
  useDirtyNavigation(dirty, "Discard unsaved prompt changes?")
  const resetDraft = () => {
    setSystemTemplate(active?.systemTemplate ?? "")
    setUserTemplate(active?.userTemplate ?? "")
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
          {target && !target.isActive ? (
            <div className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">
              <div><strong>Activate version {target.version}?</strong><p className="text-sm">Follow-active routes and new editorial jobs will resolve this version. Pinned routes and existing revisions remain unchanged.</p></div>
              {active ? <PromptDiff before={active} systemTemplate={target.systemTemplate} userTemplate={target.userTemplate} /> : null}
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
                    <div className="break-all text-xs text-muted-foreground">{version.checksumSha256} · {version.isActive ? "Active" : "Inactive"}</div>
                    {version.activationReason ? (
                      <div className="mt-1 text-xs text-muted-foreground">
                        Activated {formatDate(version.activatedAt)} by {version.activatedByType} {version.activatedById} · {version.activationReason}
                      </div>
                    ) : null}
                  </div>
                  <Button variant="outline" disabled={version.isActive || activate.isPending} onClick={() => { setActivationTarget(version.id); setConfirmed(false); setActivationReason("") }}>Review activation</Button>
                </div>
                <details className="mt-2"><summary className="cursor-pointer text-sm">Inspect raw template</summary><DirectionBoundary as="pre" language={null} className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">{version.systemTemplate}{"\n\n"}{version.userTemplate}</DirectionBoundary></details>
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
      <div><strong>Current version {before.version}</strong><pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-red-50 p-2 text-red-950 dark:bg-red-950/30 dark:text-red-100">{before.systemTemplate}{"\n\n"}{before.userTemplate}</pre></div>
      <div><strong>Proposed version</strong><pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-emerald-50 p-2 text-emerald-950 dark:bg-emerald-950/30 dark:text-emerald-100">{systemTemplate}{"\n\n"}{userTemplate}</pre></div>
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

function SettingsSection({
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
  return (
    <Card id={id} className="scroll-mt-20">
      <CardHeader className="border-b">
        <div className="flex items-start gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground"><Icon className="size-5" aria-hidden="true" /></span>
          <div><CardTitle className="text-lg"><h2 className="text-lg font-semibold">{title}</h2></CardTitle><CardDescription className="mt-1">{description}</CardDescription></div>
        </div>
        {action ? <CardAction>{action}</CardAction> : null}
      </CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  )
}

function SettingsDialog({
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
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const initialRef = useRef<HTMLElement>(null)
  const releaseDirty = useDirtyNavigation(dirty, "Discard unsaved settings changes?")
  const close = () => {
    if (pending) return
    if (!dirty || window.confirm("Discard unsaved settings changes?")) {
      releaseDirty()
      onClose()
    }
  }
  useEditorialModal({ open: true, containerRef: dialogRef, initialFocusRef: initialRef, onClose: close, canClose: !pending })
  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} tabIndex={-1} className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-slate-950/50 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) close() }}>
      <form className="my-auto w-full max-w-2xl space-y-5 rounded-xl border bg-background p-5 shadow-2xl" onSubmit={(event) => { event.preventDefault(); onSubmit() }}>
        <div className="flex items-start justify-between gap-4">
          <div><h2 id={titleId} className="text-xl font-semibold">{title}</h2><p id={descriptionId} className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p></div>
          <Button type="button" size="icon" variant="ghost" aria-label="Close dialog" disabled={pending} onClick={close}><X aria-hidden="true" /></Button>
        </div>
        {children}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <span className="text-xs text-muted-foreground">{dirty ? "Unsaved changes" : "No unsaved changes"}</span>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" disabled={!dirty || pending} onClick={onReset}>Reset</Button>
            <Button type="button" variant="outline" disabled={pending} onClick={close}>Cancel</Button>
            <Button type="submit" disabled={!dirty || pending || submitDisabled}>{pending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : null}{pending ? "Saving…" : submitLabel}</Button>
          </div>
        </div>
      </form>
    </div>
  )
}

function SecretDialog({ title, label, onClose, onSave }: { title: string; label: string; onClose: () => void; onSave: (secret: string) => Promise<void> }) {
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
        void onSave(secret).then(() => { setSecret(""); onClose() }).catch((cause) => pushNotice({ tone: "error", title: "Secret rotation failed", message: getApiErrorMessage(cause) })).finally(() => setPending(false))
      }}
      submitLabel="Rotate secret"
    >
      <Field label={label} required><input autoFocus type="password" autoComplete="new-password" className={fieldClass} value={secret} disabled={pending} onChange={(event) => setSecret(event.target.value)} /></Field>
    </SettingsDialog>
  )
}

function OneTimeSecretDialog({ title, secret, command, onClose }: { title: string; secret: string; command?: string; onClose: () => void }) {
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  useEditorialModal({ open: true, containerRef: dialogRef, initialFocusRef: closeRef, onClose })
  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4">
      <div className="w-full max-w-2xl space-y-4 rounded-xl border bg-background p-5 shadow-2xl">
        <div><h2 id={titleId} className="text-xl font-semibold">{title}</h2><p className="mt-1 text-sm text-amber-800 dark:text-amber-300">Shown once. Store it safely; never paste it into chat, logs, or Git.</p></div>
        <Field label="One-time pairing code or credential"><DirectionBoundary as="textarea" language="en" readOnly className={`${fieldClass} font-mono`} rows={3} value={secret} /></Field>
        {command ? <Field label="Local exchange command"><DirectionBoundary as="textarea" language="en" readOnly className={`${fieldClass} font-mono text-sm`} rows={5} value={command} /></Field> : null}
        <div className="flex justify-end"><Button ref={closeRef} onClick={onClose}>I stored it safely</Button></div>
      </div>
    </div>
  )
}

function Field({ label, hint, error, required, children }: { label: string; hint?: string; error?: string | null; required?: boolean; children: React.ReactNode }) {
  const messageId = useId()
  const control = isValidElement<Record<string, unknown>>(children)
    ? cloneElement(children, {
      ...(error ? { "aria-invalid": true } : {}),
      ...((error || hint) ? { "aria-describedby": messageId } : {}),
    })
    : children
  return (
    <label className="grid gap-1.5 text-sm font-medium">
      <span>{label}{required ? <span className="text-red-700 dark:text-red-300" aria-hidden="true"> *</span> : null}</span>
      {control}
      {error ? <span id={messageId} className="text-sm font-normal text-red-700 dark:text-red-300" role="alert">{error}</span> : hint ? <span id={messageId} className="text-xs font-normal text-muted-foreground">{hint}</span> : null}
    </label>
  )
}

function NumberField({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  return <Field label={label}><input type="number" className={fieldClass} value={value} min={min} max={max} onChange={(event) => onChange(Number(event.target.value))} /></Field>
}

function ActionButton({ label, icon: Icon, busy, destructive, onClick }: { label: string; icon: typeof Activity; busy?: boolean; destructive?: boolean; onClick: () => void }) {
  return <Button size="sm" variant={destructive ? "destructive" : "outline"} disabled={busy} onClick={onClick}>{busy ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Icon aria-hidden="true" />}{label}</Button>
}

function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase()
  const bad = ["unhealthy", "unavailable", "red", "revoked", "disabled", "failed", "not configured"].includes(normalized)
  const good = ["healthy", "ready", "green", "active", "enabled", "reachable", "verified", "administrator"].includes(normalized)
  return <Badge variant={bad ? "destructive" : good ? "secondary" : "outline"}>{safeCode(value)}</Badge>
}

function ReadinessLabel({ label, ready, value }: { label: string; ready: boolean; value: string }) {
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 ${ready ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300" : "bg-amber-50 text-amber-900 dark:bg-amber-950/50 dark:text-amber-200"}`}>{ready ? <CheckCircle2 className="size-3.5" aria-hidden="true" /> : <CircleAlert className="size-3.5" aria-hidden="true" />}{label}: {safeCode(value)}</span>
}

function HealthStage({ label, value }: { label: string; value: string }) {
  const healthy = ["healthy", "reachable", "authenticated", "resolved", "administrator", "ready", "direct"].includes(value)
  return <div className="rounded-lg bg-muted/60 p-2 text-xs"><div className="font-medium">{label}</div><div className={`mt-1 flex items-center gap-1 ${healthy ? "text-emerald-800 dark:text-emerald-300" : "text-muted-foreground"}`}>{healthy ? <CheckCircle2 className="size-3.5" aria-hidden="true" /> : <CircleDashed className="size-3.5" aria-hidden="true" />}{safeCode(value)}</div></div>
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs text-muted-foreground">{label}</dt><dd className="font-medium">{value}</dd></div>
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="rounded-xl border border-dashed p-8 text-center"><h3 className="font-semibold">{title}</h3><p className="mt-1 text-sm text-muted-foreground">{detail}</p></div>
}

function SettingsSkeleton() {
  return <section className="space-y-5 p-4 md:p-6" role="status" aria-label="Loading content settings"><div className="h-9 w-64 animate-pulse rounded bg-muted" /><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }, (_, index) => <div key={index} className="h-20 animate-pulse rounded-xl bg-muted" />)}</div><div className="h-72 animate-pulse rounded-xl bg-muted" /><span className="sr-only">Loading content settings</span></section>
}

function safeCode(value: string) {
  return value.replaceAll("_", " ")
}

function formatDate(value: string | null, fallback = "Unknown") {
  if (!value) return fallback
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? fallback : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parsed)
}

function connectionColor(status: CodexConnection["status"]) {
  if (status === "green") return "bg-emerald-600"
  if (status === "yellow") return "bg-amber-500"
  if (status === "red") return "bg-red-600"
  return "bg-slate-400"
}

function lines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean)
}

function words(value: string) {
  return value.split(/\s+/).map((item) => item.trim()).filter(Boolean)
}

function parseJsonObject(value: string): { value: Record<string, unknown>; error: string | null } {
  if (!value.trim()) return { value: {}, error: null }
  try {
    const parsed: unknown = JSON.parse(value)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      return { value: {}, error: "Enter a JSON object using braces." }
    }
    return { value: parsed as Record<string, unknown>, error: null }
  } catch {
    return { value: {}, error: "Enter valid JSON with quoted keys and values." }
  }
}

function formatJsonObject(value: Record<string, unknown>) {
  return JSON.stringify(value, null, 2)
}

function compactJson(value: Record<string, unknown>) {
  return Object.keys(value).length ? JSON.stringify(value) : "None"
}
