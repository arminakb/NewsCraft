import { ContentItemsPage } from "@/components/dashboard/pages/content-items-page"
import { dashboardMock } from "@/lib/mock-data"

export default function Page() {
  return <ContentItemsPage initialItems={dashboardMock.queue} />
}
