import type { PlatformRevision } from "@/features/packages/types"
import {
  PreviewChecklist,
  PreviewCitations,
  PreviewDisclaimer,
  PreviewMediaAssignment,
} from "@/features/packages/components/telegram-preview"

type XRevision = Extract<PlatformRevision, { platform: "x" }>

export function XPreview({ revision }: { revision: XRevision }) {
  const { payload } = revision
  const posts = [...payload.posts].sort((left, right) => left.order - right.order)

  return (
    <section aria-label="X thread preview" className="min-w-0 space-y-4 rounded-lg border p-4">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">X {payload.mode === "thread" ? "thread" : "post"} preview</h2>
        <PreviewDisclaimer platform="X" />
      </header>

      <p className="text-sm"><span className="font-medium">Link strategy:</span> {payload.linkStrategy.replaceAll("_", " ")}</p>
      <ol className="space-y-3">
        {posts.map((post) => {
          const media = [...post.media].sort((left, right) => left.order - right.order)
          return (
            <li key={`${post.order}-${post.text}`}>
              <article aria-label={`X post ${post.order}`} className="space-y-3 rounded-md border bg-background p-3">
                <h3 className="font-semibold">Post {post.order} of {posts.length}</h3>
                <p className="whitespace-pre-wrap break-words" dir="auto">{post.text}</p>
                {media.length ? (
                  <div className="space-y-2" aria-label={`Media for X post ${post.order}`}>
                    {media.map((assignment, index) => <PreviewMediaAssignment key={`${assignment.order}-${assignment.mediaAssetId ?? "manual"}-${index}`} assignment={assignment} />)}
                  </div>
                ) : <p className="text-sm text-muted-foreground">No media assigned to this post.</p>}
                <PreviewCitations citations={post.citations} label={`Citations for X post ${post.order}`} />
              </article>
            </li>
          )
        })}
      </ol>
      <PreviewChecklist items={revision.manualChecklist} label="X manual checklist" />
    </section>
  )
}
