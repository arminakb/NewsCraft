import { Camera, CircleHelp, FileText, Globe2, Layers3 } from "lucide-react"
import type { ComponentProps } from "react"

import { cn } from "@/lib/utils"

import type { AutomationPlatform } from "./automation-types"

export function WorkflowPlatformIcon({ platform, className }: { platform: AutomationPlatform; className?: string }) {
  if (platform === "telegram") return <TelegramMark aria-hidden="true" className={className} />
  if (platform === "x") return <XMark aria-hidden="true" className={className} />
  if (platform === "blog") return <Globe2 aria-hidden="true" className={className} />
  if (platform === "instagram") return <Camera aria-hidden="true" className={className} />
  if (platform === "draft") return <FileText aria-hidden="true" className={className} />
  if (platform === "multi") return <Layers3 aria-hidden="true" className={className} />
  return <CircleHelp aria-hidden="true" className={className} />
}

export function platformLabel(platforms: AutomationPlatform[]) {
  const distinct = [...new Set(platforms)]
  if (distinct.length > 1 || distinct.includes("multi")) {
    const known = distinct.filter((item) => item !== "multi" && item !== "unknown").map(singlePlatformLabel)
    return known.length > 1 ? known.join(" + ") : "Multiple outputs"
  }
  return singlePlatformLabel(distinct[0] ?? "unknown")
}

export function primaryPlatform(platforms: AutomationPlatform[]): AutomationPlatform {
  const distinct = [...new Set(platforms)]
  if (!distinct.length) return "unknown"
  return distinct.length === 1 ? distinct[0] : "multi"
}

function singlePlatformLabel(platform: AutomationPlatform) {
  if (platform === "telegram") return "Telegram"
  if (platform === "x") return "X"
  if (platform === "blog") return "Blog"
  if (platform === "instagram") return "Instagram"
  if (platform === "draft") return "Draft"
  if (platform === "multi") return "Multiple outputs"
  return "Custom output"
}

function TelegramMark({ className, ...props }: ComponentProps<"svg">) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={cn("fill-current", className)} data-platform-logo="telegram" focusable="false" {...props}>
      <path d="M11.944 0A12 12 0 1 0 24 12 12 12 0 0 0 11.944 0Zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.628-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.479.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.324-.437.893-.663 3.498-1.524 5.831-2.529 6.998-3.014 3.333-1.386 4.025-1.627 4.476-1.635Z" />
    </svg>
  )
}

function XMark({ className, ...props }: ComponentProps<"svg">) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={cn("fill-current", className)} data-platform-logo="x" focusable="false" {...props}>
      <path d="M18.901 1.153h3.68l-8.04 9.19L24 22.847h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z" />
    </svg>
  )
}
