"use client"

import { CircleHelp, Globe2, MessageSquare, Newspaper, Send } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { reportSourceIconFailure } from "@/features/operations/ingestion-api"
import type { SourcePlatform } from "@/features/operations/ingestion-types"
import { API_BASE_URL } from "@/lib/http"
import { cn } from "@/lib/utils"

type SourceIconProps = {
  platform: SourcePlatform
  className?: string
  iconUrl?: string | null
  iconUpdatedAt?: string | null
  name?: string | null
  sourceId?: string
}

export function SourceIcon({ platform, className, iconUrl, iconUpdatedAt, name, sourceId }: SourceIconProps) {
  const discoveredIconUrl = isFeedPlatform(platform) ? toApiIconUrl(iconUrl, iconUpdatedAt) : null
  const [imageFailed, setImageFailed] = useState(false)
  const reportedIconRef = useRef<string | null>(null)

  useEffect(() => {
    setImageFailed(false)
    reportedIconRef.current = null
  }, [discoveredIconUrl, sourceId])

  if (discoveredIconUrl && !imageFailed) {
    return (
      <span
        className={cn(
          "inline-flex size-7 shrink-0 items-center justify-center bg-transparent",
          className,
        )}
      >
        <img
          alt=""
          className="size-full object-contain p-0.5"
          decoding="async"
          loading="lazy"
          onError={() => {
            setImageFailed(true)
            if (sourceId && reportedIconRef.current !== discoveredIconUrl) {
              reportedIconRef.current = discoveredIconUrl
              void reportSourceIconFailure(sourceId).catch(() => undefined)
            }
          }}
          src={discoveredIconUrl}
        />
      </span>
    )
  }

  if (platform === "telegram_public") {
    return (
      <span className={cn("inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-[var(--flow-telegram)] text-white", className)}>
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
      <span className={cn("inline-flex size-7 shrink-0 items-center justify-center rounded-md bg-slate-600 text-white", className)}>
        <ServiceIcon className="size-4" aria-hidden="true" />
      </span>
    )
  }

  return (
    <span
      aria-label={name ? `${name} source mark` : "Source mark"}
      className={cn(
        "inline-flex size-7 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 px-1 text-[0.65rem] font-bold tracking-wide text-primary",
        className,
      )}
    >
      {sourceMark(name, platform)}
    </span>
  )
}

function isFeedPlatform(platform: SourcePlatform) {
  return platform === "rss" || platform === "atom"
}

function toApiIconUrl(value?: string | null, updatedAt?: string | null) {
  if (!value || !value.startsWith("/sources/")) return null
  const cacheKey = updatedAt ? `?v=${encodeURIComponent(updatedAt)}` : ""
  return `${API_BASE_URL}${value}${cacheKey}`
}

function sourceMark(name: string | null | undefined, platform: SourcePlatform) {
  const value = name?.trim() || (platform === "atom" ? "Atom" : "RSS")
  const words = value.split(/\s+/).filter(Boolean)
  if (words.length > 1) return `${Array.from(words[0])[0] ?? "S"}${Array.from(words.at(-1) ?? "")[0] ?? ""}`.toUpperCase()
  return (Array.from(value)[0] ?? "S").toUpperCase()
}
