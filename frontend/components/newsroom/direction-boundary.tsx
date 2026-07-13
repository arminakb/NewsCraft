import {
  createElement,
  type ComponentPropsWithRef,
  type ElementType,
} from "react"

export type ContentDirection = "ltr" | "rtl" | "auto"

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
    : primarySubtag === "fa" || primarySubtag === "ar"
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
    ...props,
    "data-testid": "direction-boundary",
    dir: resolved.dir,
    lang: resolved.lang,
  })
}
