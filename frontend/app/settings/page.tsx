import type { Metadata } from "next"
import { Suspense } from "react"

import { SettingsModal } from "@/features/settings/settings-modal"
import { SettingsRouteBackground } from "@/features/settings/settings-route"

export const metadata: Metadata = {
  title: "Settings | NewsCraft",
}

export default function SettingsPage() {
  return (
    <>
      <SettingsRouteBackground />
      <Suspense fallback={null}>
        <SettingsModal />
      </Suspense>
    </>
  )
}
