import { DashboardShell } from "@/components/dashboard/dashboard-shell"
import { dashboardMock } from "@/lib/mock-data"

export default function Page() {
  return <DashboardShell initialData={dashboardMock} />
}
