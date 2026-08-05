import { Suspense } from "react"

import { LoadingState } from "@/components/ui/state-panel"
import { NewWorkflowPage } from "@/features/automations/new-workflow-page"

export default function Page() {
  return (
    <Suspense fallback={<section className="nc-page"><LoadingState title="Creating blank workflow…" /></section>}>
      <NewWorkflowPage />
    </Suspense>
  )
}
