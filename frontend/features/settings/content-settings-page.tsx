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
  Trash2,
  UserRound,
} from "lucide-react"
import { useCallback, useEffect, useRef } from "react"
import type { MouseEvent } from "react"

import { Button } from "@/components/ui/button"
import { PageHeader } from "@/components/ui/page-header"
import { ErrorState } from "@/components/ui/state-panel"
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
import { RetentionSection } from "./retention-section"
import { TelegramSection } from "./telegram-section"

const settingsShortcuts = [
  { id: "editorial-profiles", label: "Editorial profiles", icon: null },
  { id: "llm-providers", label: "LLM providers", icon: null },
  { id: "codex-connection", label: "Codex", icon: null },
  { id: "telegram-destinations", label: "Telegram", icon: null },
  { id: "prompt-governance", label: "Prompts", icon: null },
  { id: "retention", label: "Retention", icon: Trash2 },
] as const

export function ContentSettingsPage() {
  const brands = useQuery({ queryKey: queryKeys.brandProfiles, queryFn: getBrandProfiles })
  const templates = useQuery({ queryKey: queryKeys.promptTemplates, queryFn: getPromptTemplates })
  const providers = useQuery({ queryKey: queryKeys.llmProviders, queryFn: getLLMProviders })
  const destinations = useQuery({
    queryKey: queryKeys.telegramDestinations,
    queryFn: getTelegramDestinations,
    refetchInterval: (query) => query.state.data?.some((item) =>
      [item.health_status, item.proxy_health_status, item.telegram_health_status].includes("checking")
    ) ? 3_000 : false,
  })
  const proxies = useQuery({
    queryKey: queryKeys.telegramProxies,
    queryFn: getTelegramProxies,
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.reachability_status === "checking") ? 3_000 : false,
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
  const settingsReady = !requiredQueries.some((query) => query.isPending || query.isError)
  const handleShortcutClick = useSettingsSectionNavigation(settingsReady)

  if (requiredQueries.some((query) => query.isPending)) return <SettingsSkeleton />
  const failed = requiredQueries.filter((query) => query.isError)
  if (failed.length) {
    return (
      <section className="nc-page">
        <ErrorState
          dir="auto"
          title="Settings unavailable"
          description={getApiErrorMessage(failed[0].error, "Settings could not be loaded.")}
          action={
            <Button
              variant="outline"
              onClick={() => void Promise.all(requiredQueries.map((query) => query.refetch()))}
            >
              <RefreshCw aria-hidden="true" /> Retry settings
            </Button>
          }
        />
      </section>
    )
  }

  const profiles = brands.data ?? []
  const llmProviders = providers.data ?? []
  const telegramDestinations = destinations.data ?? []
  const promptTemplates = templates.data ?? []
  const enabledProviders = llmProviders.filter((item) => item.enabled)
  const healthyDestinations = telegramDestinations.filter((item) => item.health_status === "healthy")
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
      ready: profiles.some((item) => item.is_default),
      detail: profiles.some((item) => item.is_default) ? "Default selected" : "Choose a default profile",
    },
    {
      href: "#llm-providers",
      label: "LLM provider",
      ready: enabledProviders.some((item) => item.generation_ready),
      detail: enabledProviders.some((item) => item.generation_ready)
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
    <section className="nc-page gap-6" aria-labelledby="content-settings-heading">
      <PageHeader
        title="Settings"
        titleId="content-settings-heading"
        contentClassName="max-w-3xl"
        description={<>Manage editorial behavior, model connections, Codex access, publishing destinations, and prompt history. Secrets stay write-only.</>}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Content readiness summary">
        <SummaryCard
          icon={BrainCircuit}
          label="LLM providers"
          value={`${enabledProviders.length} enabled`}
          ready={enabledProviders.some((item) => item.generation_ready)}
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

      <aside className="nc-panel p-4" aria-labelledby="setup-checklist-heading">
        <div className="flex items-center gap-2">
          <UserRound className="size-5 text-primary" aria-hidden="true" />
          <h2 id="setup-checklist-heading" className="font-semibold">Setup checklist</h2>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {setup.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="flex min-h-11 items-center gap-3 rounded-lg border px-3 py-2 text-sm transition-colors duration-200 hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
              onClick={handleShortcutClick}
            >
              {item.ready
                ? <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden="true" />
                : <CircleAlert className="size-4 shrink-0 text-warning" aria-hidden="true" />}
              <span>
                <strong>{item.label}</strong>
                <span className="ml-1 text-muted-foreground">· {item.detail}</span>
              </span>
            </a>
          ))}
        </div>
      </aside>

      <nav className="sticky top-0 z-20 -mx-4 flex gap-1 overflow-x-auto border-y bg-background/95 px-4 py-2 backdrop-blur md:-mx-6 md:px-6" aria-label="Settings sections">
        {settingsShortcuts.map(({ id, label, icon: Icon }) => (
          <a
            key={id}
            className="flex min-h-11 shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors duration-200 hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            href={`#${id}`}
            onClick={handleShortcutClick}
          >
            {Icon ? <Icon className="size-4" aria-hidden="true" /> : null}
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
      <RetentionSection />
    </section>
  )
}

function useSettingsSectionNavigation(ready: boolean) {
  const activeTarget = useRef<string | null>(null)
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingFrame = useRef<number | null>(null)

  const navigateToSection = useCallback((sectionId: string, updateHash: boolean) => {
    const target = document.getElementById(sectionId)
    if (!target) return

    if (updateHash) {
      const url = new URL(window.location.href)
      url.hash = sectionId
      window.history.replaceState(window.history.state, "", url)
    }

    target.focus({ preventScroll: true })
    if (activeTarget.current === sectionId) return

    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false
    target.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "start",
    })

    activeTarget.current = sectionId
    if (resetTimer.current !== null) clearTimeout(resetTimer.current)
    resetTimer.current = setTimeout(() => {
      activeTarget.current = null
      resetTimer.current = null
    }, reducedMotion ? 0 : 300)
  }, [])

  const handleShortcutClick = useCallback((event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    const sectionId = event.currentTarget.hash.slice(1)
    if (!sectionId) return
    navigateToSection(sectionId, true)
  }, [navigateToSection])

  useEffect(() => {
    if (!ready || !window.location.hash) return
    const sectionId = decodeURIComponent(window.location.hash.slice(1))
    if (!settingsShortcuts.some((shortcut) => shortcut.id === sectionId)) return

    pendingFrame.current = requestAnimationFrame(() => {
      pendingFrame.current = null
      navigateToSection(sectionId, false)
    })
  }, [navigateToSection, ready])

  useEffect(() => () => {
    if (pendingFrame.current !== null) cancelAnimationFrame(pendingFrame.current)
    if (resetTimer.current !== null) clearTimeout(resetTimer.current)
  }, [])

  return handleShortcutClick
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
    <div className="nc-panel flex items-center gap-3 p-4">
      <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-muted text-primary">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        <div className="truncate font-semibold">{value}</div>
      </div>
      <span
        className={`ml-auto size-2.5 shrink-0 rounded-full ${ready ? "bg-success" : "bg-muted-foreground"}`}
        aria-label={ready ? "Ready" : "Needs attention"}
        role="img"
      />
    </div>
  )
}
