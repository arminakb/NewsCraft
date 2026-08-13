type CamelCase<Value extends string> =
  Value extends `${infer Head}_${infer Tail}`
    ? `${Head}${Capitalize<CamelCase<Tail>>}`
    : Value

export type Camelized<Value> =
  Value extends readonly (infer Item)[]
    ? Camelized<Item>[]
    : Value extends Record<string, unknown>
      ? { [Key in keyof Value as Key extends string ? CamelCase<Key> : Key]: Camelized<Value[Key]> }
      : Value

// Fields whose VALUE is a free-form map keyed by caller-supplied identifiers
// (workflow node ids, prompt version ids) or captured verbatim from an external
// service. Those child keys are data, not contract field names, so neither
// direction of the case conversion may rewrite them — a node id such as
// `generate_content_pack_1` must survive read → save byte-for-byte, and a
// Telegram API response must keep its own `message_id` spelling. This is the
// single table; features/automations/automation-api.ts snakeize() consumes it
// for the outbound direction.
export const FREE_FORM_MAP_FIELDS: ReadonlySet<string> = new Set([
  "layout",
  "promptChecksums",
  "prompt_checksums",
  "responseMetadata",
  "response_metadata",
])

export function camelize<Value>(value: Value): Camelized<Value> {
  return camelizeValue(value, false) as Camelized<Value>
}

function camelizeValue(value: unknown, preserveKeys: boolean): unknown {
  if (Array.isArray(value)) return value.map((item) => camelizeValue(item, preserveKeys))
  if (value === null || typeof value !== "object") return value
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      preserveKeys ? key : key.replace(/_([a-z])/g, (_match, letter: string) => letter.toUpperCase()),
      camelizeValue(item, FREE_FORM_MAP_FIELDS.has(key)),
    ]),
  )
}
