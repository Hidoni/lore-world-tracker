/**
 * Structural validation of raw calendar documents against the JSON Schemas exported from the
 * Python models (chronology-engine.md §3.1, §11). The schemas come from `calendar-schema.gen.ts`;
 * this module interprets the keywords they use.
 *
 * Issues are located like the Python engine's (Pydantic) errors so that both engines report the
 * same `(code, path)` pairs: a missing member at the member, an unknown member at the member, a
 * failed union at the members of its best-fitting branches.
 */
import { CALENDAR_SCHEMA_DEFS } from '../calendar-schema.gen'
import { gcd } from '../numbers'

export type PathPart = string | number

/** One structural violation. `kind` drives the §11 code mapping and union-branch selection. */
export interface SchemaIssue {
  readonly path: readonly PathPart[]
  readonly kind: 'required' | 'additional' | 'too_long' | 'string_too_long' | 'invalid'
  /** The offending value (`undefined` for a missing member). */
  readonly value: unknown
}

interface SchemaNode {
  $ref?: string
  type?: string
  const?: unknown
  enum?: readonly unknown[]
  anyOf?: readonly SchemaNode[]
  oneOf?: readonly SchemaNode[]
  discriminator?: { propertyName: string; mapping: Readonly<Record<string, string>> }
  properties?: Readonly<Record<string, SchemaNode>>
  required?: readonly string[]
  additionalProperties?: boolean | SchemaNode
  patternProperties?: Readonly<Record<string, SchemaNode>>
  propertyNames?: SchemaNode
  minProperties?: number
  maxProperties?: number
  items?: SchemaNode
  minItems?: number
  maxItems?: number
  minLength?: number
  maxLength?: number
  pattern?: string
  minimum?: number
  maximum?: number
}

const DEFS = CALENDAR_SCHEMA_DEFS as Readonly<Record<string, SchemaNode>>
const RATIONAL_REF = '#/$defs/Rational'
const PATTERNS = new Map<string, RegExp>()

function regex(pattern: string): RegExp {
  let compiled = PATTERNS.get(pattern)
  if (compiled === undefined) {
    compiled = new RegExp(pattern, 'u')
    PATTERNS.set(pattern, compiled)
  }
  return compiled
}

function definition(ref: string): SchemaNode {
  const node = DEFS[ref.replace('#/$defs/', '')]
  if (node === undefined) throw new Error(`unknown schema reference ${ref}`)
  return node
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasType(value: unknown, type: string): boolean {
  switch (type) {
    case 'object':
      return isObject(value)
    case 'array':
      return Array.isArray(value)
    case 'string':
      return typeof value === 'string'
    case 'integer':
      return Number.isInteger(value)
    case 'boolean':
      return typeof value === 'boolean'
    case 'null':
      return value === null
    default:
      throw new Error(`unsupported schema type ${type}`)
  }
}

/** Every structural issue of `value` against the named definition (e.g. `CalendarDefinition`). */
export function checkDocument(name: string, value: unknown): SchemaIssue[] {
  return check(definition(`#/$defs/${name}`), value, [])
}

function check(node: SchemaNode, value: unknown, path: readonly PathPart[]): SchemaIssue[] {
  const invalid = (): SchemaIssue[] => [{ path, kind: 'invalid', value }]
  if (node.$ref !== undefined) {
    const issues = check(definition(node.$ref), value, path)
    // Rationals are normalized: a model rule of the Python schema, not expressible in JSON Schema.
    if (node.$ref === RATIONAL_REF && issues.length === 0) {
      const { num, den } = value as { num: string; den: string }
      if (gcd(BigInt(num), BigInt(den)) !== 1n) return invalid()
    }
    return issues
  }
  const union = node.oneOf ?? node.anyOf
  if (union !== undefined) return checkUnion(node, union, value, path)
  if (node.type !== undefined && !hasType(value, node.type)) return invalid()
  if ('const' in node && value !== node.const) return invalid()
  if (node.enum !== undefined && !node.enum.includes(value)) return invalid()
  if (typeof value === 'string') return checkString(node, value, path)
  if (typeof value === 'number') {
    const tooSmall = node.minimum !== undefined && value < node.minimum
    return tooSmall || (node.maximum !== undefined && value > node.maximum) ? invalid() : []
  }
  if (Array.isArray(value)) return checkArray(node, value, path)
  if (isObject(value)) return checkObject(node, value, path)
  return []
}

/** Length in code points, as JSON Schema (and Python) count string lengths. */
function codePoints(value: string): number {
  return value.replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, '_').length
}

