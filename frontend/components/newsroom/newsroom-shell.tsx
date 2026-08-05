"use client"

import { useQuery } from "@tanstack/react-query"
import { useCallback, useRef, useState } from "react"

import { DateTimeProvider } from "@/components/providers/date-time-provider"
import { NotificationsSidebar } from "@/components/newsroom/notifications-sidebar"
import { getJobSummary } from "@/features/jobs/api"
import { queryKeys } from "@/lib/query-keys"
import { cn } from "@/lib/utils"

import { MobileNewsroomNav } from "./mobile-newsroom-nav"
import { NewsroomSidebar } from "./newsroom-sidebar"

export function NewsroomShell({
  children,
  settings,
}: {
  children: React.ReactNode
  settings?: React.ReactNode
}) {
  const [sidebarExpanded, setSidebarExpanded] = useState(false)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const notificationTriggerRef = useRef<HTMLButtonElement | null>(null)
  const summaryQuery = useQuery({
    queryKey: queryKeys.jobSummary,
    queryFn: getJobSummary,
  })
  const openNotifications = useCallback((trigger: HTMLButtonElement) => {
    notificationTriggerRef.current = trigger
    setNotificationsOpen(true)
  }, [])
  const changeNotificationsOpen = useCallback((open: boolean) => {
    setNotificationsOpen(open)
    if (open) return
    window.requestAnimationFrame(() => {
      const trigger = notificationTriggerRef.current
      if (!trigger?.isConnected) return
      trigger.focus()
    })
  }, [])

  return (
    <DateTimeProvider>
      <div
        className={cn(
          "newsroom-shell min-h-screen min-w-0 overflow-x-clip bg-background text-sm text-foreground min-[900px]:grid min-[900px]:h-screen min-[900px]:overflow-hidden min-[900px]:transition-[grid-template-columns] min-[900px]:duration-[180ms] min-[900px]:ease-out motion-reduce:min-[900px]:transition-none",
          sidebarExpanded
            ? "min-[900px]:grid-cols-[260px_minmax(0,1fr)]"
            : "min-[900px]:grid-cols-[72px_minmax(0,1fr)]",
        )}
        data-sidebar-state={sidebarExpanded ? "expanded" : "collapsed"}
      >
        <NewsroomSidebar
          expanded={sidebarExpanded}
          onExpandedChange={setSidebarExpanded}
          onNotificationsOpen={openNotifications}
          notificationsOpen={notificationsOpen}
          summary={summaryQuery.data}
        />
        <div data-testid="newsroom-content" className="newsroom-scroll min-w-0 overflow-x-clip bg-background min-[900px]:col-start-2 min-[900px]:row-start-1 min-[900px]:h-screen min-[900px]:overflow-y-auto">
          <main
            id="main-content"
            tabIndex={-1}
            className="min-w-0 pb-[calc(5rem+env(safe-area-inset-bottom))] min-[900px]:pb-0"
          >
            {children}
          </main>
        </div>
        <MobileNewsroomNav
          notificationsOpen={notificationsOpen}
          onNotificationsOpen={openNotifications}
        />
      </div>
      <NotificationsSidebar open={notificationsOpen} onOpenChange={changeNotificationsOpen} />
      {settings}
    </DateTimeProvider>
  )
}
