// Deliberate exception to the `camelize()` decoding rule.
//
// Every other feature client decodes backend payloads with lib/camelize.ts,
// which trusts the generated OpenAPI types. Package payloads are LLM-authored
// content packs whose shape is only as trustworthy as the model that produced
// them, so they are validated field by field at runtime — an unexpected or
// missing key must fail loudly here rather than reach the editor as `undefined`.
// Do not "simplify" this module into camelize(); do not copy its style into
// clients that consume ordinary, schema-backed endpoints.

import { safeHttpUrl } from "@/lib/url"

const UUID_PATTERN =/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256_PATTERN = /^[0-9a-f]{64}$/

export function exactObject<const K extends string>(
  value: unknown,
  keys: readonly K[],
  message: string,
): Record<K, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(message)
  const row = value as Record<string, unknown>
  const actual = Object.keys(row)
  if (actual.length !== keys.length || actual.some((key) => !keys.includes(key as K))) throw new Error(message)
  return row as Record<K, unknown>
}

export function array(value: unknown, message: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(message)
  return value
}

export function string(value: unknown, message: string, allowEmpty = false): string {
  if (typeof value !== "string" || (!allowEmpty && value.trim().length === 0)) throw new Error(message)
  return value
}

export function nullableString(value: unknown, message: string, allowEmpty = false): string | null {
  return value === null ? null : string(value, message, allowEmpty)
}

export function stringArray(value: unknown, message: string, allowEmpty = false): string[] {
  return array(value, message).map((item) => string(item, message, allowEmpty))
}

export function boolean(value: unknown, message: string): boolean {
  if (typeof value !== "boolean") throw new Error(message)
  return value
}

export function positiveInteger(value: unknown, message: string): number {
  if (!Number.isInteger(value) || (value as number) < 1) throw new Error(message)
  return value as number
}

export function nonNegativeInteger(value: unknown, message: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) throw new Error(message)
  return value as number
}

export function nullableNonNegativeInteger(value: unknown, message: string): number | null {
  return value === null ? null : nonNegativeInteger(value, message)
}

export function uuid(value: unknown, message: string): string {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) throw new Error(message)
  return value
}

export function nullableUuid(value: unknown, message: string): string | null {
  return value === null ? null : uuid(value, message)
}

export function sha256(value: unknown, message: string): string {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) throw new Error(message)
  return value
}

export function httpUrl(value: unknown, message: string): string {
  if (typeof value !== "string" || safeHttpUrl(value) === null) throw new Error(message)
  return value
}

export function nullableHttpUrl(value: unknown, message: string): string | null {
  return value === null ? null : httpUrl(value, message)
}

export function timestamp(value: unknown, message: string): string {
  const text = string(value, message)
  if (Number.isNaN(new Date(text).getTime()) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(text)) throw new Error(message)
  return text
}

export function nullableTimestamp(value: unknown, message: string): string | null {
  return value === null ? null : timestamp(value, message)
}

export function safeRelativePath(value: unknown, message: string): string {
  const path = string(value, message)
  const parts = path.split("/")
  if (
    path.startsWith("/")
    || path.includes("\\")
    || parts.some((part) => !part || part === "." || part === ".." || !/^[A-Za-z0-9._-]+$/.test(part))
  ) throw new Error(message)
  return path
}

export function oneOf<const T extends readonly string[]>(
  value: unknown,
  choices: T,
  message: string,
): T[number] {
  if (typeof value !== "string" || !choices.includes(value)) throw new Error(message)
  return value as T[number]
}

export function sameStringArray(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index])
}
