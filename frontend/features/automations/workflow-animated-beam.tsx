"use client"

import { useEffect, useId, useState, type RefObject } from "react"

import { cn } from "@/lib/utils"

const FALLBACK_PATH = "M 18,44 H 82"
const FALLBACK_DIMENSIONS = { width: 100, height: 88 }

/**
 * Adapted from ref/Component.tsx. Keep the reference path construction and
 * moving-gradient treatment; native SVG animation replaces framer-motion so
 * gallery cards stay lightweight and do not mount a full editor.
 */
export interface AnimatedBeamProps {
  className?: string
  containerRef: RefObject<HTMLElement | null>
  fromRef: RefObject<HTMLElement | null>
  toRef: RefObject<HTMLElement | null>
  reverse?: boolean
  pathColor?: string
  pathWidth?: number
  pathOpacity?: number
  gradientStartColor?: string
  gradientStopColor?: string
  delay?: number
  duration?: number
  startXOffset?: number
  startYOffset?: number
  endXOffset?: number
  endYOffset?: number
  animated?: boolean
}

export function AnimatedBeam({
  className,
  containerRef,
  fromRef,
  toRef,
  reverse = false,
  duration = 4.6,
  delay = 0,
  pathColor = "var(--border)",
  pathWidth = 1.4,
  pathOpacity = 0.68,
  gradientStartColor = "currentColor",
  gradientStopColor = "currentColor",
  startXOffset = 0,
  startYOffset = 0,
  endXOffset = 0,
  endYOffset = 0,
  animated = true,
}: AnimatedBeamProps) {
  const id = `workflow-beam-${useId().replace(/:/g, "")}`
  const gradientId = `${id}-gradient`
  const filterId = `${id}-filter`
  const clipId = `${id}-clip`
  const [pathD, setPathD] = useState(FALLBACK_PATH)
  const [svgDimensions, setSvgDimensions] = useState(FALLBACK_DIMENSIONS)

  const gradientCoordinates = reverse
    ? {
        x1: ["90%", "-10%"],
        x2: ["100%", "0%"],
        y1: ["0%", "0%"],
        y2: ["0%", "0%"],
      }
    : {
        x1: ["10%", "110%"],
        x2: ["0%", "100%"],
        y1: ["0%", "0%"],
        y2: ["0%", "0%"],
      }

  useEffect(() => {
    const updatePath = () => {
      if (!containerRef.current || !fromRef.current || !toRef.current) return

      const containerRect = containerRef.current.getBoundingClientRect()
      const rectA = fromRef.current.getBoundingClientRect()
      const rectB = toRef.current.getBoundingClientRect()
      const svgWidth = Math.ceil(containerRect.width)
      const svgHeight = Math.ceil(containerRect.height)
      if (!svgWidth || !svgHeight) return

      setSvgDimensions({ width: svgWidth, height: svgHeight })

      const startX = rectA.left - containerRect.left + rectA.width / 2 + startXOffset
      const startY = rectA.top - containerRect.top + rectA.height / 2 + startYOffset
      const endX = rectB.left - containerRect.left + rectB.width / 2 + endXOffset
      const endY = rectB.top - containerRect.top + rectB.height / 2 + endYOffset
      const centerY = (startY + endY) / 2
      const d = `M ${startX},${centerY} H ${endX}`
      setPathD(d)
    }

    updatePath()
    if (typeof ResizeObserver === "undefined") return

    const resizeObserver = new ResizeObserver(updatePath)
    for (const element of [containerRef.current, fromRef.current, toRef.current]) {
      if (element) resizeObserver.observe(element)
    }
    return () => resizeObserver.disconnect()
  }, [containerRef, endXOffset, endYOffset, fromRef, startXOffset, startYOffset, toRef])

  return (
    <svg
      aria-hidden="true"
      className={cn("workflow-beam-svg pointer-events-none absolute inset-0 h-full w-full overflow-visible", className)}
      data-animated={animated ? "true" : "false"}
      data-flow-connector
      data-workflow-beam={animated ? "animated" : "static"}
      fill="none"
      height={svgDimensions.height}
      viewBox={`0 0 ${svgDimensions.width} ${svgDimensions.height}`}
      width={svgDimensions.width}
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d={pathD} stroke={pathColor} strokeLinecap="round" strokeOpacity={pathOpacity} strokeWidth={pathWidth} />
      {animated ? (
        <>
          <path
            data-workflow-beam-highlight
            d={pathD}
            fill="none"
            pathLength="100"
            stroke={gradientStopColor}
            strokeDasharray="22 78"
            strokeDashoffset="100"
            strokeLinecap="round"
            strokeOpacity="1"
            strokeWidth={pathWidth * 2.4}
          >
            <animate
              attributeName="stroke-dashoffset"
              begin={`${delay}s`}
              calcMode="spline"
              dur={`${duration}s`}
              keySplines="0.16 1 0.3 1"
              keyTimes="0; 1"
              repeatCount="indefinite"
              values="0; -100"
            />
          </path>
          <g
            data-workflow-beam-glow
            clipPath={`url(#${clipId})`}
            filter={`url(#${filterId})`}
          >
            <path
              data-workflow-beam-glow-path
              d={pathD}
              fill="none"
              pathLength="100"
              stroke={gradientStopColor}
              strokeDasharray="22 78"
              strokeDashoffset="100"
              strokeLinecap="round"
              strokeOpacity="0.9"
              strokeWidth={pathWidth * 5.5}
            >
              <animate
                attributeName="stroke-dashoffset"
                begin={`${delay}s`}
                calcMode="spline"
                dur={`${duration}s`}
                keySplines="0.16 1 0.3 1"
                keyTimes="0; 1"
                repeatCount="indefinite"
                values="0; -100"
              />
            </path>
          </g>
          <path
            data-workflow-beam-moving-path
            d={pathD}
            clipPath={`url(#${clipId})`}
            fill="none"
            pathLength="100"
            stroke={`url(#${gradientId})`}
            strokeLinecap="round"
            strokeOpacity="1"
            strokeWidth={pathWidth * 1.45}
          />
          <defs>
            <linearGradient
              data-workflow-beam-gradient
              gradientUnits="objectBoundingBox"
              id={gradientId}
              x1={reverse ? "100%" : "0%"}
              x2={reverse ? "0%" : "100%"}
              y1="0%"
              y2="0%"
            >
              <stop stopColor={gradientStartColor} stopOpacity="0" />
              <stop offset="22%" stopColor={gradientStartColor} stopOpacity="0.2" />
              <stop offset="38%" stopColor={gradientStartColor} stopOpacity="0.9" />
              <stop offset="48%" stopColor={gradientStopColor} />
              <stop offset="58%" stopColor={gradientStopColor} stopOpacity="0.8" />
              <stop offset="74%" stopColor={gradientStopColor} stopOpacity="0.12" />
              <stop offset="100%" stopColor={gradientStopColor} stopOpacity="0" />
              <animate
                attributeName="x1"
                begin={`${delay}s`}
                calcMode="spline"
                dur={`${duration}s`}
                keySplines="0.16 1 0.3 1"
                keyTimes="0; 1"
                repeatCount="indefinite"
                values={gradientCoordinates.x1.join("; ")}
              />
              <animate
                attributeName="x2"
                begin={`${delay}s`}
                calcMode="spline"
                dur={`${duration}s`}
                keySplines="0.16 1 0.3 1"
                keyTimes="0; 1"
                repeatCount="indefinite"
                values={gradientCoordinates.x2.join("; ")}
              />
              <animate
                attributeName="y1"
                begin={`${delay}s`}
                dur={`${duration}s`}
                repeatCount="indefinite"
                values={gradientCoordinates.y1.join("; ")}
              />
              <animate
                attributeName="y2"
                begin={`${delay}s`}
                dur={`${duration}s`}
                repeatCount="indefinite"
                values={gradientCoordinates.y2.join("; ")}
              />
            </linearGradient>
            <filter
              colorInterpolationFilters="sRGB"
              data-workflow-beam-filter
              filterUnits="userSpaceOnUse"
              height={svgDimensions.height * 7}
              id={filterId}
              width={svgDimensions.width * 2}
              x={-svgDimensions.width * 0.5}
              y={-svgDimensions.height * 3}
            >
              <feGaussianBlur data-workflow-beam-blur result="workflow-beam-blur" stdDeviation="3.2" />
            </filter>
            <clipPath data-workflow-beam-clip clipPathUnits="userSpaceOnUse" id={clipId}>
              <path d={pathD} fill="none" stroke="white" strokeLinecap="round" strokeWidth={Math.max(pathWidth * 10, 18)} />
            </clipPath>
          </defs>
        </>
      ) : null}
    </svg>
  )
}
