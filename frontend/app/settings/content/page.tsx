import type { Metadata } from "next"

import { LegacySettingsRoute } from "@/features/settings/settings-route"

export const metadata: Metadata = {
  title: "Settings | NewsCraft",
}

export default function Page() {
  return <LegacySettingsRoute />
}
