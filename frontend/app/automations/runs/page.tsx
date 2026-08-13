import { Suspense } from "react"

import { LoadingState } from "@/components/ui/state-panel"
import { AutomationRunsPage } from "@/features/automations/automation-runs-page"

export default function Page() {
  return <Suspense fallback={<section className="nc-page"><LoadingState title="Loading runs…" /></section>}><AutomationRunsPage /></Suspense>
}
