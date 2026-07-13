import type {
  CitationRef,
  MediaAssignment,
  PlatformRevision,
} from "@/features/packages/types"

type TelegramRevision = Extract<PlatformRevision, { platform: "telegram" }>

export function PreviewDisclaimer({ platform }: { platform: string }) {
  return (
    <p role="note" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
      Approximation only — this {platform} preview is not pixel parity or live platform state.
    </p>
  )
}

export function PreviewCitations({
  citations,
  label,
}: {
  citations: CitationRef[]
  label: string
}) {
  return (
    <section aria-label={label} className="space-y-2">
      <h3 className="font-semibold">Citations</h3>
      {citations.length === 0 ? (
        <p className="text-sm text-muted-foreground">No citations are stored for this revision.</p>
      ) : (
        <ol className="space-y-2">
          {citations.map((citation, index) => (
            <li key={`${citation.evidenceSnapshotId}-${citation.locator}-${index}`}>
              <article aria-label={`Citation ${index + 1}`} className="min-w-0 rounded-md border p-3 text-sm">
                <dl className="grid min-w-0 gap-1 sm:grid-cols-[max-content_1fr]">
                  <dt className="font-medium">Evidence snapshot</dt>
                  <dd className="break-all">{citation.evidenceSnapshotId}</dd>
                  <dt className="font-medium">Evidence key</dt>
                  <dd className="break-all">{citation.evidenceKey}</dd>
                  <dt className="font-medium">Source</dt>
                  <dd className="min-w-0 break-all">
                    {citation.sourceUrl ? (
                      <a href={citation.sourceUrl} target="_blank" rel="noreferrer" className="text-primary underline">
                        {citation.sourceUrl}
                      </a>
                    ) : (
                      <span>Operator-provided evidence — no source link</span>
                    )}
                  </dd>
                  <dt className="font-medium">Locator</dt>
                  <dd className="break-all">{citation.locator}</dd>
                  <dt className="font-medium">Excerpt hash</dt>
                  <dd className="break-all font-mono text-xs">{citation.excerptSha256}</dd>
                </dl>
              </article>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

export function PreviewMediaAssignment({ assignment }: { assignment: MediaAssignment }) {
  return (
    <article aria-label={`Media assignment ${assignment.order}`} className="rounded-md border bg-muted/30 p-3 text-sm">
      <dl className="grid min-w-0 gap-1 sm:grid-cols-[max-content_1fr]">
        <dt className="font-medium">Asset</dt>
        <dd className="break-all">
          {assignment.mediaAssetId ? assignment.mediaAssetId : <strong className="text-amber-800">Manual media required</strong>}
        </dd>
        <dt className="font-medium">Role</dt>
        <dd>{assignment.role}</dd>
        <dt className="font-medium">Order</dt>
        <dd>{assignment.order}</dd>
        <dt className="font-medium">Alt text</dt>
        <dd className="whitespace-pre-wrap break-words" dir="auto">{assignment.altText}</dd>
        {assignment.manualBrief ? (
          <>
            <dt className="font-medium">Manual brief</dt>
            <dd className="whitespace-pre-wrap break-words" dir="auto">{assignment.manualBrief}</dd>
          </>
        ) : null}
        {assignment.imagePrompt ? (
          <>
            <dt className="font-medium">Image prompt</dt>
            <dd className="whitespace-pre-wrap break-words" dir="auto">{assignment.imagePrompt}</dd>
          </>
        ) : null}
      </dl>
    </article>
  )
}

export function PreviewChecklist({ items, label }: { items: string[]; label: string }) {
  return (
    <section aria-label={label} className="space-y-2">
      <h3 className="font-semibold">Manual checklist</h3>
      {items.length ? (
        <ul className="list-disc space-y-1 ps-5">
          {items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">No adjacent manual checklist items.</p>
      )}
    </section>
  )
}

export function TelegramPreview({ revision }: { revision: TelegramRevision }) {
  const { payload } = revision

  return (
    <section aria-label="Telegram preview" className="min-w-0 space-y-4 rounded-lg border p-4">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">Telegram preview</h2>
        <PreviewDisclaimer platform="Telegram" />
      </header>

      <section aria-label="Exact Telegram payload" className="min-w-0 space-y-3 rounded-md border bg-background p-3">
        <h3 className="font-semibold">Exact Telegram payload</h3>
        <pre dir={payload.direction} className="whitespace-pre-wrap break-words font-sans">{payload.body}</pre>
        <dl className="grid min-w-0 gap-1 text-sm sm:grid-cols-[max-content_1fr]">
          <dt className="font-medium">Parse mode</dt>
          <dd>{payload.parseMode}</dd>
          <dt className="font-medium">Direction</dt>
          <dd>{payload.direction}</dd>
          <dt className="font-medium">Source item</dt>
          <dd className="break-all">{payload.sourceItemId ?? "No source item ID in exact payload"}</dd>
          <dt className="font-medium">Source URL</dt>
          <dd className="break-all">
            {payload.sourceUrl ? <a href={payload.sourceUrl} target="_blank" rel="noreferrer" className="text-primary underline">{payload.sourceUrl}</a> : "No source URL in exact payload"}
          </dd>
          <dt className="font-medium">Media policy</dt>
          <dd>{payload.mediaPolicy}</dd>
          <dt className="font-medium">Dry run</dt>
          <dd>{payload.dryRun ? "Yes" : "No"}</dd>
        </dl>

        <section aria-label="Telegram buttons" className="space-y-1">
          <h4 className="font-medium">Buttons</h4>
          {payload.buttons.length ? (
            <ul className="space-y-1">
              {payload.buttons.map((button, index) => (
                <li key={`${index}-${button.url}`}>
                  <a href={button.url} target="_blank" rel="noreferrer" className="break-all text-primary underline">
                    {button.text}: {button.url}
                  </a>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-muted-foreground">No buttons in exact payload.</p>}
        </section>

        <section aria-label="Telegram media assignments" className="space-y-1">
          <h4 className="font-medium">Ordered media asset IDs</h4>
          {payload.mediaAssetIds.length ? (
            <ol className="list-decimal space-y-1 ps-5">
              {payload.mediaAssetIds.map((assetId) => <li key={assetId} className="break-all">{assetId}</li>)}
            </ol>
          ) : <p className="text-sm text-muted-foreground">No media asset IDs in exact payload.</p>}
          {payload.mediaPolicy === "replace_manually" ? <p role="status" className="font-medium text-amber-800">Manual media replacement is required.</p> : null}
        </section>
      </section>

      <PreviewCitations citations={revision.evidenceCitations} label="Telegram evidence citations" />
      <PreviewChecklist items={revision.manualChecklist} label="Telegram manual checklist" />
    </section>
  )
}
