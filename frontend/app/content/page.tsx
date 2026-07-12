import { ContentItemsPage } from "@/components/dashboard/pages/content-items-page"
import { emptyDashboardSnapshot } from "@/lib/empty-data"

export default function Page() {
  return <ContentItemsPage initialItems={emptyDashboardSnapshot.queue} />
}
