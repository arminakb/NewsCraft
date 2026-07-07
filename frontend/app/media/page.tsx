import { MediaAssetsPage } from "@/components/dashboard/pages/media-assets-page"
import { dashboardMock } from "@/lib/mock-data"

export default function Page() {
  return <MediaAssetsPage initialMedia={dashboardMock.media} />
}
