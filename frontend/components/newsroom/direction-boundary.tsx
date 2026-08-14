import {
  createElement,
  type ComponentPropsWithRef,
  type ElementType,
} from "react"

export type ContentDirection = "ltr" | "rtl" | "auto"

/**
 * Primary language subtags written right-to-left. Keyed by subtag because
 * the region and script suffixes ("fa-IR", "ar_EG") never change direction.
 */
const RIGHT_TO_LEFT_SUBTAGS: ReadonlySet<string> = new Set([
  "ar",
  "ckb",
  "dv",
  "fa",
  "he",
  "ps",
  "sd",
  "ug",
  "ur",
  "yi",
])

export type DirectionBoundaryProps<T extends ElementType = "div"> = {
  as?: T
  language?: string | null
  direction?: ContentDirection | null
} & Omit<ComponentPropsWithRef<T>, "as" | "dir" | "lang">

export function resolveContentDirection(
  language?: string | null,
  direction?: ContentDirection | null,
): { dir: ContentDirection; lang: string | undefined } {
  const candidate = language?.trim() ?? ""
  const primarySubtag = candidate.split(/[-_]/, 1)[0]?.toLowerCase()
  const lang = !candidate || primarySubtag === "und" ? undefined : candidate
  const inferred: ContentDirection = !lang
    ? "auto"
    : primarySubtag && RIGHT_TO_LEFT_SUBTAGS.has(primarySubtag)
      ? "rtl"
      : "ltr"

  return { dir: direction ?? inferred, lang }
}

export function DirectionBoundary<T extends ElementType = "div">({
  as,
  language,
  direction,
  ...props
}: DirectionBoundaryProps<T>) {
  const element = as ?? "div"
  const resolved = resolveContentDirection(language, direction)
  return createElement(element, {
    "data-testid": "direction-boundary",
    ...props,
    dir: resolved.dir,
    lang: resolved.lang,
  })
}
