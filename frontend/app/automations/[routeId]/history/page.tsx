import { redirect } from "next/navigation"

export default async function AutomationHistoryPage({ params }: { params: Promise<{ routeId: string }> }) {
  const { routeId } = await params
  redirect(`/automations/runs?automationId=${encodeURIComponent(routeId)}`)
}
