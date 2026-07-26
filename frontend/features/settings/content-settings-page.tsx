"use client"

import { useQuery } from "@tanstack/react-query"
import {
  Activity,
  Bot,
  BrainCircuit,
  CheckCircle2,
  CircleAlert,
  RefreshCw,
  ShieldCheck,
  UserRound,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  getBrandProfiles,
  getPromptTemplates,
} from "@/features/automations/telegram-api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"
import { CodexSection } from "./codex-section"
import { SettingsSkeleton } from "./content-settings-primitives"
import {
  getCodexActivity,
  getCodexConnections,
  getLLMProviders,
  getTelegramDestinations,
  getTelegramProxies,
} from "./content-settings-api"
import { EditorialProfilesSection } from "./editorial-profiles-section"
import { LLMProvidersSection } from "./llm-providers-section"
import { PromptGovernanceSection } from "./prompt-governance-section"
import { TelegramSection } from "./telegram-section"

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
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.reachabilityStatus === "checking") ? 3_000 : false,
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
        <Button
          variant="outline"
          onClick={() => void Promise.all(requiredQueries.map((query) => query.refetch()))}
        >
          <RefreshCw aria-hidden="true" /> Retry settings
        </Button>
      </section>
    )
  }

  const profiles = brands.data ?? []
  const llmProviders = providers.data ?? []
  const telegramDestinations = destinations.data ?? []
  const promptTemplates = templates.data ?? []
  const enabledProviders = llmProviders.filter((item) => item.enabled)
  const healthyDestinations = telegramDestinations.filter((item) => item.healthStatus === "healthy")
  const greenConnections = connections.data?.filter((item) => item.status === "green") ?? []
  const codexSummary = codexError
    ? "Authentication required"
    : codexPending
      ? "Checking"
      : greenConnections.length
        ? `${greenConnections.length} connected`
        : "No live heartbeat"
  const setup = [
    {
      href: "#editorial-profiles",
      label: "Editorial profile",
      ready: profiles.some((item) => item.isDefault),
      detail: profiles.some((item) => item.isDefault) ? "Default selected" : "Choose a default profile",
    },
    {
      href: "#llm-providers",
      label: "LLM provider",
      ready: enabledProviders.some((item) => item.generationReady),
      detail: enabledProviders.some((item) => item.generationReady)
        ? "Generation ready"
        : "Connect and test a provider",
    },
    {
      href: "#telegram-destinations",
      label: "Telegram destination",
      ready: healthyDestinations.length > 0,
      detail: healthyDestinations.length > 0
        ? "Healthy destination available"
        : "Add or repair a destination",
    },
    {
      href: "#prompt-governance",
      label: "Prompt governance",
      ready: promptTemplates.length > 0,
      detail: promptTemplates.length > 0 ? "Prompt purposes configured" : "Configure required prompts",
    },
  ]

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
        <SummaryCard
          icon={BrainCircuit}
          label="LLM providers"
          value={`${enabledProviders.length} enabled`}
          ready={enabledProviders.some((item) => item.generationReady)}
        />
        <SummaryCard
          icon={Bot}
          label="Telegram"
          value={`${healthyDestinations.length}/${telegramDestinations.length} healthy`}
          ready={healthyDestinations.length > 0}
        />
        <SummaryCard
          icon={ShieldCheck}
          label="Codex"
          value={codexSummary}
          ready={!codexError && greenConnections.length > 0}
        />
        <SummaryCard
          icon={Activity}
          label="Prompt purposes"
          value={`${promptTemplates.length} configured`}
          ready={promptTemplates.length > 0}
        />
      </div>

      <aside className="rounded-xl border bg-card p-4" aria-labelledby="setup-checklist-heading">
        <div className="flex items-center gap-2">
          <UserRound className="size-5 text-primary" aria-hidden="true" />
          <h2 id="setup-checklist-heading" className="font-semibold">Setup checklist</h2>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {setup.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="flex min-h-11 items-center gap-3 rounded-lg border px-3 py-2 text-sm hover:bg-muted"
            >
              {item.ready
                ? <CheckCircle2 className="size-4 shrink-0 text-emerald-600" aria-hidden="true" />
                : <CircleAlert className="size-4 shrink-0 text-amber-600" aria-hidden="true" />}
              <span>
                <strong>{item.label}</strong>
                <span className="ml-1 text-muted-foreground">· {item.detail}</span>
              </span>
            </a>
          ))}
        </div>
      </aside>

      <nav className="sticky top-0 z-20 -mx-4 flex gap-1 overflow-x-auto border-y bg-background/95 px-4 py-2 backdrop-blur md:-mx-6 md:px-6" aria-label="Content settings sections">
        {[
          ["editorial-profiles", "Editorial profiles"],
          ["llm-providers", "LLM providers"],
          ["codex-connection", "Codex"],
          ["telegram-destinations", "Telegram"],
          ["prompt-governance", "Prompts"],
        ].map(([href, label]) => (
          <a
            key={href}
            className="min-h-10 shrink-0 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            href={`#${href}`}
          >
            {label}
          </a>
        ))}
      </nav>

      <EditorialProfilesSection profiles={profiles} />
      <LLMProvidersSection providers={llmProviders} />
      <CodexSection
        connections={connections.data ?? []}
        activity={activity.data ?? []}
        error={codexError ? getApiErrorMessage(codexError, "Codex settings could not be loaded.") : null}
        loading={codexPending}
        refreshing={codexRefreshing}
        onRetry={() => void Promise.all([connections.refetch(), activity.refetch()])}
      />
      <TelegramSection destinations={telegramDestinations} proxies={proxies.data ?? []} />
      <PromptGovernanceSection templates={promptTemplates} />
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
      <span
        className={`ml-auto size-2.5 shrink-0 rounded-full ${ready ? "bg-emerald-600" : "bg-slate-400"}`}
        aria-label={ready ? "Ready" : "Needs attention"}
      />
    </div>
  )
}
