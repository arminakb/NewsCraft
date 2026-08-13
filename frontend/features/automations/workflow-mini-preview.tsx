"use client"

import { TriangleAlert } from "lucide-react"
import { memo, useEffect, useMemo, useRef, useState } from "react"

import { cn } from "@/lib/utils"

import type { AutomationPreviewStage } from "./automation-types"
import { AnimatedBeam } from "./workflow-animated-beam"
import { nodeTypeIcon } from "./workflow-node-visual"
import { primaryPlatform, WorkflowPlatformIcon } from "./workflow-platform-icon"

const MAX_VISIBLE_STAGES = 4
const PREVIEW_ICON_SIZE = 32
const PREVIEW_BEAM_OFFSET = PREVIEW_ICON_SIZE / 2 + 2
const priority: Record<AutomationPreviewStage["category"], number> = {
  trigger: 0,
  content: 50,
  ai: 90,
  validation: 70,
  review: 100,
  draft: 80,
  publish: 110,
  unknown: 10,
}

type PreviewElementRef = { current: HTMLElement | null }

type PreviewItem =
  | { kind: "stage"; key: string; stage: AutomationPreviewStage; stageIndex: number }
  | { kind: "overflow"; key: string; hiddenCount: number; stageIndex: number }

export const WorkflowMiniPreview = memo(function WorkflowMiniPreview({
  stages,
  paused,
}: {
  stages: AutomationPreviewStage[]
  paused: boolean
}) {
  const summary = summarizePreviewStages(stages)
  const accessibleSummary = stages.length
    ? `Workflow stages: ${stages.map(workflowStageAccessibleLabel).join(", ")}.${summary.hiddenCount ? ` ${summary.hiddenCount} additional workflow steps are collapsed visually.` : ""}`
    : "Workflow preview unavailable."
  const attentionIndex = summary.visible.findIndex((stage) => stage.needsAttention || stage.category === "unknown")
  const items = useMemo(() => buildPreviewItems(summary), [summary])
  const itemSignature = items.map((item) => item.key).join("|")
  const itemRefs = useMemo(
    () => new Map(items.map((item) => [item.key, { current: null } as PreviewElementRef])),
    [itemSignature],
  )
  const containerRef = useRef<HTMLDivElement>(null)
  const reducedMotion = usePrefersReducedMotion()
  const flowActive = !paused && !reducedMotion

  if (!summary.visible.length) {
    return <p aria-label="Empty" className="flex min-h-20 items-center text-sm text-muted-foreground">Empty</p>
  }

  return (
    <div
      aria-label={accessibleSummary}
      className={cn("flex min-h-[88px] min-w-0 items-center", paused && "opacity-80")}
      data-flow-motion={paused ? "paused" : "active"}
      data-reduced-motion={reducedMotion ? "true" : "false"}
      role="img"
    >
      <div className="relative min-h-[88px] w-full min-w-0 overflow-hidden px-1 py-2" ref={containerRef}>
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-0">
          {items.slice(0, -1).map((item, index) => {
            const nextItem = items[index + 1]
            const fromRef = itemRefs.get(item.key)
            const toRef = itemRefs.get(nextItem.key)
            if (!fromRef || !toRef) return null

            const targetStage = nextItem.kind === "stage"
              ? nextItem.stage
              : item.kind === "stage"
                ? item.stage
                : summary.visible[0]
            const active = flowActive && (attentionIndex < 0 || nextItem.stageIndex < attentionIndex)
            return (
              <AnimatedBeam
                animated={active}
                className={connectorStyle(targetStage)}
                containerRef={containerRef}
                delay={index * 0.35}
                duration={4.6}
                endXOffset={-PREVIEW_BEAM_OFFSET}
                fromRef={fromRef}
                gradientStartColor="var(--flow-beam-start)"
                gradientStopColor="var(--flow-beam-highlight)"
                key={`${item.key}-${nextItem.key}`}
                pathColor="var(--muted-foreground)"
                pathOpacity={0.42}
                pathWidth={1.55}
                startXOffset={PREVIEW_BEAM_OFFSET}
                toRef={toRef}
              />
            )
          })}
        </div>

        <div
          className="relative z-10 grid w-full min-w-0 items-start gap-x-1"
          style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}
        >
          {items.map((item) => {
            const itemRef = itemRefs.get(item.key)
            if (item.kind === "overflow") {
              return (
                <div className="flex min-w-0 flex-col items-center gap-1 text-center" key={item.key}>
                  <span
                    aria-hidden="true"
                    className="grid size-8 shrink-0 place-items-center rounded-full border border-dashed border-border/80 bg-muted/80 px-0.5 text-[11px] font-semibold leading-none text-muted-foreground"
                    ref={(element) => { if (itemRef) itemRef.current = element }}
                  >
                    +{item.hiddenCount}
                  </span>
                  <span className="max-w-full text-[12px] leading-4 text-muted-foreground">more</span>
                </div>
              )
            }

            return (
              <div className="flex min-w-0 flex-col items-center gap-1 text-center" key={item.key}>
                <span
                  className={cn(
                    "relative grid size-8 shrink-0 place-items-center rounded-lg border shadow-xs ring-1 ring-inset ring-white/10",
                    stageStyle(item.stage),
                  )}
                  data-node-icon={item.stage.nodeType}
                  data-stage-category={item.stage.category}
                  data-stage-type={item.stage.nodeType}
                  ref={(element) => { if (itemRef) itemRef.current = element }}
                >
                  <StageIcon stage={item.stage} />
                  {item.stage.needsAttention || item.stage.category === "unknown" ? (
                    <span className="absolute -end-1 -top-1 grid size-4 place-items-center rounded-full bg-[var(--error-surface)] text-destructive shadow-xs">
                      <TriangleAlert aria-hidden="true" className="size-2.5" />
                    </span>
                  ) : null}
                </span>
                <span
                  className="max-w-full text-[12px] leading-4 text-muted-foreground [overflow-wrap:anywhere]"
                  title={item.stage.label}
                >
                  {workflowStageLabel(item.stage)}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
})

function StageIcon({ stage }: { stage: AutomationPreviewStage }) {
  const platform = primaryPlatform(stage.platforms)
  if (stage.platforms.length) return <WorkflowPlatformIcon className="size-[18px] shrink-0" platform={platform} />
  const Icon = nodeTypeIcon(stage.nodeType)
  return <Icon aria-hidden="true" className="size-[18px] shrink-0 stroke-[1.8]" />
}

function usePrefersReducedMotion() {
  const [reducedMotion, setReducedMotion] = useState(() => (
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  ))

  useEffect(() => {
    const mediaQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)")
    if (!mediaQuery) return

    const update = () => setReducedMotion(mediaQuery.matches)
    update()
    mediaQuery.addEventListener?.("change", update)
    return () => mediaQuery.removeEventListener?.("change", update)
  }, [])

  return reducedMotion
}

function buildPreviewItems(summary: ReturnType<typeof summarizePreviewStages>): PreviewItem[] {
  const items: PreviewItem[] = summary.visible.map((stage, stageIndex) => ({
    kind: "stage",
    key: stage.nodeId,
    stage,
    stageIndex,
  }))
  if (!summary.hiddenCount || summary.collapseAfter < 0) return items

  const insertAt = Math.min(summary.collapseAfter + 1, items.length - 1)
  items.splice(insertAt, 0, {
    kind: "overflow",
    key: `overflow-${summary.visible[0]?.nodeId ?? "workflow"}`,
    hiddenCount: summary.hiddenCount,
    stageIndex: insertAt,
  })
  return items
}

export function summarizePreviewStages(stages: AutomationPreviewStage[], limit = MAX_VISIBLE_STAGES) {
  if (stages.length <= limit) return { visible: stages, hiddenCount: 0, collapseAfter: -1 }
  const middleSlots = Math.max(0, limit - 2)
  const selectedMiddle = stages
    .slice(1, -1)
    .map((stage, index) => ({ stage, index: index + 1 }))
    .sort((left, right) => priority[right.stage.category] - priority[left.stage.category] || left.index - right.index)
    .slice(0, middleSlots)
    .sort((left, right) => left.index - right.index)
  const visible = [stages[0], ...selectedMiddle.map((item) => item.stage), stages.at(-1)!]
  const firstGapIndex = visible.findIndex((stage, index) => index > 0 && stages.indexOf(stage) - stages.indexOf(visible[index - 1]) > 1)
  return {
    visible,
    hiddenCount: stages.length - visible.length,
    collapseAfter: firstGapIndex > 0 ? firstGapIndex - 1 : visible.length - 2,
  }
}

export function workflowStageLabel(stage: AutomationPreviewStage) {
  const platform = primaryPlatform(stage.platforms)
  if (stage.nodeType === "new_source_item") return "New source item"
  if (stage.nodeType === "generate_content_pack") return "AI Generate"
  if (stage.nodeType === "human_review") return "Review"
  if (stage.nodeType === "save_drafts" || platform === "draft") return "Draft"
  if (stage.nodeType === "telegram_publish" || platform === "telegram") return "Publish"
  if (platform === "x") return "X"
  if (platform === "blog") return "Blog"
  if (stage.nodeType === "manual_package" || platform === "multi") return "Publish"
  if (stage.nodeType === "select_content") return "Collect"
  if (stage.nodeType === "filter_content") return "Filter"
  if (stage.nodeType === "research") return "AI Research"
  if (stage.nodeType === "validate") return "Validate"
  if (stage.nodeType === "schedule") return "Schedule"
  if (stage.nodeType === "manual") return "Manual"
  return stage.category === "publish" ? "Publish" : stage.category === "unknown" ? "Step" : titleCase(stage.category)
}

function workflowStageAccessibleLabel(stage: AutomationPreviewStage) {
  if (stage.category === "unknown") return "Unsupported workflow step"
  if (stage.nodeType === "new_source_item") return "New source item trigger"
  if (stage.nodeType === "telegram_publish") return "Telegram publish"
  if (stage.nodeType === "generate_content_pack") return "AI generation"
  if (stage.nodeType === "research") return "AI Research"
  if (stage.nodeType === "human_review") return "Human review"
  return stage.label
}

function stageStyle(stage: AutomationPreviewStage) {
  const platform = primaryPlatform(stage.platforms)
  if (platform === "telegram") return "border-[var(--flow-telegram-border)] bg-[var(--flow-telegram-surface)] text-[var(--flow-telegram)]"
  if (platform === "x") return "border-[var(--flow-x-border)] bg-[var(--flow-x-surface)] text-[var(--flow-x)]"
  if (platform === "blog") return "border-[var(--flow-blog-border)] bg-[var(--flow-blog-surface)] text-[var(--flow-blog)]"
  if (platform === "draft" || stage.category === "draft") return "border-[var(--flow-draft-border)] bg-[var(--flow-draft-surface)] text-[var(--flow-draft)]"
  if (stage.nodeType === "research") return "border-[var(--flow-research-border)] bg-[var(--flow-research-surface)] text-[var(--flow-research)]"
  if (stage.category === "ai") return "border-[var(--flow-ai-border)] bg-[var(--flow-ai-surface)] text-[var(--flow-ai)]"
  if (stage.category === "validation") return "border-[var(--flow-validation-border)] bg-[var(--flow-validation-surface)] text-[var(--flow-validation)]"
  if (stage.category === "review") return "border-[var(--flow-review-border)] bg-[var(--flow-review-surface)] text-[var(--flow-review)]"
  if (stage.category === "content") return "border-[var(--flow-content-border)] bg-[var(--flow-content-surface)] text-[var(--flow-content)]"
  if (stage.category === "trigger") return "border-[var(--flow-trigger-border)] bg-[var(--flow-trigger-surface)] text-[var(--flow-trigger)]"
  return "border-border bg-muted text-muted-foreground"
}

function connectorStyle(stage: AutomationPreviewStage) {
  const platform = primaryPlatform(stage.platforms)
  if (platform === "telegram") return "text-[var(--flow-telegram)]"
  if (platform === "x") return "text-[var(--flow-x)]"
  if (platform === "blog") return "text-[var(--flow-blog)]"
  if (stage.category === "ai") return "text-[var(--flow-ai)]"
  if (stage.category === "review") return "text-[var(--flow-review)]"
  if (stage.category === "validation") return "text-[var(--flow-validation)]"
  if (stage.category === "content") return "text-[var(--flow-content)]"
  return "text-[var(--flow-trigger)]"
}

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1)
}
