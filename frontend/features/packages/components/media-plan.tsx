"use client"

import type { PlatformRevision, SourceMedia } from "@/features/packages/types"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"

type RevisionFor<P extends PlatformRevision["platform"]> = Extract<PlatformRevision, { platform: P }>
type PayloadFor<P extends PlatformRevision["platform"]> = RevisionFor<P>["payload"]

export type MediaPlanProps = {
  revision: PlatformRevision
  onReorder?: (payload: PlatformRevision["payload"]) => void
}

export function MediaPlan({ revision, onReorder }: MediaPlanProps) {
  const assets = [...revision.sourceMedia].sort((left, right) => left.order - right.order || left.id.localeCompare(right.id))
  return (
    <section aria-labelledby="media-plan-heading" className="space-y-4">
      <div>
        <h2 id="media-plan-heading" className="text-lg font-semibold">Media plan</h2>
        <p className="text-sm text-muted-foreground">Source assets and publish-order assignments for this exact revision.</p>
      </div>
      <section aria-labelledby="source-assets-heading" className="space-y-2">
        <h3 id="source-assets-heading" className="font-medium">Ordered source assets</h3>
        {assets.length ? (
          <ol className="space-y-2">
            {assets.map((asset, index) => <SourceAssetRow key={asset.id} asset={asset} position={index + 1} />)}
          </ol>
        ) : <p className="text-sm text-warning">No source assets are available for this revision.</p>}
      </section>
      <section aria-labelledby="assignments-heading" className="space-y-2">
        <h3 id="assignments-heading" className="font-medium">Assignments</h3>
        <AssignmentList revision={revision} onReorder={onReorder} />
      </section>
    </section>
  )
}

function SourceAssetRow({ asset, position }: { asset: SourceMedia; position: number }) {
  return (
    <li aria-label={`Source asset ${position}`} className="rounded-lg border p-3 text-sm">
      <div className="font-medium">{position}. {asset.id}</div>
      <div>{asset.kind} · {asset.mimeType}</div>
      <div>{dimensions(asset)} · {bytes(asset.byteLength)}</div>
      {asset.durationSeconds !== null ? <div>Duration: {asset.durationSeconds} seconds</div> : null}
      <div className={asset.available ? "text-success" : "text-destructive"}>
        {asset.available ? "Available" : "Unavailable"} · {asset.fetchStatus}
      </div>
    </li>
  )
}

function AssignmentList({ revision, onReorder }: MediaPlanProps) {
  switch (revision.platform) {
    case "telegram":
      return <TelegramAssignments revision={revision} onReorder={onReorder} />
    case "instagram":
      return <InstagramAssignments revision={revision} onReorder={onReorder} />
    case "x":
      return <XAssignments revision={revision} onReorder={onReorder} />
    case "blog":
      return <BlogAssignments revision={revision} />
    default:
      return assertNever(revision)
  }
}

