import { Suspense } from "react"

import { LoadingState } from "@/components/ui/state-panel"
import { OperationsCenter } from "@/features/operations/operations-center"

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const query = await searchParams
  return (
    <Suspense fallback={<LoadingState aria-label="Loading Operations Center" className="m-4" title="Loading Operations Center…" />}>
      <OperationsCenter
        initialQuery={{
          view: first(query.view),
          status: first(query.status),
          job: first(query.job),
          type: first(query.type),
          range: first(query.range),
          search: first(query.search),
          failed: first(query.failed),
        }}
      />
    </Suspense>
  )
}

function first(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] ?? null : value ?? null
}
