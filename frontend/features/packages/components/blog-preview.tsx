import type { PlatformRevision } from "@/features/packages/types"
import {
  PreviewChecklist,
  PreviewCitations,
  PreviewDisclaimer,
  PreviewMediaAssignment,
} from "@/features/packages/components/telegram-preview"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"

type BlogRevision = Extract<PlatformRevision, { platform: "blog" }>

export function BlogPreview({ revision }: { revision: BlogRevision }) {
  const { payload } = revision

  return (
    <section aria-label="Blog preview" className="min-w-0 space-y-4 rounded-lg border p-4">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">Blog preview</h2>
        <PreviewDisclaimer platform="blog" />
      </header>

      <article className="space-y-3 rounded-md border bg-background p-3">
        <DirectionBoundary as="h3" language={null} className="text-xl font-semibold">{payload.title}</DirectionBoundary>
        <p className="break-all text-sm text-muted-foreground">Slug: {payload.slug}</p>
        <DirectionBoundary as="p" language={null} className="font-medium">{payload.excerpt}</DirectionBoundary>
        <DirectionBoundary as="pre" language={null} className="whitespace-pre-wrap break-words font-sans">{payload.bodyMarkdown}</DirectionBoundary>
      </article>

      <section aria-label="Blog headings" className="space-y-2">
        <h3 className="font-semibold">Declared heading order</h3>
        <ol className="list-decimal space-y-1 ps-5">
          {payload.headings.map((heading, index) => <DirectionBoundary as="li" language={null} key={`${index}-${heading}`}>{heading}</DirectionBoundary>)}
        </ol>
      </section>

      <section aria-label="Blog metadata" className="space-y-2">
        <h3 className="font-semibold">Metadata</h3>
        <p><span className="font-medium">SEO description:</span> <DirectionBoundary as="span" language={null}>{payload.seoDescription}</DirectionBoundary></p>
        <p><span className="font-medium">Tags:</span> <DirectionBoundary as="span" language={null}>{payload.tags.join(", ") || "No tags"}</DirectionBoundary></p>
        <div>
          <h4 className="font-medium">Canonical sources</h4>
          {payload.canonicalSources.length ? (
            <ol className="list-decimal space-y-1 ps-5">
              {payload.canonicalSources.map((source) => (
                <li key={source} className="break-all">
                  <a href={source} target="_blank" rel="noreferrer" className="text-primary underline">{source}</a>
                </li>
              ))}
            </ol>
          ) : <p className="text-sm text-muted-foreground">No canonical source URLs are stored.</p>}
        </div>
      </section>

      <section aria-label="Blog hero media" className="space-y-2">
        <h3 className="font-semibold">Hero media</h3>
        {payload.heroMedia ? <PreviewMediaAssignment assignment={payload.heroMedia} /> : <p className="text-sm text-muted-foreground">No hero media assignment is stored.</p>}
      </section>

      <PreviewCitations citations={payload.citations} label="Blog citations" />
      <PreviewChecklist items={revision.manualChecklist} label="Blog manual checklist" />
    </section>
  )
}
