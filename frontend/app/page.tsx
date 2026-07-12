import { DashboardShell } from "@/components/dashboard/dashboard-shell"
import { emptyDashboardSnapshot } from "@/lib/empty-data"

export default function Page() {
  return <DashboardShell initialData={emptyDashboardSnapshot} />
}
