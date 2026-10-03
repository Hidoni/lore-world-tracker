/**
 * Counting positions of calendar rules with super-periods (recurrence.md §5.4). The Python twin is
 * backend/src/lore/chronology/recurrence/counting.py.
 *
 * `n(k)` is the number of positions of candidate period `k` (`null` positions excluded) and
 * `S(K) = Σ_{k<K} n(k)`. Inside a stretch of years without calendar exceptions, `n` is periodic in
 * `k`: shifting `k` by the **super-period** `Q` shifts time by `M` whole periods of the top
 * pattern, which preserves the calendar structure, the interval alignment, every `mod` filter's
 * residue and the phase of every continuous cycle the rule uses. Periods that overlap an exception
 * year are counted one by one; every clean stretch gets the prefix sums of its own first `Q`
 * periods (after an exception, ordinals and cycle phases may be shifted). The total number of
 * periods enumerated is limited (`ENUM_LIMIT`, `rule.too_complex_to_count` beyond).
 */
import { bisectLeft, defined } from '../calendar/compiled'
import { cycleFilter, unitsPerPeriod } from '../calendar/units'
import { floorDiv, gcd } from '../numbers'
import type { PeriodFilter } from '../schema.gen'
import type { CalendarPlan } from './calendar-rules'

/** Most candidate periods enumerated to build the counts (one super-period, exception years and
 * short stretches together). */
export const ENUM_LIMIT = 1_000_000n

/** The rule can't be counted by super-periods (aperiodic, or too many periods to enumerate). An
 * internal signal, not an error for callers. */
export class TooComplex extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'TooComplex'
  }
}

/** Periods `[start, end)` (`end` `null`: unbounded) with their counts. */
class Segment {
  /** Counts before each of the first periods (length = enumerated periods + 1). */
  prefix: bigint[] = []
  /** `prefix` covers one super-period and repeats over the whole segment. */
  periodic = false

  constructor(
    readonly start: bigint,
    readonly end: bigint | null,
    /** The periods overlap exception years: always counted one by one. */
    readonly dirty = false,
  ) {}

  total(q: bigint): bigint {
    return this.upto(defined(this.end) - this.start, q)
  }

  upto(length: bigint, q: bigint): bigint {
    if (!this.periodic) return defined(this.prefix[Number(length)])
    const full = floorDiv(length, q)
    return full * defined(this.prefix.at(-1)) + defined(this.prefix[Number(length - full * q)])
  }
}

/** The smallest `M ≥ 1` with `M·a ≡ 0 (mod b)`. */
function needs(a: bigint, b: bigint): bigint {
  return b / gcd(a, b)
}

function lcm(values: readonly bigint[]): bigint {
  return values.reduce((a, b) => (a / gcd(a, b)) * b, 1n)
}

/** Index of the first prefix entry `≥ value` (prefixes are non-decreasing). */
function firstReaching(prefix: readonly bigint[], value: bigint): bigint {
  return BigInt(bisectLeft(prefix, value))
}

export class Counter {
  enumerated = 0n
  readonly q: bigint
  readonly segments: readonly Segment[]
  /** `S` at the start of each segment whose predecessors are summed so far. */
  readonly #before: bigint[] = [0n]

  constructor(readonly plan: CalendarPlan) {
    this.q = this.#superPeriod()
    this.segments = this.#segments()
  }

  // super-period

