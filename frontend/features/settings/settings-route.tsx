"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

import { sectionFromLegacyHash, settingsHref } from "./settings-sections"

export function LegacySettingsRoute() {
  const router = useRouter()

  useEffect(() => {
    const section = sectionFromLegacyHash(window.location.hash)
    router.replace(settingsHref(section?.id), { scroll: false })
  }, [router])

  return null
}

export function SettingsRouteBackground() {
  return (
    <section aria-hidden="true" className="nc-page gap-5">
      <div className="h-8 w-48 rounded-lg bg-muted" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div className="h-24 rounded-xl border bg-card" key={index} />
        ))}
      </div>
      <div className="h-80 rounded-xl border bg-card" />
    </section>
  )
}
