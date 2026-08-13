import { AutomationBuilder } from "@/features/automations/automation-builder"

export default async function Page({ params }: { params: Promise<{ routeId: string }> }) {
  const { routeId } = await params
  return <AutomationBuilder automationId={routeId} />
}
