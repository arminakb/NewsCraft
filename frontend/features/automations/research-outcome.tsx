"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { getTelegramDispatches } from "@/features/automations/telegram-api"
import type { TelegramDispatch } from "@/features/automations/telegram-types"
import { getResearchRuns, getStory } from "@/lib/editorial-api"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function DispatchResearchOutcome({ dispatch, researchMode }: { dispatch: TelegramDispatch; researchMode: "off" | "manual" | "auto_if_incomplete" }) {
  const story = useQuery({ queryKey: queryKeys.story(dispatch.storyId), queryFn: () => getStory(dispatch.storyId), enabled: Boolean(dispatch.storyId) })
  const runs = useQuery({ queryKey: queryKeys.researchRuns(dispatch.storyId), queryFn: () => getResearchRuns(dispatch.storyId), enabled: Boolean(dispatch.storyId) && researchMode !== "off" })
  if (!dispatch.storyId) return <div role="status">Story identity unavailable</div>
  if (story.isPending || (researchMode !== "off" && runs.isPending)) return <div role="status">Loading research truth…</div>
  if (story.isError || runs.isError) return <div role="alert">{getApiErrorMessage(story.error ?? runs.error, "Research truth unavailable")}</div>
  const latest = runs.data?.[0] ?? null
  const failedAuto = researchMode === "auto_if_incomplete" && (dispatch.status === "needs_review" || dispatch.errorCode?.includes("research"))
  return <div className="space-y-1 text-xs"><div>Completeness {story.data?.completeness.score ?? 0}% · {story.data?.completeness.complete ? "complete" : "incomplete"}</div>{latest ? <><div>Research {latest.status} · run {latest.id}</div><div>{latest.provider ? `${latest.provider.name} · ${latest.provider.providerType}` : "Provider identity unavailable"}</div></> : researchMode === "off" ? <div>Research off</div> : <div>No research run yet</div>}{failedAuto ? <strong className="text-amber-800">Review required</strong> : null}{researchMode === "manual" && !latest?.resultStoryRevisionId ? <Link className="block text-primary underline" href={`/inbox?story_id=${dispatch.storyId}`}>Research more</Link> : null}{latest?.status === "succeeded" && latest.resultStoryRevisionId ? <Link className="block text-primary underline" href={`/inbox?story_id=${dispatch.storyId}&research_run_id=${latest.id}`}>Regenerate from research result</Link> : null}</div>
}

export function ReviewResearchOutcome({ routeId, dispatchId, researchMode }: { routeId: string; dispatchId: string; researchMode: "off" | "manual" | "auto_if_incomplete" }) {
  const dispatches = useQuery({ queryKey: queryKeys.telegramDispatches(routeId), queryFn: () => getTelegramDispatches(routeId) })
  if (dispatches.isPending) return <div role="status">Loading dispatch research outcome…</div>
  if (dispatches.isError) return <div role="alert">{getApiErrorMessage(dispatches.error)}</div>
  const dispatch = dispatches.data.find((item) => item.id === dispatchId)
  return dispatch ? <DispatchResearchOutcome dispatch={dispatch} researchMode={researchMode} /> : <div role="alert">Dispatch research outcome unavailable</div>
}