  #superPeriod(): bigint {
    const plan = this.plan
    const { regime, top } = plan
    const found: bigint[] = []
    const cycles = new Set<string>()
    let units: bigint
    let stepSize: bigint
    if (plan.rounds === null) {
      units = unitsPerPeriod(regime, plan.level, top)
      found.push(needs(units, plan.interval))
      stepSize = 1n
    } else {
      cycles.add(plan.rounds.id)
      units = unitsPerPeriod(regime, plan.level, top, cycleFilter(plan.rounds.id))
      stepSize = BigInt(plan.rounds.length)
      found.push(needs(units, stepSize * plan.interval))
    }
    for (const item of plan.rule.filters ?? []) {
      this.#filterNeeds(item, found, cycles, units, stepSize)
    }
    for (const selector of plan.rule.select?.path ?? []) {
      if ('cycle' in selector) cycles.add(selector.cycle.id)
    }
    for (const cycle of regime.cycles) {
      if (cycles.has(cycle.id) && cycle.reset === null) {
        const counted = unitsPerPeriod(regime, cycle.level, top, cycleFilter(cycle.id))
        found.push(needs(counted, BigInt(cycle.length)))
      }
    }
    if (units === 0n) throw new TooComplex('the period level has no units in the regular pattern')
    const q = (lcm(found) * units) / (stepSize * plan.interval)
    if (q > ENUM_LIMIT) throw new TooComplex(`a super-period holds ${q} candidate periods`)
    return q
  }

  #filterNeeds(
    item: PeriodFilter,
    found: bigint[],
    cycles: Set<string>,
    units: bigint,
    size: bigint,
  ): void {
    const plan = this.plan
    if ('mod' in item) {
      const mod = BigInt(item.mod)
      if (item.of === 'ordinal' || plan.rounds !== null) found.push(needs(units, size * mod))
      else if (plan.level === plan.top) found.push(needs(plan.regime.period, mod))
    } else if ('cycle' in item) {
      cycles.add(item.cycle)
    } else if ('in' in item) {
      if (plan.level === plan.top)
        throw new TooComplex('an `in` filter on year numbers is not periodic')
    } else if ('all' in item || 'any' in item) {
      for (const child of 'all' in item ? item.all : item.any) {
        this.#filterNeeds(child, found, cycles, units, size)
      }
    } else {
      this.#filterNeeds(item.not, found, cycles, units, size)
    }
  }

  // segments

  /** Exception-affected period ranges and the clean stretches between them, in order. */
  #segments(): Segment[] {
    const { plan } = this
    const regime = plan.regime
    const dirty: [bigint, bigint][] = []
    for (const year of regime.exceptionYears) {
      const low = regime.yearStart(year)
      const high = regime.yearStart(year + 1n) - 1n
      let [kLo, kHi] = plan.kRange(low, high)
      // a period straddling the year boundary
      kLo = kLo - 1n > 0n ? kLo - 1n : 0n
      kHi += 1n
      if (kHi < 0n) continue
      const previous = dirty.at(-1)
      if (previous !== undefined && kLo <= previous[1] + 1n) {
        if (kHi > previous[1]) previous[1] = kHi
      } else {
        dirty.push([kLo, kHi])
      }
    }
    const segments: Segment[] = []
    let position = 0n
    for (const [kLo, kHi] of dirty) {
      if (kLo > position) segments.push(new Segment(position, kLo))
      segments.push(new Segment(kLo, kHi + 1n, true))
      position = kHi + 1n
    }
    segments.push(new Segment(position, null))
    return segments
  }

  #counts(start: bigint, length: bigint): bigint[] {
    this.enumerated += length
    if (this.enumerated > ENUM_LIMIT) throw new TooComplex('too many periods to enumerate')
    const prefix = [0n]
    let total = 0n
    for (let k = start; k < start + length; k++) {
      for (const p of this.plan.positions(k)) if (p !== null) total++
      prefix.push(total)
    }
    return prefix
  }

  #fill(segment: Segment): void {
    if (segment.prefix.length > 0) return
    const length = segment.end === null ? null : segment.end - segment.start
    if (length !== null && (segment.dirty || length <= 2n * this.q)) {
      segment.prefix = this.#counts(segment.start, length)
    } else {
      segment.prefix = this.#counts(segment.start, this.q)
      segment.periodic = true
    }
  }

  // queries

  /** `S` at the start of segment `index` (summing earlier segments as needed). */
  #segmentStarts(index: number): bigint {
    while (this.#before.length <= index) {
      const segment = defined(this.segments[this.#before.length - 1])
      this.#fill(segment)
      this.#before.push(defined(this.#before.at(-1)) + segment.total(this.q))
    }
    return defined(this.#before[index])
  }

  #segmentOf(k: bigint): number {
    return (
      bisectLeft(
        this.segments.map((segment) => segment.start),
        k + 1n,
      ) - 1
    )
  }

  /** `S(k)`: positions in periods `0 … k-1`. */
  count(k: bigint): bigint {
    const index = this.#segmentOf(k)
    const segment = defined(this.segments[index])
    this.#fill(segment)
    return this.#segmentStarts(index) + segment.upto(k - segment.start, this.q)
  }

  /** The period holding the `i`-th position (1-based), `null` if there is none. */
  periodOf(i: bigint): bigint | null {
    for (const [index, segment] of this.segments.entries()) {
      this.#fill(segment)
      const base = this.#segmentStarts(index)
      if (segment.end !== null) {
        if (base + segment.total(this.q) >= i)
          return segment.start + this.#within(segment, i - base)
        continue
      }
      // an unbounded segment is always periodic
      const per = defined(segment.prefix.at(-1))
      if (per === 0n) return null
      const full = floorDiv(i - base - 1n, per)
      const rest = i - base - 1n - full * per
      return segment.start + full * this.q + firstReaching(segment.prefix, rest + 1n) - 1n
    }
    /* v8 ignore next */
    return null
  }

  /** Offset of the period holding the `r`-th position of a bounded segment. */
  #within(segment: Segment, r: bigint): bigint {
    if (!segment.periodic) return firstReaching(segment.prefix, r) - 1n
    const per = defined(segment.prefix.at(-1))
    const full = floorDiv(r - 1n, per)
    const rest = r - 1n - full * per
    return full * this.q + firstReaching(segment.prefix, rest + 1n) - 1n
  }
}

/** The plan's counter, or `null` when its rule can't be counted by super-periods. */
export function counterFor(plan: CalendarPlan): Counter | null {
  try {
    return new Counter(plan)
  } catch (error) {
    if (error instanceof TooComplex) return null
    throw error
  }
}
