"use client"

import { X } from "lucide-react"
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export type NoticeInput = {
  tone: "success" | "error"
  title: string
  message: string
  compact?: boolean
}

export type Notice = NoticeInput & { id: string; createdAt: number }

type NoticeContextValue = {
  pushNotice: (notice: NoticeInput) => void
  notices: readonly Notice[]
  retainedNotices: readonly Notice[]
  dismissNotice: (id: string) => void
}

const NoticeContext = createContext<NoticeContextValue | null>(null)

export function NoticeProvider({ children }: { children: React.ReactNode }) {
  const [notices, setNotices] = useState<Notice[]>([])
  const [retainedNotices, setRetainedNotices] = useState<Notice[]>([])
  const nextId = useRef(0)
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>())

  useEffect(
    () => () => {
      for (const timer of timers.current) clearTimeout(timer)
    },
    []
  )

  const pushNotice = useCallback((input: NoticeInput) => {
    const id = `notice-${nextId.current++}`
    const notice = { ...input, id, createdAt: Date.now() }
    setNotices((current) => [...current, notice])
    setRetainedNotices((current) => [...current.slice(-99), notice])
    const timer = setTimeout(() => {
      setNotices((current) => current.filter((notice) => notice.id !== id))
      timers.current.delete(timer)
    }, 5_000)
    timers.current.add(timer)
  }, [])

  const dismissNotice = useCallback((id: string) => {
    setNotices((current) => current.filter((notice) => notice.id !== id))
    setRetainedNotices((current) => current.filter((notice) => notice.id !== id))
  }, [])

  return (
    <NoticeContext.Provider value={{ dismissNotice, notices, pushNotice, retainedNotices }}>
      {children}
      <div
        role="status"
        aria-label="Notifications"
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed right-4 top-16 z-[120] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
      >
        {notices.map((notice) => (
          <Alert
            key={notice.id}
            tone={notice.tone}
            className={cn(
              "pointer-events-auto bg-popover shadow-md",
              notice.compact && "w-fit max-w-full self-end p-2.5",
            )}
          >
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
              <div className="min-w-0 break-words">
                <AlertTitle data-notice-title>{notice.title}</AlertTitle>
                <AlertDescription dir="auto">{notice.message}</AlertDescription>
              </div>
              <Button
                aria-label={`Dismiss ${notice.title}`}
                className="-me-1 -mt-1 shrink-0"
                onClick={() => dismissNotice(notice.id)}
                size="icon-sm"
                type="button"
                variant="ghost"
              >
                <X aria-hidden="true" />
              </Button>
            </div>
          </Alert>
        ))}
      </div>
    </NoticeContext.Provider>
  )
}

export function useNotices() {
  const context = useContext(NoticeContext)
  if (!context) throw new Error("useNotices must be used within NoticeProvider")
  return context
}

export function useOptionalNotices() {
  return useContext(NoticeContext)
}
