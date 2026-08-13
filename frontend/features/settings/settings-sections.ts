import {
  Bot,
  BrainCircuit,
  Clock3,
  FileText,
  Send,
  Trash2,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

export const SETTINGS_RETURN_PATH_KEY = "newscraft.settings.return-path"
export const SETTINGS_RESTORE_FOCUS_KEY = "newscraft.settings.restore-focus"

export const settingsSections = [
  {
    id: "llm-providers",
    title: "LLM Providers",
    description: "OpenAI-compatible connections for generation and research.",
    icon: BrainCircuit,
    legacyHashes: ["llm-providers"],
  },
  {
    id: "codex",
    title: "Codex",
    description: "Pair trusted Codex clients and review connection activity.",
    icon: Bot,
    legacyHashes: ["codex", "codex-connection"],
  },
  {
    id: "telegram",
    title: "Telegram",
    description: "Destinations, bot credentials, proxies, and connection health.",
    icon: Send,
    legacyHashes: ["telegram", "telegram-destinations"],
  },
  {
    id: "date-time",
    title: "Date & Time",
    description: "Operator timezone and local timestamp presentation.",
    icon: Clock3,
    legacyHashes: ["date-time"],
  },
  {
    id: "retention",
    title: "Retention",
    description: "Data lifetimes, cleanup previews, and bounded retention runs.",
    icon: Trash2,
    legacyHashes: ["retention"],
  },
  {
    id: "prompts",
    title: "Prompts",
    description: "Versioned prompt templates, diffs, and activation history.",
    icon: FileText,
    legacyHashes: ["prompts", "prompt-governance"],
  },
] as const satisfies readonly {
  id: string
  title: string
  description: string
  icon: LucideIcon
  legacyHashes: readonly string[]
}[]

export type SettingsSectionId = (typeof settingsSections)[number]["id"]

export const defaultSettingsSection = settingsSections[0]

export function isSettingsSectionId(value: string | null): value is SettingsSectionId {
  return settingsSections.some((section) => section.id === value)
}

export function resolveSettingsSection(value: string | null) {
  return settingsSections.find((section) => section.id === value) ?? defaultSettingsSection
}

export function sectionFromLegacyHash(hash: string) {
  const normalized = decodeURIComponent(hash.replace(/^#/, ""))
  return settingsSections.find((section) =>
    section.legacyHashes.some((legacyHash) => legacyHash === normalized)
  )
}

export function settingsHref(section: SettingsSectionId = defaultSettingsSection.id) {
  return `/settings?section=${section}`
}

export function rememberSettingsReturnPath() {
  if (typeof window === "undefined") return
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
  if (window.location.pathname === "/settings" || window.location.pathname.startsWith("/settings/")) return
  window.sessionStorage.setItem(SETTINGS_RETURN_PATH_KEY, current)
}

export function consumeSettingsReturnPath() {
  if (typeof window === "undefined") return "/"
  const stored = window.sessionStorage.getItem(SETTINGS_RETURN_PATH_KEY)
  window.sessionStorage.removeItem(SETTINGS_RETURN_PATH_KEY)
  return stored && stored.startsWith("/") && !stored.startsWith("/settings") ? stored : "/"
}

export function hasRememberedSettingsReturnPath() {
  if (typeof window === "undefined") return false
  const stored = window.sessionStorage.getItem(SETTINGS_RETURN_PATH_KEY)
  return Boolean(stored && stored.startsWith("/") && !stored.startsWith("/settings"))
}

export function requestSettingsFocusRestoration() {
  if (typeof window === "undefined") return
  window.sessionStorage.setItem(SETTINGS_RESTORE_FOCUS_KEY, "true")
}
