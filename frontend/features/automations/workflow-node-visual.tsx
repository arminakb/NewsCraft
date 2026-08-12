import {
  Clock,
  FileCheck,
  FileText,
  Filter,
  ListFilter,
  MessageSquare,
  MousePointerClick,
  Package,
  Radio,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  UserCheck,
  Workflow,
  type LucideIcon,
} from "lucide-react"

import type { AutomationResource, WorkflowNode } from "./automation-types"

const icons: Record<string, LucideIcon> = {
  clock: Clock,
  "file-check": FileCheck,
  "file-text": FileText,
  filter: Filter,
  "list-filter": ListFilter,
  "message-square": MessageSquare,
  "mouse-pointer-click": MousePointerClick,
  package: Package,
  radio: Radio,
  search: Search,
  send: Send,
  "shield-check": ShieldCheck,
  sparkles: Sparkles,
  "user-check": UserCheck,
}

const nodeTypeIcons: Record<string, string> = {
  manual: "mouse-pointer-click",
  collection_article_added: "file-text",
  new_source_item: "radio",
  schedule: "clock",
  select_content: "list-filter",
  filter_content: "filter",
  research: "search",
  generate_content_pack: "sparkles",
  validate: "shield-check",
  human_review: "user-check",
  save_drafts: "file-check",
  manual_package: "package",
  telegram_publish: "send",
  story_output: "file-check",
}

const compactNodeLabels: Record<string, string> = {
  manual: "Manual",
  collection_article_added: "Article",
  new_source_item: "New item",
  schedule: "Schedule",
  select_content: "Collect",
  filter_content: "Filter",
  research: "Research",
  generate_content_pack: "AI Generate",
  validate: "Validate",
  human_review: "Review",
  save_drafts: "Drafts",
  manual_package: "Publish",
  telegram_publish: "Telegram",
  story_output: "Output",
}

export const familyStyles: Record<string, string> = {
  trigger: "border-success/35 bg-[var(--success-surface)] text-success",
  research: "border-violet-500/35 bg-violet-500/10 text-violet-700 dark:text-violet-300",
  generate: "border-violet-500/35 bg-violet-500/10 text-violet-700 dark:text-violet-300",
  review: "border-violet-500/35 bg-violet-500/10 text-violet-700 dark:text-violet-300",
  select_filter: "border-primary/35 bg-accent text-accent-foreground",
  validate: "border-primary/35 bg-accent text-accent-foreground",
  output: "border-warning/35 bg-[var(--warning-surface)] text-warning",
}

export const familyIconStyles: Record<string, string> = {
  trigger: "text-success",
  research: "text-violet-700 dark:text-violet-300",
  generate: "text-violet-700 dark:text-violet-300",
  review: "text-violet-700 dark:text-violet-300",
  select_filter: "text-primary",
  validate: "text-primary",
  output: "text-warning",
}

export function nodeIcon(name: unknown): LucideIcon {
  return typeof name === "string" ? icons[name] ?? Workflow : Workflow
}

export function nodeTypeIcon(nodeType: string): LucideIcon {
  return nodeIcon(nodeTypeIcons[nodeType])
}

export function compactNodeLabel(nodeType: string, fallback: string) {
  return compactNodeLabels[nodeType] ?? fallback
}

export function familyLabel(family: string) {
  const labels: Record<string, string> = {
    trigger: "Trigger",
    select_filter: "Select & filter",
    research: "AI Research",
    generate: "Generate",
    validate: "Validate",
    review: "Review",
    output: "Output",
  }
  return labels[family] ?? family.replaceAll("_", " ")
}

export function configuredNodeLabel(
  node: Pick<WorkflowNode, "type" | "config">,
  fallback: string,
  resources: AutomationResource[] = [],
) {
  if (node.type === "new_source_item") {
    const sourceIds = Array.isArray(node.config.sourceIds)
      ? node.config.sourceIds.filter((value): value is string => typeof value === "string")
      : []
    if (!sourceIds.length) return "Select one or more sources"
    const sourceResources = resources.filter((resource) => resource.kind === "source")
    if (!sourceResources.length) return "Loading sources…"
    return sourceIds.map((sourceId) => (
      sourceResources.find((resource) => resource.id === sourceId)?.displayName ?? "Unavailable source"
    )).join(", ")
  }
  if (node.type !== "collection_article_added") return fallback
  const collectionId = typeof node.config.collectionId === "string" ? node.config.collectionId : ""
  if (!collectionId) return "Select a Feed collection"
  if (!resources.length) return "Loading Feed collection…"
  return resources.find((resource) => resource.kind === "collection" && resource.id === collectionId)?.displayName ?? "Unavailable collection"
}
