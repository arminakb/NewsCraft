import { RunsPage } from "@/components/dashboard/pages/runs-page"
import { dashboardMock } from "@/lib/mock-data"

export default function Page() {
  return <RunsPage initialRuns={dashboardMock.runs} />
}
