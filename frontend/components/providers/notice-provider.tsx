"use client"

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react"

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
          <div
            key={notice.id}
            className={`rounded-md border bg-background p-3 shadow-lg ${notice.tone === "error" ? "border-red-200 dark:border-red-800" : "border-emerald-200 dark:border-emerald-800"}`}
          >
            <div data-notice-title className="font-semibold">
              {notice.title}
            </div>
            <div className="mt-1 text-sm text-muted-foreground" dir="auto">
              {notice.message}
            </div>
          </div>
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
