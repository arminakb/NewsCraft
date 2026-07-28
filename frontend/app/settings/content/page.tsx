import type { Metadata } from "next"

import { ContentSettingsPage } from "@/features/settings/content-settings-page"

export const metadata: Metadata = {
  title: "Settings | NewsCraft",
}

export default function Page() {
  return <ContentSettingsPage />
}
