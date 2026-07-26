"use client"

import { useQuery } from "@tanstack/react-query"
import type { TelegramDispatch } from "@/features/automations/telegram-types"
import {
  getResearchRuns,
  getStoryCompleteness,
} from "@/features/editorial/api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function DispatchResearchOutcome({ dispatch, researchMode }: { dispatch: TelegramDispatch; researchMode: "off" | "manual" | "auto_if_incomplete" }) {
  const completeness = useQuery({ queryKey: queryKeys.story(dispatch.storyId), queryFn: () => getStoryCompleteness(dispatch.storyId), enabled: Boolean(dispatch.storyId) })
  const runs = useQuery({ queryKey: queryKeys.researchRuns(dispatch.storyId), queryFn: () => getResearchRuns(dispatch.storyId), enabled: Boolean(dispatch.storyId) && researchMode !== "off" })
  if (!dispatch.storyId) return <div role="status">Story identity unavailable</div>
  if (completeness.isPending || (researchMode !== "off" && runs.isPending)) return <div role="status">Loading research truth…</div>
  if (completeness.isError || runs.isError) return <div role="alert">{getApiErrorMessage(completeness.error ?? runs.error, "Research truth unavailable")}</div>
  const latest = runs.data?.[0] ?? null
  const failedAuto = researchMode === "auto_if_incomplete" && (dispatch.status === "needs_review" || dispatch.errorCode?.includes("research"))
  return <div className="space-y-1 text-xs"><div>Completeness {completeness.data?.score ?? 0}% · {completeness.data?.complete ? "complete" : "incomplete"}</div>{latest ? <><div>Research {latest.status} · run {latest.id}</div><div>{latest.provider ? `${latest.provider.name} · ${latest.provider.providerType}` : "Provider identity unavailable"}</div></> : researchMode === "off" ? <div>Research off</div> : <div>No research run yet</div>}{failedAuto ? <strong className="text-amber-800">Review required</strong> : null}</div>
}