function checkString(node: SchemaNode, value: string, path: readonly PathPart[]): SchemaIssue[] {
  const length = codePoints(value)
  if (node.maxLength !== undefined && length > node.maxLength) {
    return [{ path, kind: 'string_too_long', value }]
  }
  const tooShort = node.minLength !== undefined && length < node.minLength
  if (tooShort || (node.pattern !== undefined && !regex(node.pattern).test(value))) {
    return [{ path, kind: 'invalid', value }]
  }
  return []
}

function checkArray(
  node: SchemaNode,
  value: readonly unknown[],
  path: readonly PathPart[],
): SchemaIssue[] {
  if (node.maxItems !== undefined && value.length > node.maxItems) {
    return [{ path, kind: 'too_long', value }]
  }
  if (node.minItems !== undefined && value.length < node.minItems) {
    return [{ path, kind: 'invalid', value }]
  }
  const items = node.items
  return items === undefined ? [] : value.flatMap((item, i) => check(items, item, [...path, i]))
}

function checkObject(
  node: SchemaNode,
  value: Readonly<Record<string, unknown>>,
  path: readonly PathPart[],
): SchemaIssue[] {
  const keys = Object.keys(value)
  if (node.maxProperties !== undefined && keys.length > node.maxProperties) {
    return [{ path, kind: 'too_long', value }]
  }
  if (node.minProperties !== undefined && keys.length < node.minProperties) {
    return [{ path, kind: 'invalid', value }]
  }
  const issues: SchemaIssue[] = []
  for (const name of node.required ?? []) {
    if (!Object.hasOwn(value, name)) issues.push({ path: [...path, name], kind: 'required', value })
  }
  const patterns = Object.entries(node.patternProperties ?? {})
  for (const key of keys) {
    const at = [...path, key]
    const member = value[key]
    const properties = node.properties ?? {}
    const property = Object.hasOwn(properties, key) ? properties[key] : undefined
    if (property !== undefined) {
      issues.push(...check(property, member, at))
      continue
    }
    const nameIssues = node.propertyNames === undefined ? [] : check(node.propertyNames, key, at)
    if (nameIssues.length > 0) {
      issues.push({ path: at, kind: 'invalid', value: key })
      continue
    }
    const matching = patterns.filter(([pattern]) => regex(pattern).test(key))
    if (matching.length > 0) {
      for (const [, schema] of matching) issues.push(...check(schema, member, at))
    } else if (typeof node.additionalProperties === 'object') {
      issues.push(...check(node.additionalProperties, member, at))
    } else if (node.additionalProperties === false) {
      issues.push({ path: at, kind: 'additional', value: member })
    } else if (patterns.length > 0) {
      // A mapping with a key pattern (Python `dict[Id, …]`): keys must match it.
      issues.push({ path: at, kind: 'invalid', value: key })
    }
  }
  return issues
}

function checkUnion(
  node: SchemaNode,
  branches: readonly SchemaNode[],
  value: unknown,
  path: readonly PathPart[],
): SchemaIssue[] {
  const discriminator = node.discriminator
  if (discriminator !== undefined) {
    const tag = isObject(value) ? value[discriminator.propertyName] : undefined
    const ref = typeof tag === 'string' ? discriminator.mapping[tag] : undefined
    return ref === undefined
      ? [{ path, kind: 'invalid', value }]
      : check({ $ref: ref }, value, path)
  }
  const nullable = branches.some((branch) => branch.type === 'null')
  if (nullable && value === null) return []
  const candidates = branches.filter((branch) => branch.type !== 'null')
  const results = candidates.map((branch) => check(branch, value, path))
  if (results.some((issues) => issues.length === 0)) return []
  // Of the failed branches, keep those whose own shape fits the value (no missing or unknown
  // member directly inside it); if none fits, report them all.
  const depth = path.length + 1
  const fitting = results.filter((issues) => !issues.some((issue) => shapeIssue(issue, depth)))
  return (fitting.length > 0 ? fitting : results).flat()
}

function shapeIssue(issue: SchemaIssue, depth: number): boolean {
  return (issue.kind === 'required' || issue.kind === 'additional') && issue.path.length <= depth
}
