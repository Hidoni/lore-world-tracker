/**
 * Shared recurrence types and the plan contract (recurrence.md §3–§4). The Python twin is
 * backend/src/lore/chronology/recurrence/plan.py.
 *
 * A plan maps each candidate period `k = 0, 1, …` to its positions: the time-ordered starts of the
 * occurrences the period can hold. Position `j` of period `k` has the key `k.j` when the rule can
 * select several positions per period, else `k`. A position whose finer fields don't exist
 * (`missing: skip`) is `null`: it has no occurrence but still consumes its `j`.
 */
import { add, durationUpperBound } from '../calendar/arithmetic'
import type { ValidationError } from '../calendar/compile'
import { type CompiledCalendar, bisectRight, defined } from '../calendar/compiled'
import type { Duration, EndSpec } from '../schema.gen'

export type RecurrenceErrorCode =
  'not_found' | 'rule.invalid' | 'rule.too_complex_to_count' | 'rule.too_many_positions'

/** Periods scanned around a moment before searching by counting. */
export const NEAR = 64n
/** Most candidate periods searched for one occurrence (first, last, next) or counted one by one. */
export const SCAN_LIMIT = 100_000n
/** Most positions one period may hold (`rule.too_many_positions` beyond). */
export const MAX_POSITIONS = 100_000n
/** `expand` gives up on items when the window has more than `maxItems * 4` candidates. */
export const TRUNCATE_FACTOR = 4n
/** Super-period counters kept per compiled regime (least recently used first out). */
export const COUNTER_CACHE = 64
/** Most periods `expand` visits; beyond, it estimates (sparse rules such as Fridays the 13th over
 * daily periods stay exact within it). */
export const ITERATE_LIMIT = 10_000n
/** Periods sampled to estimate the occurrences per period of rules that can't be counted. */
export const SAMPLES = 64n

/** A rule validation error (§9); `warning` only for `rule.series_start_not_occurrence`. */
export interface RuleValidationError extends ValidationError {
  readonly severity: 'error' | 'warning'
}

/** `not_found`, an invalid rule (`errors` lists why), or a rule too large to evaluate. */
export class RecurrenceError extends Error {
  constructor(
    readonly code: RecurrenceErrorCode,
    message: string,
    readonly errors: readonly RuleValidationError[] = [],
  ) {
    super(message)
    this.name = 'RecurrenceError'
  }
}

/** What a rule needs besides itself (recurrence.md §4 `ctx`). */
export interface RecurrenceContext {
  /** The resolved series start. */
  readonly seriesStart: bigint
  /** The series' end spec: the occurrence duration (`duration`, `instant` or `unknown`). */
  readonly end: EndSpec
  /** `D`: no occurrence starts after it. */
  readonly dimensionDuration: bigint
  /** The rule's calendar (and the calendar of a calendar duration). */
  readonly calendar?: CompiledCalendar | null
  /** Resolved moments of the rule's time points, by JSON pointer (`/limit/until`). */
  readonly resolved?: Readonly<Record<string, bigint | undefined>>
}

export interface Occurrence {
  readonly key: string
  readonly start: bigint
  readonly end: bigint
}

/** The conformance-vector form of an occurrence. */
export function occurrenceToJson(item: Occurrence): Record<string, string> {
  return { key: item.key, start: item.start.toString(), end: item.end.toString() }
}

/** A located position: (period `k`, index `j` in the period, start). */
export type Position = readonly [bigint, number, bigint]

const max = (a: bigint, b: bigint): bigint => (a > b ? a : b)
const min = (a: bigint, b: bigint): bigint => (a < b ? a : b)

/** Candidate periods `k ≥ 0`; positions of later periods start later. */
export abstract class Plan {
  /** Keys are `k.j` (the rule may select several positions per period). */
  multi = false
  /** Merged, sorted `[from, to)` ranges (set by the engine). */
  exclusions: [bigint, bigint][] = []
  exclusionStarts: bigint[] = []
  readonly duration: Duration | null

  constructor(
    readonly ctx: RecurrenceContext,
    /** The latest allowed start: `min(until, D)`, or the count limit's last start. */
    public last: bigint,
  ) {
    this.duration = ctx.end.kind === 'duration' ? ctx.end.duration : null
  }

  /** Period `k`'s positions in time order (ignoring the series bounds). */
  abstract positions(k: bigint): (bigint | null)[]

  /** Periods (`k ≥ 0`) whose positions may lie in `[low, high]`; empty if `lo > hi`. */
  abstract kRange(low: bigint, high: bigint): readonly [bigint, bigint]

  /** Every period has exactly one position with an occurrence. */
  abstract get dense(): boolean

  endOf(start: bigint): bigint {
    const duration = this.duration
    if (duration === null) return start
    if (duration.kind === 'calendar') return add(defined(this.ctx.calendar), start, duration)
    return start + BigInt(duration.units)
  }

  /** The occurrence length when it is the same for every occurrence. */
  exactLength(): bigint | null {
    const duration = this.duration
    if (duration === null) return 0n
    return duration.kind === 'calendar' ? null : BigInt(duration.units)
  }

