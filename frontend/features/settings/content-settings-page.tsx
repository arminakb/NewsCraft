"use client"

import { useQuery } from "@tanstack/react-query"
import { RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorState } from "@/components/ui/state-panel"
import { getPromptTemplates } from "@/features/automations/telegram-api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

import { CodexSection } from "./codex-section"
import { SettingsPanel } from "./content-settings-primitives"
import {
  getCodexActivity,
  getCodexConnections,
  getLLMProviders,
  getTelegramDestinations,
  getTelegramProxies,
} from "./content-settings-api"
import { DateTimeSection } from "./date-time-section"
import { LLMProvidersSection } from "./llm-providers-section"
import { PromptGovernanceSection } from "./prompt-governance-section"
import { RetentionSection } from "./retention-section"
import {
  defaultSettingsSection,
  type SettingsSectionId,
} from "./settings-sections"
import { TelegramSection } from "./telegram-section"

export function ContentSettingsPage({
  section = defaultSettingsSection.id,
}: {
  section?: SettingsSectionId
}) {
  const templates = useQuery({
    queryKey: queryKeys.promptTemplates,
    queryFn: getPromptTemplates,
    enabled: section === "prompts",
  })
  const providers = useQuery({
    queryKey: queryKeys.llmProviders,
    queryFn: getLLMProviders,
    enabled: section === "llm-providers",
  })
  const destinations = useQuery({
    queryKey: queryKeys.telegramDestinations,
    queryFn: getTelegramDestinations,
    enabled: section === "telegram",
    refetchInterval: (query) => query.state.data?.some((item) =>
      [item.health_status, item.proxy_health_status, item.telegram_health_status].includes("checking")
    ) ? 3_000 : false,
  })
  const proxies = useQuery({
    queryKey: queryKeys.telegramProxies,
    queryFn: getTelegramProxies,
    enabled: section === "telegram",
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.reachability_status === "checking") ? 3_000 : false,
  })
  const connections = useQuery({
    queryKey: queryKeys.codexConnections,
    queryFn: getCodexConnections,
    enabled: section === "codex",
    refetchInterval: (query) => query.state.error ? false : 20_000,
  })
  const activity = useQuery({
    queryKey: queryKeys.codexActivity,
    queryFn: () => getCodexActivity(),
    enabled: section === "codex",
    refetchInterval: (query) => query.state.error ? false : 20_000,
  })

  const selectedQueries = section === "llm-providers"
    ? [providers]
    : section === "telegram"
      ? [destinations, proxies]
      : section === "prompts"
        ? [templates]
        : []
  const pending = selectedQueries.some((query) => query.isPending)
  const failed = selectedQueries.find((query) => query.isError)

  if (pending) return <SettingsPanelSkeleton />
  if (failed) {
    return (
      <div className="p-4 min-[700px]:p-7">
        <ErrorState
          dir="auto"
          title="Settings unavailable"
          description={getApiErrorMessage(failed.error, "Settings could not be loaded.")}
          action={
            <Button
              onClick={() => void Promise.all(selectedQueries.map((query) => query.refetch()))}
              variant="outline"
            >
              <RefreshCw aria-hidden="true" /> Retry settings
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <SettingsPanel>
      {section === "llm-providers" ? (
        <LLMProvidersSection providers={providers.data ?? []} />
      ) : null}
      {section === "codex" ? (
        <CodexSection
          connections={connections.data ?? []}
          activity={activity.data ?? []}
          error={connections.error || activity.error
            ? getApiErrorMessage(
              connections.error ?? activity.error,
              "Codex settings could not be loaded.",
            )
            : null}
          loading={connections.isPending || activity.isPending}
          refreshing={connections.isFetching || activity.isFetching}
          onRetry={() => void Promise.all([connections.refetch(), activity.refetch()])}
        />
      ) : null}
      {section === "telegram" ? (
        <TelegramSection destinations={destinations.data ?? []} proxies={proxies.data ?? []} />
      ) : null}
      {section === "date-time" ? <DateTimeSection /> : null}
      {section === "retention" ? <RetentionSection /> : null}
      {section === "prompts" ? (
        <PromptGovernanceSection templates={templates.data ?? []} />
      ) : null}
    </SettingsPanel>
  )
}

function SettingsPanelSkeleton() {
  return (
    <div
      aria-label="Loading selected Settings category"
      className="space-y-4 p-4 min-[700px]:p-7"
      role="status"
    >
      <Skeleton className="h-11 w-40" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-64 w-full" />
      <span className="sr-only">Loading Settings category…</span>
    </div>
  )
}
