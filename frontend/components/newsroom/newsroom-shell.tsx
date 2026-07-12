"use client"

import { useQuery } from "@tanstack/react-query"

import { getAutomationControl } from "@/features/control/api"
import { getJobSummary } from "@/features/jobs/api"
import { queryKeys } from "@/lib/query-keys"

import { MobileNewsroomNav } from "./mobile-newsroom-nav"
import { NewsroomHeader, type ControlDisplayState } from "./newsroom-header"
import { NewsroomSidebar } from "./newsroom-sidebar"

export function NewsroomShell({ children }: { children: React.ReactNode }) {
  const controlQuery = useQuery({
    queryKey: queryKeys.automationControl,
    queryFn: getAutomationControl,
  })
  const summaryQuery = useQuery({
    queryKey: queryKeys.jobSummary,
    queryFn: getJobSummary,
  })

  const controlState: ControlDisplayState = controlQuery.error
    ? "unavailable"
    : !controlQuery.data
      ? "checking"
      : controlQuery.data.globalPause
        ? "paused"
        : "active"

  return (
    <div className="min-h-screen min-w-0 bg-slate-50 text-sm text-foreground md:grid md:grid-cols-[248px_minmax(0,1fr)]">
      <NewsroomSidebar summary={summaryQuery.data} />
      <div data-testid="newsroom-content" className="min-w-0 overflow-x-clip bg-white">
        <NewsroomHeader controlState={controlState} />
        <main id="main-content" className="min-w-0 pb-20 md:pb-0">
          {children}
        </main>
      </div>
      <MobileNewsroomNav />
    </div>
  )
}
