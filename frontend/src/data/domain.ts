import type { components } from '@/api'
import type { MomentShape, MomentString } from '@/api/moment'
import { MOMENT_SHAPES } from '@/api/moments.gen'

type Schemas = components['schemas']

/**
 * Domain mapping (frontend.md §5.1): resolved moments are `bigint` after the data layer. API types
 * mark them `MomentString` (from the OpenAPI document); `Domain<T>` is `T` with each one a
 * `bigint`, and `toDomain` converts a response along the generated `MOMENT_SHAPES`. Time *specs*
 * stay JSON (strings), consumed by `@lore/chronology`.
 */
export type Domain<T> = T extends MomentString
  ? bigint
  : T extends readonly (infer U)[]
    ? Domain<U>[]
    : T extends object
      ? { [K in keyof T]: Domain<T[K]> }
      : T

const DECIMAL = /^(0|[1-9][0-9]*)$/

/** A moment string → `bigint` (what isn't one is left alone). */
function moment(value: unknown): unknown {
  return typeof value === 'string' && DECIMAL.test(value) ? BigInt(value) : value
}

function convert(value: unknown, shape: MomentShape): unknown {
  if (value === null || value === undefined) return value
  if (shape === 'm') return moment(value)
  if ('r' in shape) {
    const named = MOMENT_SHAPES[shape.r]
    return named === undefined ? value : convert(value, named)
  }
  if ('u' in shape) {
    let current: unknown = value
    for (const option of shape.u) current = convert(current, option)
    return current
  }
  if ('a' in shape)
    return Array.isArray(value) ? value.map((item) => convert(item, shape.a)) : value
  if (typeof value !== 'object' || Array.isArray(value)) return value
  const record = value as Record<string, unknown>
  if ('d' in shape) {
    return Object.fromEntries(Object.entries(record).map(([k, v]) => [k, convert(v, shape.d)]))
  }
  const copy: Record<string, unknown> = { ...record }
  for (const [key, inner] of Object.entries(shape.o)) {
    if (key in copy) copy[key] = convert(copy[key], inner)
  }
  return copy
}

/**
 * A response of an OpenAPI schema with its moments as `bigint` (schemas without moments come back
 * unchanged). The type comes from the schema name: response types from the client lose the
 * `MomentString` brand.
 */
export function toDomain<Name extends keyof Schemas>(
  value: unknown,
  schema: Name,
): Domain<Schemas[Name]> {
  const shape = MOMENT_SHAPES[schema]
  return (shape === undefined ? value : convert(value, shape)) as Domain<Schemas[Name]>
}

/** A value of type `T` with its moments, where `shape` says, as `bigint`. */
export function toDomainAs<T>(value: unknown, shape: MomentShape): Domain<T> {
  return convert(value, shape) as Domain<T>
}

/** A domain moment back on the wire. */
export function momentString(value: bigint): MomentString {
  if (value < 0n) throw new RangeError('moments are non-negative')
  return value.toString() as MomentString
}

/** Any `bigint` in a request body becomes its decimal string (moments are the only bigints). */
export function toWire<T>(value: T): T {
  if (typeof value === 'bigint') return value.toString() as T
  if (Array.isArray(value)) return value.map((item: unknown) => toWire(item)) as T
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, toWire(v)]),
    ) as T
  }
  return value
}

/**
 * Moments inside an entity's `ext` (kind-specific JSON that the OpenAPI document leaves open), per
 * kind. Module kinds add theirs when the KindRegistry lands (#60).
 */
export const EXT_MOMENTS: Readonly<Record<string, MomentShape>> = {
  event: {
    o: {
      start_t: 'm',
      end_t: 'm',
      series_start_t: 'm',
      series_end_t: 'm',
      original_start_t: 'm',
    },
  },
  dimension: { o: { duration: 'm', present_t: 'm' } },
  timeline: { o: { branch_t: 'm' } },
}

/** An entity (or anything with `kind` and `ext`) with the moments of its `ext` as `bigint`. */
export function entityToDomain<T extends { kind: string; ext?: unknown }>(entity: T): T {
  const shape = EXT_MOMENTS[entity.kind]
  if (shape === undefined || entity.ext === null || entity.ext === undefined) return entity
  return { ...entity, ext: convert(entity.ext, shape) }
}

const BIGINT_TAG = '$bigint'

/**
 * `JSON.stringify` can't serialize `bigint` (CLAUDE.md): these keep domain values (moments
 * included) through JSON, e.g. in `localStorage`, as `{"$bigint": "123"}`.
 */
export function bigintReplacer(_key: string, value: unknown): unknown {
  return typeof value === 'bigint' ? { [BIGINT_TAG]: value.toString() } : value
}

export function bigintReviver(_key: string, value: unknown): unknown {
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>
    const tagged = record[BIGINT_TAG]
    if (typeof tagged === 'string' && Object.keys(record).length === 1) {
      return BigInt(tagged)
    }
  }
  return value
}

export function stringifyDomain(value: unknown): string {
  return JSON.stringify(value, bigintReplacer)
}

export function parseDomain(text: string): unknown {
  return JSON.parse(text, bigintReviver) as unknown
}
