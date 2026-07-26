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

export function camelize<Value>(value: Value): Camelized<Value> {
  if (Array.isArray(value)) return value.map(camelize) as Camelized<Value>
  if (value === null || typeof value !== "object") return value as Camelized<Value>
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key.replace(/_([a-z])/g, (_match, letter: string) => letter.toUpperCase()),
      camelize(item),
    ]),
  ) as Camelized<Value>
}
