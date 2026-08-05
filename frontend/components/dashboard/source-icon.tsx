import { CircleHelp, Globe2, MessageSquare, Newspaper, Rss, Send } from "lucide-react"

import { cn } from "@/lib/utils"
import type { SourcePlatform } from "@/features/operations/ingestion-types"

export function SourceIcon({ platform, className }: { platform: SourcePlatform; className?: string }) {
  if (platform === "telegram_public") {
    return (
      <span className={cn("inline-flex size-7 items-center justify-center rounded-full bg-[var(--flow-telegram)] text-white", className)}>
        <Send className="size-4" aria-hidden="true" />
      </span>
    )
  }

  const serviceIcon =
    platform === "google_news"
      ? Newspaper
      : platform === "gdelt"
        ? Globe2
        : platform === "hackernews"
          ? MessageSquare
          : platform === "unknown"
            ? CircleHelp
            : null

  if (serviceIcon) {
    const ServiceIcon = serviceIcon
    return (
      <span className={cn("inline-flex size-7 items-center justify-center rounded-md bg-slate-600 text-white", className)}>
        <ServiceIcon className="size-4" aria-hidden="true" />
      </span>
    )
  }

  return (
    <span className={cn("inline-flex size-7 items-center justify-center rounded-md bg-orange-500 text-white", className)}>
      <Rss className="size-4" aria-hidden="true" />
    </span>
  )
}
