import { SourcesPage } from "@/components/dashboard/pages/sources-page"
import { emptyDashboardSnapshot } from "@/lib/empty-data"

export default function Page() {
  return <SourcesPage initialSources={emptyDashboardSnapshot.sources} />
}
