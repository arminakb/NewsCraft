"use client"

import { X } from "lucide-react"
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"

export type NoticeInput = { tone: "success" | "error"; title: string; message: string }

type Notice = NoticeInput & { id: string }

const NoticeContext = createContext<{ pushNotice: (notice: NoticeInput) => void } | null>(null)

export function NoticeProvider({ children }: { children: React.ReactNode }) {
  const [notices, setNotices] = useState<Notice[]>([])
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
    setNotices((current) => [...current, { ...input, id }])
    const timer = setTimeout(() => {
      setNotices((current) => current.filter((notice) => notice.id !== id))
      timers.current.delete(timer)
    }, 5_000)
    timers.current.add(timer)
  }, [])

  const dismissNotice = useCallback((id: string) => {
    setNotices((current) => current.filter((notice) => notice.id !== id))
  }, [])

  return (
    <NoticeContext.Provider value={{ pushNotice }}>
      {children}
      <div
        role="status"
        aria-label="Notifications"
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed right-4 top-16 z-[80] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
      >
        {notices.map((notice) => (
          <Alert
            key={notice.id}
            tone={notice.tone}
            className="pointer-events-auto grid-cols-[auto_1fr_auto] bg-popover shadow-md"
          >
            <div>
              <AlertTitle data-notice-title>{notice.title}</AlertTitle>
              <AlertDescription dir="auto">{notice.message}</AlertDescription>
            </div>
            <Button
              aria-label={`Dismiss ${notice.title}`}
              className="-me-1 -mt-1"
              onClick={() => dismissNotice(notice.id)}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <X aria-hidden="true" />
            </Button>
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
