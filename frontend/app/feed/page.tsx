import { Suspense } from "react"

import { ArticlesPage } from "@/features/articles/articles-page"

export default function Page() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground" role="status">Loading library…</div>}>
      <ArticlesPage />
    </Suspense>
  )
}
