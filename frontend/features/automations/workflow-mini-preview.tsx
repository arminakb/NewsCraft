import {
  Bot,
  CircleHelp,
  Clock3,
  FileCheck2,
  Filter,
  ListFilter,
  MousePointerClick,
  Package,
  Radio,
  Search,
  ShieldCheck,
  TriangleAlert,
  UserCheck,
} from "lucide-react"
import { memo, useId, type CSSProperties } from "react"

import { cn } from "@/lib/utils"

import type { AutomationPreviewStage } from "./automation-types"
import { primaryPlatform, WorkflowPlatformIcon } from "./workflow-platform-icon"

const MAX_VISIBLE_STAGES = 4
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
  const attentionIndex = summary.visible.findIndex((stage) => stage.needsAttention)

  if (!summary.visible.length) {
    return <p aria-label="Empty" className="flex min-h-20 items-center text-sm text-muted-foreground">Empty</p>
  }

  return (
    <div
      aria-label={accessibleSummary}
      className={cn("flex min-h-20 items-center", paused && "opacity-80")}
      data-flow-motion={paused ? "paused" : "active"}
      role="img"
    >
      <div aria-hidden="true" className="flex min-w-0 flex-1 items-start justify-between">
        {summary.visible.map((stage, index) => {
          const connectorActive = !paused && (attentionIndex < 0 || index < attentionIndex)
          return (
            <div className="contents" key={stage.nodeId}>
              {index ? <WorkflowConnector active={connectorActive} index={index} stage={stage} /> : null}
              <div className="relative flex w-12 shrink-0 flex-col items-center gap-1.5 text-center">
                <span
                  className={cn(
                    "grid size-[30px] place-items-center rounded-lg border shadow-xs ring-1 ring-inset ring-white/10",
                    stageStyle(stage),
                  )}
                  data-stage-category={stage.category}
                  data-stage-type={stage.nodeType}
                >
                  <StageIcon stage={stage} />
                </span>
                <span className="whitespace-nowrap text-[12px] leading-4 text-muted-foreground" title={stage.label}>
                  {workflowStageLabel(stage)}
                </span>
                {stage.needsAttention ? (
                  <span className="absolute end-0 top-[-3px] grid size-4 place-items-center rounded-full bg-[var(--error-surface)] text-destructive">
                    <TriangleAlert className="size-2.5" />
                  </span>
                ) : null}
              </div>
              {index === summary.collapseAfter && summary.hiddenCount ? (
                <div className="flex shrink-0 flex-col items-center gap-1.5 px-0.5">
                  <span className="grid h-[30px] min-w-7 place-items-center rounded-full border border-dashed bg-muted px-1 text-xs font-semibold text-muted-foreground">…</span>
                  <span className="text-[12px] leading-4 text-muted-foreground">+{summary.hiddenCount}</span>
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
})

function WorkflowConnector({ active, index, stage }: { active: boolean; index: number; stage: AutomationPreviewStage }) {
  const gradientId = useId().replace(/:/g, "")
  return (
    <span
      className={cn("workflow-connector relative mt-[11px] h-2 min-w-2 flex-1", connectorStyle(stage))}
      data-animated={active ? "true" : "false"}
      data-flow-connector
    >
      <svg className="h-full w-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 100 8">
        <defs>
          <linearGradient id={gradientId} x1="0" x2="1">
            <stop offset="0" stopColor="var(--border)" />
            <stop offset="0.58" stopColor="currentColor" stopOpacity="0.42" />
            <stop offset="1" stopColor="currentColor" stopOpacity="0.78" />
          </linearGradient>
        </defs>
        <path d="M3 4H97" fill="none" stroke={`url(#${gradientId})`} strokeLinecap="round" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
        <circle cx="3" cy="4" fill="var(--border)" r="1.35" />
        <circle cx="97" cy="4" fill="currentColor" opacity="0.72" r="1.45" />
        {active ? (
          <circle
            className="workflow-flow-particle"
            cx="3"
            cy="4"
            fill="currentColor"
            r="1.8"
            style={{ "--workflow-flow-delay": `${index * 0.55}s` } as CSSProperties}
          />
        ) : null}
      </svg>
    </span>
  )
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

function StageIcon({ stage }: { stage: AutomationPreviewStage }) {
  if (stage.platforms.length) return <WorkflowPlatformIcon platform={primaryPlatform(stage.platforms)} className="size-4" />
  const Icon = stage.nodeType === "manual" ? MousePointerClick
    : stage.nodeType === "schedule" ? Clock3
      : stage.nodeType === "new_source_item" ? Radio
      : stage.nodeType === "select_content" ? ListFilter
          : stage.nodeType === "filter_content" ? Filter
            : stage.nodeType === "research" ? Search
              : stage.nodeType === "generate_content_pack" ? Bot
                : stage.nodeType === "validate" ? ShieldCheck
                  : stage.nodeType === "human_review" ? UserCheck
                    : stage.nodeType === "save_drafts" ? FileCheck2
                      : stage.nodeType === "manual_package" ? Package
                        : CircleHelp
  return <Icon className="size-4" />
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
