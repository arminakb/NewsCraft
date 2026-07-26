import { Suspense } from "react"

import { InboxPage } from "@/features/inbox/inbox-page"

export default function Page() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground" role="status">Loading inbox…</div>}>
      <InboxPage />
    </Suspense>
  )
}
