import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import type { MediaTile } from "@/lib/types"

export function MediaStrip({ media }: { media: MediaTile[] }) {
  return (
    <Card role="region" aria-label="Media extraction" className="rounded-md py-0" size="sm">
      <CardHeader className="flex-row items-center border-b px-3 py-3">
        <CardTitle className="text-base">
          Media extraction <span className="font-normal text-muted-foreground">(latest)</span>
        </CardTitle>
        <Button variant="link" className="ml-auto h-auto p-0 text-primary">
          View all media
        </Button>
      </CardHeader>
      <CardContent className="px-3 py-3">
        <div className="grid grid-cols-[repeat(6,minmax(150px,1fr))] gap-3 overflow-x-auto">
          {media.map((tile) => (
            <figure key={tile.id} data-testid="media-tile" className="min-w-36">
              <div className="relative aspect-video overflow-hidden rounded-md bg-muted">
                <img src={tile.src} alt="" className="size-full object-cover" />
                <span className="absolute left-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
                  {tile.format}
                </span>
                <span className="absolute right-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
                  {tile.dimensions}
                </span>
              </div>
              <figcaption className="mt-1 min-w-0">
                <div className="truncate text-xs font-medium">{tile.fileName}</div>
                <div className="mt-0.5 flex items-center justify-between text-[11px] text-muted-foreground">
                  <span>{tile.age}</span>
                  <span>{tile.size}</span>
                </div>
              </figcaption>
            </figure>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
