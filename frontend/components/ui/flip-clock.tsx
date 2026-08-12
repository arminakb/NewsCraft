"use client"

import { useEffect, useState } from "react"
import { AnimatePresence, motion, useReducedMotion } from "framer-motion"

import { cn } from "@/lib/utils"

type ClockDigit = number | null

interface FlipClockProps {
  className?: string
}

/**
 * Reused from ref/Prompt.md and the FlipClock source in ref/Component.tsx.
 * The only behavior changes are hydration-safe startup, reduced-motion
 * handling, and the responsive/header layout surface.
 */
function Digit({ value, reducedMotion }: { value: ClockDigit; reducedMotion: boolean }) {
  return (
    <div
      aria-hidden="true"
      className="flip-clock-digit relative flex h-14 w-10 items-center justify-center overflow-hidden rounded-md bg-zinc-900 font-mono text-3xl font-bold text-white max-[479px]:h-11 max-[479px]:w-8 max-[479px]:text-2xl"
    >
      <AnimatePresence mode="popLayout">
        {value === null ? null : (
          <motion.span
            key={value}
            initial={reducedMotion ? false : { y: -40, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={reducedMotion ? { opacity: 0 } : { y: 40, opacity: 0 }}
            transition={{ duration: reducedMotion ? 0 : 0.3 }}
            className="absolute inset-0 flex items-center justify-center"
          >
            {value}
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  )
}

export default function FlipClock({ className }: FlipClockProps) {
  // Keep the initial render deterministic. The reference initializes with
  // Date.now(), but that can differ between Next.js server and browser render.
  const [time, setTime] = useState<Date | null>(null)
  const reducedMotion = useReducedMotion() ?? false

  useEffect(() => {
    const updateTime = () => setTime(new Date())
    updateTime()
    const interval = window.setInterval(updateTime, 1000)
    return () => window.clearInterval(interval)
  }, [])

  const hours = time ? time.getHours().toString().padStart(2, "0") : null
  const minutes = time ? time.getMinutes().toString().padStart(2, "0") : null
  const seconds = time ? time.getSeconds().toString().padStart(2, "0") : null
  const formattedTime = time ? `${hours}:${minutes}:${seconds}` : "--:--:--"

  return (
    <div
      aria-label={time ? `Local time ${formattedTime}` : "Loading local time"}
      aria-live="off"
      className={cn("flip-clock flex items-center justify-center gap-1 whitespace-nowrap", className)}
      data-testid="flip-clock"
      data-time={formattedTime}
      role="timer"
    >
      {renderDigits(hours, "h", reducedMotion)}
      <span aria-hidden="true" className="flip-clock-separator text-3xl font-bold text-zinc-500 max-[479px]:text-2xl">:</span>
      {renderDigits(minutes, "m", reducedMotion)}
      <span aria-hidden="true" className="flip-clock-separator text-3xl font-bold text-zinc-500 max-[479px]:text-2xl">:</span>
      {renderDigits(seconds, "s", reducedMotion)}
    </div>
  )
}

function renderDigits(value: string | null, prefix: string, reducedMotion: boolean) {
  return (value ?? "  ").split("").map((digit, index) => (
    <Digit key={`${prefix}-${index}`} reducedMotion={reducedMotion} value={value ? Number.parseInt(digit, 10) : null} />
  ))
}
