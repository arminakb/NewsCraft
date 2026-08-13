import { Suspense } from "react"

import { SettingsModal } from "@/features/settings/settings-modal"

export default function SettingsModalRoute() {
  return (
    <Suspense fallback={null}>
      <SettingsModal />
    </Suspense>
  )
}
