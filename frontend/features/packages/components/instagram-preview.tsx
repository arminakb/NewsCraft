import type { PlatformRevision } from "@/features/packages/types"
import {
  PreviewChecklist,
  PreviewCitations,
  PreviewDisclaimer,
  PreviewMediaAssignment,
} from "@/features/packages/components/telegram-preview"

type InstagramRevision = Extract<PlatformRevision, { platform: "instagram" }>

export function InstagramPreview({ revision }: { revision: InstagramRevision }) {
  const { payload } = revision
  const slides = [...payload.carousel].sort((left, right) => left.order - right.order)

  return (
    <section aria-label="Instagram preview" className="min-w-0 space-y-4 rounded-lg border p-4">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">Instagram preview</h2>
        <PreviewDisclaimer platform="Instagram" />
      </header>

      <div className="space-y-2 rounded-md border bg-background p-3">
        <p className="font-semibold" dir="auto">{payload.hook}</p>
        <p className="whitespace-pre-wrap break-words" dir="auto">{payload.caption}</p>
        <p dir="auto"><span className="font-medium">Call to action:</span> {payload.cta}</p>
        <p className="break-words" dir="auto">{payload.hashtags.join(" ")}</p>
        <p className="text-sm" dir="auto"><span className="font-medium">Package alt text:</span> {payload.altText}</p>
      </div>

      <section aria-label="Instagram carousel" className="space-y-3">
        <h3 className="font-semibold">Carousel</h3>
        {slides.length ? (
          <ol className="space-y-3">
            {slides.map((slide) => (
              <li key={`${slide.order}-${slide.headline}`}>
                <article aria-label={`Carousel slide ${slide.order}`} className="space-y-2 rounded-md border p-3">
                  <h4 className="font-semibold">Slide {slide.order}: {slide.headline}</h4>
                  <p className="whitespace-pre-wrap break-words" dir="auto">{slide.body}</p>
                  <PreviewMediaAssignment assignment={slide.media} />
                </article>
              </li>
            ))}
          </ol>
        ) : <p className="text-sm text-muted-foreground">This revision contains no carousel slides.</p>}
      </section>

      <PreviewCitations citations={payload.citations} label="Instagram citations" />
      <PreviewChecklist items={revision.manualChecklist} label="Instagram manual checklist" />
    </section>
  )
}
