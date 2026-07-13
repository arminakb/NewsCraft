import Link from "next/link"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { HistoryTimeline } from "@/features/operations/history-timeline"

export default async function AutomationHistoryPage({ params }: { params: Promise<{ routeId: string }> }) {
  const { routeId } = await params

  return (
    <OperationsPageFrame
      actions={
        <Link
          className="inline-flex min-h-9 items-center rounded-lg border bg-background px-3 text-sm font-medium hover:bg-muted"
          href={`/automations/${routeId}`}
        >
          Back to route
        </Link>
      }
      subtitle="Review cursor-paginated events derived from durable workflow records."
      title="Automation history"
    >
      <HistoryTimeline routeId={routeId} />
    </OperationsPageFrame>
  )
}
