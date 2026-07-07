import { SourcesPage } from "@/components/dashboard/pages/sources-page"
import { dashboardMock } from "@/lib/mock-data"

export default function Page() {
  return <SourcesPage initialSources={dashboardMock.sources} />
}