  upperLength(): bigint {
    const duration = this.duration
    if (duration === null) return 0n
    if (duration.kind === 'calendar') {
      return durationUpperBound(defined(this.ctx.calendar), duration)
    }
    const units = BigInt(duration.units)
    return units < 0n ? -units : units
  }

  key(k: bigint, j: number): string {
    return this.multi ? `${k}.${j}` : String(k)
  }

  /** Period `k`'s occurrences within the series bounds, not excluded, in time order. */
  occurrences(k: bigint): Occurrence[] {
    const found: Occurrence[] = []
    this.positions(k).forEach((start, j) => {
      if (start !== null && this.happens(start)) {
        found.push({ key: this.key(k, j), start, end: this.endOf(start) })
      }
    })
    return found
  }

  /** A generated start is an occurrence: within the series bounds and not excluded. */
  happens(start: bigint): boolean {
    return this.ctx.seriesStart <= start && start <= this.last && this.exclusionAt(start) === null
  }

  // counting (§5.4): positions of all periods k ≥ 0, ignoring every bound

  /** `G(t)`: positions starting before `t`. */
  abstract countBefore(t: bigint): bigint

  /** The `i`-th position (1-based); `null` if there is none. */
  abstract position(i: bigint): Position | null

  /** Generated occurrences (`seriesStart ≤ start ≤ D`, exclusions included) before `t`; the
   * count limit applies to these. */
  generatedBefore(t: bigint): bigint {
    const limit = this.ctx.dimensionDuration + 1n
    return max(0n, this.countBefore(min(t, limit)) - this.countBefore(this.ctx.seriesStart))
  }

  /** Generated occurrences before `t` inside an exclusion. */
  excludedBefore(t: bigint): bigint {
    let total = 0n
    for (const [begin, to] of this.exclusions) {
      if (begin < t) {
        total += max(0n, this.generatedBefore(min(to, t)) - this.generatedBefore(min(begin, t)))
      }
    }
    return total
  }

  /** Occurrences (the series bounds and exclusions applied) starting before `t`. */
  actualBefore(t: bigint): bigint {
    t = min(t, this.last + 1n)
    return this.generatedBefore(t) - this.excludedBefore(t)
  }

  exclusionAt(t: bigint): readonly [bigint, bigint] | null {
    const index = bisectRight(this.exclusionStarts, t) - 1
    const found = this.exclusions[index]
    return found !== undefined && t < found[1] ? found : null
  }

  #occurrence([k, j, start]: Position): Occurrence {
    return { key: this.key(k, j), start, end: this.endOf(start) }
  }

  /** The first occurrence starting at or after `t`: nearby periods are scanned, far ones found by
   * counting; excluded starts jump to the end of their exclusion. */
  nextOccurrence(t: bigint): Occurrence | null {
    t = max(t, this.ctx.seriesStart)
    while (t <= this.last) {
      const found = this.#near(t, 1n) ?? this.position(this.countBefore(t) + 1n)
      if (found === null || found[2] > this.last) return null
      const exclusion = this.exclusionAt(found[2])
      if (exclusion === null) return this.#occurrence(found)
      t = exclusion[1]
    }
    return null
  }

  /** The last occurrence starting at or before `t`. */
  previousOccurrence(t: bigint): Occurrence | null {
    t = min(t, this.last)
    while (t >= this.ctx.seriesStart) {
      let found = this.#near(t, -1n)
      if (found === null) {
        const index = this.countBefore(t + 1n)
        if (index <= this.countBefore(this.ctx.seriesStart)) return null
        found = defined(this.position(index))
      }
      if (found[2] < this.ctx.seriesStart) return null
      const exclusion = this.exclusionAt(found[2])
      if (exclusion === null) return this.#occurrence(found)
      t = exclusion[0] - 1n
    }
    return null
  }

  /** The first position at or after `t` (`step` 1) or at or before it (-1) within `NEAR`
   * periods, or `null` if there is none that close. */
  #near(t: bigint, step: 1n | -1n): Position | null {
    const [low, high] = this.kRange(t, t)
    const k = step === 1n ? low : high
    for (let candidate = k; candidate !== k + step * NEAR; candidate += step) {
      if (candidate < 0n) return null
      const starts = this.positions(candidate)
      const order = starts.map((_, j) => j)
      if (step === -1n) order.reverse()
      for (const j of order) {
        const start = starts[j] ?? null
        if (start !== null && (step === 1n ? start >= t : start <= t)) return [candidate, j, start]
      }
    }
    return null
  }

  /** Occurrences in periods `kLo … kHi`: exact for dense plans, else sampled. */
  estimate(kLo: bigint, kHi: bigint): bigint {
    const count = kHi - kLo + 1n
    if (this.dense) return count
    const samples = min(count, SAMPLES)
    const ks = new Set<bigint>()
    const divisor = max(samples - 1n, 1n)
    for (let i = 0n; i < samples; i++) ks.add(kLo + (i * (count - 1n)) / divisor)
    let hits = 0n
    for (const k of ks) {
      for (const p of this.positions(k)) if (p !== null) hits++
    }
    return (count * hits) / BigInt(ks.size)
  }
}