function TelegramAssignments({ revision, onReorder }: { revision: RevisionFor<"telegram">; onReorder?: MediaPlanProps["onReorder"] }) {
  const ids = revision.payload.mediaAssetIds
  if (revision.payload.mediaPolicy === "replace_manually") {
    return <RequiredManualAsset message="Telegram media must be supplied manually before publishing." />
  }
  if (revision.payload.mediaPolicy === "omit") {
    return <p className="text-sm text-muted-foreground">Telegram media is omitted by policy; this is an intentional message-only publish.</p>
  }
  if (!ids.length) {
    return <p className="text-sm text-muted-foreground">No Telegram media is assigned; this is an intentional message-only publish.</p>
  }
  const assigned = ids.map((id) => revision.sourceMedia.find((item) => item.id === id))
  const categories = new Set(assigned.map(telegramAssetCategory).filter((value) => value !== null))
  const mixedDocumentsAndVisuals = categories.has("document") && categories.has("visual")
  return (
    <div className="space-y-2">
      {mixedDocumentsAndVisuals ? <RequiredManualAsset message="Mixed Telegram documents and visual media require manual review." /> : null}
      <ol className="space-y-2">
        {ids.map((id, index) => {
          const problem = sourceAssetProblem("telegram", assigned[index])
          return (
            <li key={`${id}:${index}`} aria-label={`Media assignment Telegram item ${index + 1}`} className="rounded-lg border p-3">
              <div>Telegram item {index + 1} · {id}</div>
              {problem ? <RequiredManualAsset message={`Telegram item ${index + 1} requires a manual replacement — ${problem}.`} /> : null}
              {onReorder ? (
                <MoveControls
                  label={`Telegram item ${index + 1}`}
                  index={index}
                  length={ids.length}
                  onMove={(target) => onReorder({ ...revision.payload, mediaAssetIds: move(ids, index, target) })}
                />
              ) : null}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function InstagramAssignments({ revision, onReorder }: { revision: RevisionFor<"instagram">; onReorder?: MediaPlanProps["onReorder"] }) {
  const slides = [...revision.payload.carousel].sort((left, right) => left.order - right.order)
  if (!slides.length) return <RequiredManualAsset message="No Instagram carousel media is assigned." />
  return (
    <ol className="space-y-2">
      {slides.map((slide, index) => (
        <li key={`${slide.order}:${index}`} aria-label={`Media assignment slide ${slide.order}`} className="rounded-lg border p-3">
          <div className="font-medium">Slide {slide.order} · <DirectionBoundary as="span" language={null}>{slide.headline}</DirectionBoundary></div>
          <AssignmentDetails platform="instagram" assignment={slide.media} sourceMedia={revision.sourceMedia} />
          {onReorder ? (
            <MoveControls
              label={`slide ${slide.order}`}
              index={index}
              length={slides.length}
              onMove={(target) => {
                const reordered = move(slides, index, target).map((item, itemIndex) => ({
                  ...item,
                  order: itemIndex + 1,
                  media: { ...item.media, order: itemIndex + 1 },
                }))
                onReorder({ ...revision.payload, carousel: reordered })
              }}
            />
          ) : null}
        </li>
      ))}
    </ol>
  )
}

function XAssignments({ revision, onReorder }: { revision: RevisionFor<"x">; onReorder?: MediaPlanProps["onReorder"] }) {
  const posts = [...revision.payload.posts].sort((left, right) => left.order - right.order)
  return (
    <ol className="space-y-2">
      {posts.flatMap((post, postIndex) => {
        const sortedMedia = [...post.media].sort((left, right) => left.order - right.order)
        if (!sortedMedia.length) {
          return [
            <li key={`post:${post.order}:manual`} aria-label={`Media assignment post ${post.order}`} className="rounded-lg border p-3">
              <RequiredManualAsset message={`Post ${post.order} has no assigned media.`} />
            </li>,
          ]
        }
        return sortedMedia.map((assignment, mediaIndex) => (
          <li key={`${post.order}:${assignment.order}:${mediaIndex}`} aria-label={`Media assignment post ${post.order} item ${assignment.order}`} className="rounded-lg border p-3">
            <div className="font-medium">Post {post.order} · media {assignment.order}</div>
            <AssignmentDetails platform="x" assignment={assignment} sourceMedia={revision.sourceMedia} />
            {onReorder ? (
              <MoveControls
                label={`post ${post.order} media ${assignment.order}`}
                index={mediaIndex}
                length={sortedMedia.length}
                onMove={(target) => {
                  const reordered = move(sortedMedia, mediaIndex, target).map((item, itemIndex) => ({ ...item, order: itemIndex + 1 }))
                  const nextPosts = posts.map((item, index) => index === postIndex ? { ...item, media: reordered } : item)
                  onReorder({ ...revision.payload, posts: nextPosts })
                }}
              />
            ) : null}
          </li>
        ))
      })}
    </ol>
  )
}

function BlogAssignments({ revision }: { revision: RevisionFor<"blog"> }) {
  if (!revision.payload.heroMedia) return <RequiredManualAsset message="A blog hero asset must be supplied manually." />
  return (
    <ol>
      <li aria-label="Media assignment blog hero" className="rounded-lg border p-3">
        <div className="font-medium">Blog hero</div>
        <AssignmentDetails platform="blog" assignment={revision.payload.heroMedia} sourceMedia={revision.sourceMedia} />
      </li>
    </ol>
  )
}

function AssignmentDetails({ platform, assignment, sourceMedia }: { platform: "instagram" | "x" | "blog"; assignment: PayloadFor<"instagram">["carousel"][number]["media"]; sourceMedia: SourceMedia[] }) {
  const asset = assignment.mediaAssetId ? sourceMedia.find((item) => item.id === assignment.mediaAssetId) : undefined
  const problem = assignment.mediaAssetId ? sourceAssetProblem(platform, asset) : null
  const requiresManual = !assignment.mediaAssetId || Boolean(problem)
  return (
    <div className="space-y-1 text-sm">
      <div>Role: {assignment.role} · order {assignment.order}</div>
      <div>Asset: {assignment.mediaAssetId ?? "not assigned"}</div>
      <div>Alt text: <DirectionBoundary as="span" language={null}>{assignment.altText}</DirectionBoundary></div>
      <div>Manual brief: <DirectionBoundary as="span" language={null}>{assignment.manualBrief ?? "Not provided"}</DirectionBoundary></div>
      <div>Image prompt: <DirectionBoundary as="span" language={null}>{assignment.imagePrompt ?? "Not provided"}</DirectionBoundary></div>
      {requiresManual ? (
        <div role="alert" className="font-medium text-warning">
          Required manual asset{problem ? ` — ${problem}` : ""}
        </div>
      ) : null}
    </div>
  )
}

function RequiredManualAsset({ message }: { message: string }) {
  return <div role="alert" className="rounded-lg border border-warning/30 bg-[var(--warning-surface)] p-3 text-warning"><strong>Required manual asset</strong> — {message}</div>
}

function MoveControls({ label, index, length, onMove }: { label: string; index: number; length: number; onMove: (target: number) => void }) {
  return (
    <div role="group" aria-label={`Reorder ${label}`} className="mt-2 flex gap-2">
      <button type="button" className="rounded border px-2 py-1" aria-label={`Move ${label} up`} disabled={index === 0} onClick={() => onMove(index - 1)}>Move up</button>
      <button type="button" className="rounded border px-2 py-1" aria-label={`Move ${label} down`} disabled={index === length - 1} onClick={() => onMove(index + 1)}>Move down</button>
    </div>
  )
}

function move<T>(items: readonly T[], from: number, to: number): T[] {
  const next = [...items]
  const [item] = next.splice(from, 1)
  next.splice(to, 0, item)
  return next
}

function dimensions(asset: SourceMedia) {
  return asset.width !== null && asset.height !== null ? `${asset.width}×${asset.height}` : "Dimensions unavailable"
}

function bytes(value: number | null) {
  return value === null ? "Size unavailable" : `${value.toLocaleString()} bytes`
}

function sourceAssetProblem(platform: PlatformRevision["platform"], asset: SourceMedia | undefined) {
  if (!asset) return "assigned source is missing"
  if (!asset.available) return "assigned source is unavailable"
  const mimeType = asset.mimeType?.toLowerCase() ?? ""
  const kind = asset.kind.toLowerCase()
  const image = (kind === "image" || kind === "photo") && ["image/jpeg", "image/png", "image/gif", "image/webp"].includes(mimeType)
  const video = kind === "video" && ["video/mp4", "video/quicktime"].includes(mimeType)
  const document = kind === "document" && [
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/zip",
    "application/octet-stream",
  ].includes(mimeType)
  const supported = platform === "telegram" ? image || video || document : platform === "blog" ? image : image || video
  return supported ? null : "assigned source type is unsupported"
}

function telegramAssetCategory(asset: SourceMedia | undefined): "document" | "visual" | null {
  if (!asset || sourceAssetProblem("telegram", asset)) return null
  return asset.kind.toLowerCase() === "document" ? "document" : "visual"
}

function assertNever(value: never): never {
  throw new Error(`Unsupported platform revision: ${String(value)}`)
}
