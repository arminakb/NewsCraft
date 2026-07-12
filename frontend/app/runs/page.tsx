import { RunsPage } from "@/components/dashboard/pages/runs-page"
import { emptyDashboardSnapshot } from "@/lib/empty-data"

export default function Page() {
  return <RunsPage initialRuns={emptyDashboardSnapshot.runs} />
}
