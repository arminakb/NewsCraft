"use client"

import { useQuery } from "@tanstack/react-query"

import { AppSidebar } from "@/components/dashboard/app-sidebar"
import { getDashboardSummary } from "@/lib/api-client"
import { emptyDashboardCounts } from "@/lib/empty-data"
import { queryKeys } from "@/lib/query-keys"

export function OperationsPageFrame({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string
  subtitle: string
  actions?: React.ReactNode
  children: React.ReactNode
}) {
  const countsQuery = useQuery({
    queryKey: queryKeys.dashboardSummary,
    queryFn: getDashboardSummary,
    initialData: emptyDashboardCounts,
    enabled: process.env.NODE_ENV !== "test",
  })

  return (
    <div className="min-h-screen bg-slate-50 text-sm text-foreground">
      <div className="grid min-h-screen grid-cols-1 md:grid-cols-[240px_minmax(0,1fr)]">
        <AppSidebar counts={countsQuery.data} />
        <main className="min-w-0 bg-white">
          <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
            <div>
              <h1 className="text-lg font-semibold">{title}</h1>
              <p className="text-sm text-muted-foreground">{subtitle}</p>
            </div>
            {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
          </header>
          <div className="space-y-4 p-4">{children}</div>
        </main>
      </div>
    </div>
  )
}
