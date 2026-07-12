import { MediaAssetsPage } from "@/components/dashboard/pages/media-assets-page"
import { emptyDashboardSnapshot } from "@/lib/empty-data"

export default function Page() {
  return <MediaAssetsPage initialMedia={emptyDashboardSnapshot.media} />
}
