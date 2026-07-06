import { Rss, Send } from "lucide-react"

import { cn } from "@/lib/utils"
import type { SourcePlatform } from "@/lib/types"

export function SourceIcon({ platform, className }: { platform: SourcePlatform; className?: string }) {
  if (platform === "telegram_public") {
    return (
      <span className={cn("inline-flex size-7 items-center justify-center rounded-full bg-sky-500 text-white", className)}>
        <Send className="size-4" aria-hidden="true" />
      </span>
    )
  }

  return (
    <span className={cn("inline-flex size-7 items-center justify-center rounded-md bg-orange-500 text-white", className)}>
      <Rss className="size-4" aria-hidden="true" />
    </span>
  )
}
