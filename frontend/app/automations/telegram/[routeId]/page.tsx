import { RouteDetail } from "@/features/automations/route-detail"

export default async function Page({ params }: { params: Promise<{ routeId: string }> }) {
  const { routeId } = await params
  return <RouteDetail routeId={routeId} />
}
