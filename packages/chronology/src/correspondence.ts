/**
 * Cross-dimension correspondences: mapping moments through sync points (time-model.md §12). The
 * Python twin is backend/src/lore/chronology/correspondence.py; both pass the vectors in
 * spec/chronology/conformance/cases/correspondences/.
 *
 * A correspondence relates dimension A to dimension B through resolved sync points `(a_i, b_i)`,
 * strictly increasing in both coordinates. Between consecutive points the mapping is linear with an
 * exact rational slope; outside them it is undefined (`extrapolation: none`) or continues with
 * `rateBefore` / `rateAfter` (B units per A unit). Results are floored to whole base units and must
 * lie in the target dimension's `[0, D]`; otherwise there is no corresponding moment.
 */
import type { ValidationError } from './calendar'
import { bisectRight, defined } from './calendar/compiled'
import { type BigRational, floorDiv, parseRational, rational } from './numbers'
import type { CorrespondenceDef } from './schema.gen'

export type Direction = 'ab' | 'ba'

/** A resolved sync point: `a` in dimension A happens at the same time as `b` in dimension B. */
export type SyncMoments = readonly [a: bigint, b: bigint]

export type CorrespondenceErrorCode =
  'correspondence.non_monotonic' | 'correspondence.bad_rate' | 'correspondence.missing_rate'

export interface CorrespondenceValidationError extends ValidationError {
  readonly code: CorrespondenceErrorCode
}

/** An invalid correspondence; `code` is the first error's, `errors` lists all. */
export class CorrespondenceError extends Error {
  readonly code: CorrespondenceErrorCode
  readonly errors: readonly CorrespondenceValidationError[]

  constructor(
    errors: readonly [CorrespondenceValidationError, ...CorrespondenceValidationError[]],
  ) {
    super(errors[0].message)
    this.name = 'CorrespondenceError'
    this.code = errors[0].code
    this.errors = errors
  }
}

export interface CorrespondenceOptions {
  readonly extrapolation?: 'none' | 'rate'
  readonly rateBefore?: BigRational | null
  readonly rateAfter?: BigRational | null
}

/** One side of the mapping: points sorted by `x`, and the extrapolation rates (y per x). */
interface Side {
  readonly xs: readonly bigint[]
  readonly ys: readonly bigint[]
  readonly before: BigRational | null
  readonly after: BigRational | null
}

const inverse = (rate: BigRational | null): BigRational | null =>
  rate === null ? null : rational(rate.den, rate.num)

/** A validated correspondence: points sorted by `a`, both rates set when extrapolating. */
export class Correspondence {
  readonly #ab: Side
  readonly #ba: Side

  constructor(
    readonly points: readonly SyncMoments[],
    readonly extrapolate: boolean,
    readonly rateBefore: BigRational | null,
    readonly rateAfter: BigRational | null,
  ) {
    const as = points.map(([a]) => a)
    const bs = points.map(([, b]) => b)
    this.#ab = { xs: as, ys: bs, before: rateBefore, after: rateAfter }
    this.#ba = { xs: bs, ys: as, before: inverse(rateBefore), after: inverse(rateAfter) }
  }

  /** §12.2: the moment corresponding to `t` (`mapAB` or `mapBA`), or `null`. */
  map(t: bigint, direction: Direction, targetDuration: bigint): bigint | null {
    const result = this.#map(direction === 'ab' ? this.#ab : this.#ba, t)
    return result !== null && result >= 0n && result <= targetDuration ? result : null
  }

  /** The moment of dimension B (duration `targetDuration`) at `a`, or `null`. */
  mapAB(a: bigint, targetDuration: bigint): bigint | null {
    return this.map(a, 'ab', targetDuration)
  }

  /** The moment of dimension A (duration `targetDuration`) at `b`, or `null`. */
  mapBA(b: bigint, targetDuration: bigint): bigint | null {
    return this.map(b, 'ba', targetDuration)
  }

  #map({ xs, ys, before, after }: Side, x: bigint): bigint | null {
    const last = xs.length - 1
    const firstX = defined(xs[0])
    const lastX = defined(xs[last])
    if (x < firstX) {
      if (!this.extrapolate || before === null) return null
      return defined(ys[0]) + floorDiv((x - firstX) * before.num, before.den)
    }
    if (x > lastX) {
      if (!this.extrapolate || after === null) return null
      return defined(ys[last]) + floorDiv((x - lastX) * after.num, after.den)
    }
    if (last === 0) return defined(ys[0]) // a single point, and x is that point
    const i = Math.min(bisectRight(xs, x) - 1, last - 1)
    const [x0, x1] = [defined(xs[i]), defined(xs[i + 1])]
    const [y0, y1] = [defined(ys[i]), defined(ys[i + 1])]
    return y0 + floorDiv((x - x0) * (y1 - y0), x1 - x0)
  }
}

