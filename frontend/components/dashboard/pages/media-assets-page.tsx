"use client"

import { useQuery } from "@tanstack/react-query"

import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { getMediaAssets } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { MediaTile } from "@/lib/types"

export function MediaAssetsPage({
  initialMedia = [],
  enableQueries = true,
}: {
  initialMedia?: MediaTile[]
  enableQueries?: boolean
}) {
  const mediaQuery = useQuery({
    queryKey: queryKeys.media,
    queryFn: getMediaAssets,
    placeholderData: initialMedia,
    enabled: enableQueries,
  })
  const media = mediaQuery.data ?? initialMedia

  return (
    <OperationsPageFrame
      enableQueries={enableQueries}
      title="Media Assets"
      subtitle="Inspect extracted images and downloaded media candidates."
    >
      <MediaGallery media={media} />
      <Card className="rounded-md py-0" size="sm">
        <CardHeader className="border-b px-3 py-3">
          <CardTitle className="text-base">Media metadata</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <div className="overflow-x-auto">
            <div className="min-w-[820px]">
              <div className="grid grid-cols-[minmax(220px,1fr)_110px_90px_100px_130px_90px_90px] border-b px-3 py-2 text-xs text-muted-foreground">
                <span>Asset</span>
                <span>Fetch</span>
                <span>Quality</span>
                <span>Confidence</span>
                <span>Source type</span>
                <span>Role</span>
                <span>Primary</span>
              </div>
              <div className="divide-y">
                {media.map((asset) => (
                  <div key={asset.id} className="grid grid-cols-[minmax(220px,1fr)_110px_90px_100px_130px_90px_90px] items-center gap-3 px-3 py-3 text-sm">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{asset.fileName}</div>
                      <div className="text-xs text-muted-foreground">{asset.dimensions} - {asset.size}</div>
                    </div>
                    <Badge variant="outline" className="h-6 rounded-md">{asset.fetchStatus ?? "unknown"}</Badge>
                    <span>{asset.quality ?? "unknown"}</span>
                    <span className="tabular-nums">{asset.confidence ?? "-"}</span>
                    <span>{asset.sourceType ?? "-"}</span>
                    <span>{asset.role ?? "-"}</span>
                    <span>{asset.isPrimary ? "Primary" : asset.isPrimaryCandidate ? "Candidate" : "-"}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </OperationsPageFrame>
  )
}

function MediaGallery({ media }: { media: MediaTile[] }) {
  return (
    <Card role="region" aria-label="Media extraction" className="rounded-md py-0" size="sm">
      <CardHeader className="border-b px-3 py-3"><CardTitle className="text-base">Media extraction</CardTitle></CardHeader>
      <CardContent className="px-3 py-3">
        {media.length ? (
          <div className="grid grid-cols-[repeat(6,minmax(150px,1fr))] gap-3 overflow-x-auto">
            {media.map((tile) => (
              <figure key={tile.id} data-testid="media-tile" className="min-w-36">
                <div className="relative aspect-video overflow-hidden rounded-md bg-muted">
                  <img src={tile.src} alt="" className="size-full object-cover" />
                  <span className="absolute left-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">{tile.format}</span>
                  <span className="absolute right-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">{tile.dimensions}</span>
                </div>
                <figcaption className="mt-1 min-w-0"><div className="truncate text-xs font-medium">{tile.fileName}</div><div className="mt-0.5 flex items-center justify-between text-[11px] text-muted-foreground"><span>{tile.age}</span><span>{tile.size}</span></div></figcaption>
              </figure>
            ))}
          </div>
        ) : <div className="py-8 text-center text-sm text-muted-foreground">No media assets yet</div>}
      </CardContent>
    </Card>
  )
}
