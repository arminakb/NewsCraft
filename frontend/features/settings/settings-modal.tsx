"use client"

import { ArrowLeft, X } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useCallback, useEffect, useRef, useState } from "react"

import {
  guardedNavigation,
  useHasDirtyNavigation,
} from "@/components/editorial/use-dirty-navigation"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

import { ContentSettingsPage } from "./content-settings-page"
import {
  consumeSettingsReturnPath,
  defaultSettingsSection,
  hasRememberedSettingsReturnPath,
  isSettingsSectionId,
  resolveSettingsSection,
  requestSettingsFocusRestoration,
  settingsHref,
  settingsSections,
  type SettingsSectionId,
} from "./settings-sections"

const discardMessage = "Discard unsaved settings changes?"
const settingsHistoryDepthKey = "__newscraftSettingsDepth"

function settingsHistoryDepth(state: unknown) {
  if (!state || typeof state !== "object") return null
  const value = (state as Record<string, unknown>)[settingsHistoryDepthKey]
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null
}

export function SettingsModal() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const requestedSection = searchParams.get("section")
  const [activeSectionId, setActiveSectionId] = useState<SettingsSectionId>(
    () => resolveSettingsSection(requestedSection).id,
  )
  const activeSection = resolveSettingsSection(activeSectionId)
  const dirty = useHasDirtyNavigation()
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const historyDepthRef = useRef(0)
  const returnThroughHistoryRef = useRef(hasRememberedSettingsReturnPath())
  const [open, setOpen] = useState(true)
  const [mobileView, setMobileView] = useState<"categories" | "content">("categories")

  useEffect(() => {
    if (pathname !== "/settings") return
    if (isSettingsSectionId(requestedSection)) return
    router.replace(settingsHref(defaultSettingsSection.id), { scroll: false })
  }, [pathname, requestedSection, router])

  useEffect(() => {
    if (isSettingsSectionId(requestedSection)) {
      setActiveSectionId(requestedSection)
    }
  }, [requestedSection])

  useEffect(() => {
    if (!returnThroughHistoryRef.current) return
    const existingDepth = settingsHistoryDepth(window.history.state)
    historyDepthRef.current = existingDepth ?? 0
    if (existingDepth !== null) return
    window.history.replaceState(
      {
        ...(window.history.state ?? {}),
        [settingsHistoryDepthKey]: 0,
      },
      "",
      window.location.href,
    )
  }, [])

  useEffect(() => {
    const syncSectionFromHistory = () => {
      const section = new URLSearchParams(window.location.search).get("section")
      historyDepthRef.current = settingsHistoryDepth(window.history.state) ?? 0
      setActiveSectionId(resolveSettingsSection(section).id)
    }
    window.addEventListener("popstate", syncSectionFromHistory)
    return () => window.removeEventListener("popstate", syncSectionFromHistory)
  }, [])

  const closeModal = useCallback(() => {
    guardedNavigation(() => {
      const returnPath = consumeSettingsReturnPath()
      requestSettingsFocusRestoration()
      setOpen(false)
      if (returnThroughHistoryRef.current) {
        const historyDelta = -(historyDepthRef.current + 1)
        window.setTimeout(() => window.history.go(historyDelta), 0)
        return
      }
      router.replace(returnPath, { scroll: false })
    }, discardMessage)
  }, [router])

  const selectSection = useCallback((section: SettingsSectionId) => {
    const navigate = () => {
      const nextDepth = returnThroughHistoryRef.current ? historyDepthRef.current + 1 : 0
      const updateHistory = returnThroughHistoryRef.current
        ? window.history.pushState.bind(window.history)
        : window.history.replaceState.bind(window.history)
      updateHistory(
        {
          ...(window.history.state ?? {}),
          [settingsHistoryDepthKey]: nextDepth,
        },
        "",
        settingsHref(section),
      )
      historyDepthRef.current = nextDepth
      setActiveSectionId(section)
      setMobileView("content")
    }
    guardedNavigation(navigate, discardMessage)
  }, [])

  const showCategories = useCallback(() => {
    guardedNavigation(() => setMobileView("categories"), discardMessage)
  }, [])

  return (
    <Dialog
      open={open}
      disablePointerDismissal={dirty}
      onOpenChange={(open, eventDetails) => {
        if (open) return
        if (eventDetails.reason === "outside-press" && dirty) return
        closeModal()
      }}
    >
      <DialogContent
        className="h-dvh max-h-dvh max-w-none overflow-hidden rounded-none border-0 p-0 shadow-2xl min-[700px]:h-[min(780px,calc(100dvh-3rem))] min-[700px]:max-h-[calc(100dvh-3rem)] min-[700px]:w-[min(1100px,calc(100vw-3rem))] min-[700px]:rounded-2xl min-[700px]:border"
        data-testid="settings-modal"
        initialFocus={closeButtonRef}
        overlayClassName="z-[80] bg-black/55 backdrop-blur-[3px]"
        viewportClassName="z-[90] overflow-hidden p-0 min-[700px]:p-6"
      >
        <DialogTitle className="sr-only">Settings</DialogTitle>
        <DialogDescription className="sr-only">
          Configure NewsCraft provider, publishing, retention, and prompt settings.
        </DialogDescription>

        <div className="grid h-full min-h-0 min-w-0 min-[700px]:grid-cols-[248px_minmax(0,1fr)]">
          <aside
            aria-label="Settings categories"
            className={cn(
              "min-h-0 min-w-0 flex-col bg-muted/45 min-[700px]:flex min-[700px]:border-r",
              mobileView === "categories" ? "flex" : "hidden",
            )}
          >
            <SettingsRailHeader closeButtonRef={closeButtonRef} onClose={closeModal} />
            <SettingsNavigation
              activeSection={activeSection.id}
              onSelect={selectSection}
            />
          </aside>

          <section
            aria-labelledby="settings-category-title"
            className={cn(
              "min-h-0 min-w-0 flex-col bg-popover min-[700px]:flex",
              mobileView === "content" ? "flex" : "hidden",
            )}
          >
            <header className="flex min-h-[72px] shrink-0 items-center gap-3 border-b px-4 min-[700px]:px-7">
              <Button
                aria-label="Back to Settings categories"
                className="-ml-2 min-[700px]:hidden"
                onClick={showCategories}
                size="icon"
                type="button"
                variant="ghost"
              >
                <ArrowLeft aria-hidden="true" />
              </Button>
              <div className="min-w-0">
                <h2 className="truncate text-lg font-semibold" id="settings-category-title">
                  {activeSection.title}
                </h2>
                <p className="mt-0.5 hidden truncate text-[13px] text-muted-foreground sm:block">
                  {activeSection.description}
                </p>
              </div>
              <Button
                aria-label="Close Settings"
                className="ml-auto min-[700px]:hidden"
                onClick={closeModal}
                size="icon"
                type="button"
                variant="ghost"
              >
                <X aria-hidden="true" />
              </Button>
            </header>
            <div
              className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
              data-testid="settings-content-panel"
            >
              <div
                className="animate-in fade-in duration-150 motion-reduce:animate-none"
                key={activeSection.id}
              >
                <ContentSettingsPage section={activeSection.id} />
              </div>
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function SettingsRailHeader({
  closeButtonRef,
  onClose,
}: {
  closeButtonRef: React.RefObject<HTMLButtonElement | null>
  onClose: () => void
}) {
  return (
    <header className="flex min-h-[72px] shrink-0 items-center gap-3 border-b px-3">
      <Button
        aria-label="Close Settings"
        onClick={onClose}
        ref={closeButtonRef}
        size="icon"
        type="button"
        variant="ghost"
      >
        <X aria-hidden="true" />
      </Button>
      <div>
        <div className="text-base font-semibold">Settings</div>
        <div className="text-xs text-muted-foreground">NewsCraft preferences</div>
      </div>
    </header>
  )
}

function SettingsNavigation({
  activeSection,
  onSelect,
}: {
  activeSection: SettingsSectionId
  onSelect: (section: SettingsSectionId) => void
}) {
  return (
    <nav
      aria-label="Settings categories"
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2.5"
    >
      <div className="space-y-1">
        {settingsSections.map((section) => {
          const active = section.id === activeSection
          const Icon = section.icon
          return (
            <button
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-11 w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-[13px] font-medium text-muted-foreground transition-colors duration-150 hover:bg-navigation-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none",
                active && "bg-navigation-active font-semibold text-primary",
              )}
              data-settings-section={section.id}
              key={section.id}
              onClick={() => onSelect(section.id)}
              type="button"
            >
              <Icon
                aria-hidden="true"
                className={cn("size-[18px] shrink-0", active && "text-primary")}
                strokeWidth={1.5}
              />
              <span>{section.title}</span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}