interface Indexed {
  readonly index: number
  readonly point: SyncMoments
}

const compareA = ({ point: [a0] }: Indexed, { point: [a1] }: Indexed): number =>
  a0 < a1 ? -1 : a0 > a1 ? 1 : 0

/**
 * Validate resolved sync points and rates (§12.1); throws {@link CorrespondenceError}.
 *
 * Errors (paths into the correspondence document): `correspondence.non_monotonic` (points, sorted
 * by `a`, not strictly increasing in both `a` and `b`), `correspondence.bad_rate` (a rate `≤ 0`)
 * and `correspondence.missing_rate` (`rate` extrapolation from a single point without that side's
 * rate). Missing rates default to the adjacent segment's slope.
 */
export function validateCorrespondence(
  points: readonly SyncMoments[],
  options: CorrespondenceOptions = {},
): Correspondence {
  const { extrapolation = 'none' } = options
  let rateBefore = options.rateBefore ?? null
  let rateAfter = options.rateAfter ?? null
  const errors: CorrespondenceValidationError[] = []
  // A stable sort, so equal `a`s keep their document order (like Python's `sorted`).
  const order = points.map((point, index): Indexed => ({ index, point })).sort(compareA)
  for (let k = 1; k < order.length; k++) {
    const [a0, b0] = defined(order[k - 1]).point
    const { index, point } = defined(order[k])
    const [a1, b1] = point
    if (!(a0 < a1 && b0 < b1)) {
      errors.push({
        code: 'correspondence.non_monotonic',
        path: `/points/${index}`,
        message: 'sync points must increase strictly in both dimensions',
      })
    }
  }
  const rates = [
    ['rate_before', rateBefore],
    ['rate_after', rateAfter],
  ] as const
  for (const [member, rate] of rates) {
    if (rate !== null && rate.num <= 0n) {
      errors.push({
        code: 'correspondence.bad_rate',
        path: `/${member}`,
        message: 'a rate must be positive',
      })
    }
  }
  const sorted = order.map(({ point }) => point)
  const extrapolate = extrapolation === 'rate'
  if (extrapolate && sorted.length === 1) {
    for (const [member, rate] of rates) {
      if (rate === null) {
        errors.push({
          code: 'correspondence.missing_rate',
          path: `/${member}`,
          message: 'a single sync point needs explicit rates',
        })
      }
    }
  }
  const [first, ...rest] = errors
  if (first !== undefined) throw new CorrespondenceError([first, ...rest])
  if (extrapolate && sorted.length > 1) {
    const [[a0, b0], [a1, b1]] = [defined(sorted[0]), defined(sorted[1])]
    const [[a2, b2], [a3, b3]] = [defined(sorted.at(-2)), defined(sorted.at(-1))]
    rateBefore ??= rational(b1 - b0, a1 - a0)
    rateAfter ??= rational(b3 - b2, a3 - a2)
  }
  return new Correspondence(sorted, extrapolate, rateBefore, rateAfter)
}

/**
 * A correspondence document with its sync points resolved by the server
 * (`resolved["/points/<i>/a"]` and `…/b`).
 */
export function compileCorrespondence(
  definition: CorrespondenceDef,
  resolved: Readonly<Record<string, bigint>>,
): Correspondence {
  const moment = (path: string): bigint => {
    const value = Object.hasOwn(resolved, path) ? resolved[path] : undefined
    if (value === undefined) throw new Error(`sync point ${path} is not resolved`)
    return value
  }
  const points = definition.points.map((_, i): SyncMoments => [
    moment(`/points/${i}/a`),
    moment(`/points/${i}/b`),
  ])
  const rate = (value: CorrespondenceDef['rate_before']): BigRational | null =>
    value == null ? null : parseRational(value.num, value.den)
  return validateCorrespondence(points, {
    extrapolation: definition.extrapolation ?? 'none',
    rateBefore: rate(definition.rate_before),
    rateAfter: rate(definition.rate_after),
  })
}

/** One leg of a path: a correspondence, the direction to map it and the target's `D`. */
export interface Step {
  readonly correspondence: Correspondence
  readonly direction: Direction
  readonly targetDuration: bigint
}

/**
 * §12.3: map `t` along `path`, flooring at every step; `null` as soon as a step has no
 * corresponding moment. The path itself (e.g. the shortest one) is chosen by the caller.
 */
export function compose(path: readonly Step[], t: bigint): bigint | null {
  let current: bigint | null = t
  for (const { correspondence, direction, targetDuration } of path) {
    if (current === null) return null
    current = correspondence.map(current, direction, targetDuration)
  }
  return current
}
