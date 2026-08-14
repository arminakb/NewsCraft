/**
 * Field-name policy for workflow node configuration.
 *
 * These lists are security- and integrity-relevant: "unsafe" fields are the
 * ones a workflow may never carry (credentials, prompt bodies, execution
 * environment), and the transient/identifier sets decide what survives a node
 * duplication. They live alone in this small module so they can be reviewed
 * without reading the graph editor around them.
 */

const TRANSIENT_DUPLICATE_KEYS = new Set([
  "data",
  "dragging",
  "execution",
  "executionresult",
  "executionresults",
  "execution_result",
  "execution_results",
  "handles",
  "handlebounds",
  "handleboundschange",
  "hidden",
  "measured",
  "position",
  "positionabsolute",
  "position_absolute",
  "resizing",
  "runtime",
  "runtimestate",
  "runtime_state",
  "selected",
  "temporary",
  "temporary_state",
  "temporaryuistate",
  "temporary_ui_state",
  "temp_ui_state",
  "temp_uistate",
  "uistate",
  "ui_state",
  "validation",
  "validationerror",
  "validation_error",
  "validationerrors",
  "validation_errors",
])
const INSTANCE_IDENTIFIER_KEYS = new Set(["instanceid", "instance_id"])
const HANDLE_IDENTIFIER_KEYS = new Set(["handleid", "handle_id", "handleids", "handle_ids"])

function normalizeFieldKey(fieldName: string) {
  return fieldName.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLocaleLowerCase()
}

/** Identifiers that must be re-minted, never copied, when a node is duplicated. */
export function isIdentifierField(fieldName: string) {
  const normalized = normalizeFieldKey(fieldName)
  return INSTANCE_IDENTIFIER_KEYS.has(normalized) || HANDLE_IDENTIFIER_KEYS.has(normalized)
}

/** Editor/runtime scratch state that must not be carried into a duplicate. */
export function isTransientDuplicateField(fieldName: string) {
  const normalized = normalizeFieldKey(fieldName)
  return TRANSIENT_DUPLICATE_KEYS.has(normalized) || TRANSIENT_DUPLICATE_KEYS.has(normalized.replaceAll("_", ""))
}

/** Credential and executable fields prohibited anywhere in a node config. */
export function isUnsafeWorkflowField(field: string) {
  return /(?:^|_)(?:api_key|authorization|credentials?|environment|filesystem|job_type|password|prompt_body|roles?|scopes?|secret|secret_ref|system_template|token|user_template)(?:_|$)/.test(normalizeFieldKey(field))
}

/** Path of the first unsafe field anywhere in `value`, or null. */
export function findUnsafeField(value: unknown, prefix = ""): string | null {
  if (!value || typeof value !== "object") return null
  for (const [key, item] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (isUnsafeWorkflowField(key)) return path
    const nested = findUnsafeField(item, path)
    if (nested) return nested
  }
  return null
}
