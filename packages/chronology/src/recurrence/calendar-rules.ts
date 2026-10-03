/**
 * Calendar rules: periods, filters, selectors and time of day (recurrence.md §2). The Python twin
 * is backend/src/lore/chronology/recurrence/calendar_rules.py.
 *
 * Periods are units of a level (`freq.level`) or rounds of a continuous cycle (`freq.cycle`),
 * counted in the regime in force at the series start and extended proleptically (§2.1). A period's
 * positions come from the selector path (or, for `select: null`, the series start's position), then
 * the finer fields from `time` or the series start, re-applied like calendar arithmetic.
 */
import { type Path, descend, reapplyOrNull } from '../calendar/arithmetic'
import { pointer } from '../calendar/compile'
import {
  type Child,
  type CompiledCalendar,
  childRegularIndex,
  type CompiledCycle,
  type CompiledRegime,
  type CompiledTemplate,
  DateError,
  type Segment,
  activeRegime,
  defined,
  isNumber,
} from '../calendar/compiled'
import { type Overflow, findChild } from '../calendar/convert'
import { regimeCycleValue } from '../calendar/cycles'
import {
  REGULAR,
  type UnitFilter,
  countedPosition,
  cycleFilter,
  fromCountedOrdinal,
  unitsPerPeriod,
} from '../calendar/units'
import { floorDiv, floorMod } from '../numbers'
import type { CalendarRule, CycleMatch, LevelSelector, PeriodFilter } from '../schema.gen'
import { type Counter, TooComplex, counterFor } from './counting'
import {
  COUNTER_CACHE,
  ITERATE_LIMIT,
  MAX_POSITIONS,
  Plan,
  type Position,
  type RecurrenceContext,
  RecurrenceError,
  type RuleValidationError,
  SCAN_LIMIT,
} from './plan'

/** A segment of a located template: `segment.count` identical units from `start`. */
interface Run {
  readonly start: bigint
  readonly segment: Segment
}

/** A located unit: its start moment and template. */
interface Unit {
  readonly start: bigint
  readonly template: CompiledTemplate
}

/** Orders distinct moments. */
const byTime = (a: bigint, b: bigint): number => (a < b ? -1 : 1)

function tooManyPositions(): RecurrenceError {
  return new RecurrenceError('rule.too_many_positions', 'too many positions')
}

/** §3: at most one position per period, decided syntactically. A slot id is unique only within
 * one template, so at a level that skips levels it may match several units. */
function single(rule: CalendarRule, levels: readonly string[], period: number): boolean {
  if (rule.select == null) return true
  let above = period
  for (const selector of rule.select.path) {
    const level = levels.indexOf(selector.level)
    if ('all' in selector) return false
    if ('values' in selector) {
      const [value] = selector.values
      if (selector.values.length !== 1 || (!isNumber(value) && level < above - 1)) return false
    }
    if ('cycle' in selector) {
      const nth = selector.cycle.nth
      if (selector.cycle.values.length !== 1 || nth?.length !== 1) return false
    }
    above = level
  }
  return true
}

/** The cycle index a rule value names: an id from `ids` or the number `n`. */
function cycleIndex(cycle: CompiledCycle, value: string): number | null {
  if (isNumber(value)) {
    const index = Number(BigInt(value) - BigInt(cycle.numberStart))
    return index >= 0 && index < cycle.length ? index : null
  }
  const index = cycle.ids?.indexOf(value) ?? -1
  return index < 0 ? null : index
}

/** A position in a round: a cycle id or number, negative numbers from the end. */
function roundIndex(cycle: CompiledCycle, value: string): number | null {
  if (isNumber(value) && BigInt(value) < 0n) {
    const index = BigInt(cycle.length) + BigInt(value)
    return index >= 0n ? Number(index) : null
  }
  return cycleIndex(cycle, value)
}

function findCycle(regime: CompiledRegime, cycleId: string): CompiledCycle | null {
  return regime.cycles.find((c) => c.id === cycleId) ?? null
}

// --- validation (§9) -----------------------------------------------------------------------------

class Checker {
  readonly errors: RuleValidationError[] = []

  constructor(
    readonly rule: CalendarRule,
    readonly calendar: CompiledCalendar,
    readonly regime: CompiledRegime,
  ) {}

  error(code: string, path: string, message: string): void {
    this.errors.push({ code, path, message, severity: 'error' })
  }

  /** Slot ids of the children at `level` in any template of the regime. */
  slots(level: number): Set<string> {
    const found = new Set<string>()
    for (const template of this.regime.templates.values()) {
      if (template.level === level + 1) for (const slot of template.slots.keys()) found.add(slot)
    }
    return found
  }

  run(): RuleValidationError[] {
    const { rule, calendar } = this
    const levels = calendar.levels
    let period: number
    let cycle: CompiledCycle | null = null
    if ('level' in rule.freq) {
      period = levels.indexOf(rule.freq.level)
      if (period < 0) {
        this.error('rule.bad_freq_level', '/freq/level', 'unknown level')
        return this.errors
      }
    } else {
      cycle = findCycle(this.regime, rule.freq.cycle)
      if (cycle === null) {
        this.error('rule.bad_freq_level', '/freq/cycle', 'unknown cycle')
        return this.errors
      }
      if (cycle.reset !== null) {
        this.error('rule.cycle_not_continuous', '/freq/cycle', 'a reset cycle has no rounds')
        return this.errors
      }
      period = cycle.level
    }
    ;(rule.filters ?? []).forEach((item, i) => {
      this.filter(item, pointer('filters', i), period, cycle)
    })
    let deepest = period
    const path = rule.select?.path ?? []
    for (const [i, selector] of path.entries()) {
      const at = pointer('select', 'path', i)
      const level = levels.indexOf(selector.level)
      // Rounds select their own units first; every other selector is strictly finer than the
      // one before (or the period), and may skip levels (day 256 of a year).
      const fits = cycle !== null && i === 0 ? level === deepest : level >= 0 && level < deepest
      if (!fits) {
        this.error('rule.bad_selector_level', at + '/level', 'not a finer level')
        return this.errors
      }
      this.selector(selector, at, level, i === 0 ? cycle : null)
      deepest = level
    }
    this.time(deepest)
    return this.errors
  }

  filter(item: PeriodFilter, path: string, period: number, rounds: CompiledCycle | null): void {
    if ('mod' in item) {
      if (BigInt(item.eq) >= BigInt(item.mod)) {
        this.error('rule.bad_filter', path + '/eq', 'eq must be below mod')
      }
    } else if ('cycle' in item) {
      const cycle = findCycle(this.regime, item.cycle)
      if (rounds !== null || cycle?.level !== period) {
        this.error('rule.bad_filter', path + '/cycle', 'not a cycle of the period level')
        return
      }
      this.cycleValues(cycle, item.in, path + '/in', cycleIndex)
    } else if ('in' in item) {
      if (rounds !== null) {
        this.error('rule.bad_filter', path, 'cycle rounds have no number or slot')
        return
      }
      const known = this.slots(period)
      item.in.forEach((value, j) => {
        if (!isNumber(value) && !known.has(value)) {
          this.error('rule.unknown_slot', `${path}/in/${j}`, 'unknown slot')
        }
      })
    } else if ('all' in item || 'any' in item) {
      const member = 'all' in item ? 'all' : 'any'
      const items = 'all' in item ? item.all : item.any
      items.forEach((child, j) => {
        this.filter(child, `${path}/${member}/${j}`, period, rounds)
      })
    } else {
      this.filter(item.not, path + '/not', period, rounds)
    }
  }

  /** Values naming cycle positions: ids or numbers (in rounds, negative from the end). */
  cycleValues(
    cycle: CompiledCycle,
    values: readonly string[],
    path: string,
    index: (cycle: CompiledCycle, value: string) => number | null,
  ): void {
    values.forEach((value, j) => {
      if (index(cycle, value) === null) {
        this.error('rule.unknown_slot', `${path}/${j}`, `no value ${value} in the cycle`)
      }
    })
  }

  selector(
    selector: LevelSelector,
    path: string,
    level: number,
    rounds: CompiledCycle | null,
  ): void {
    if ('values' in selector) {
      if (rounds !== null) {
        this.cycleValues(rounds, selector.values, path + '/values', roundIndex)
        return
      }
      const known = this.slots(level)
      selector.values.forEach((value, j) => {
        if (!isNumber(value) && !known.has(value)) {
          this.error('rule.unknown_slot', `${path}/values/${j}`, 'unknown slot')
        }
      })
    } else if ('cycle' in selector) {
      const cycle = findCycle(this.regime, selector.cycle.id)
      if (cycle?.level !== level) {
        this.error('rule.bad_selector_level', path + '/cycle/id', 'no such cycle here')
        return
      }
      this.cycleValues(cycle, selector.cycle.values, path + '/cycle/values', cycleIndex)
      ;(selector.cycle.nth ?? []).forEach((nth, j) => {
        if (nth === '0')
          this.error('rule.bad_nth', `${path}/cycle/nth/${j}`, 'nth counts from 1 or -1')
      })
    }
  }

  time(deepest: number): void {
    const time = this.rule.time
    if (time == null) return
    const levels = this.calendar.levels
    const keys = Object.keys(time.fields)
    const bad = keys.filter((key) => {
      const index = levels.indexOf(key)
      return index < 0 || index >= deepest
    })
    for (const key of bad) {
      this.error('rule.bad_time_fields', pointer('time', 'fields', key), 'not below')
    }
    const indexes = keys
      .filter((key) => !bad.includes(key))
      .map((key) => levels.indexOf(key))
      .sort((a, b) => a - b)
    const contiguous = indexes.every((index, i) => index === defined(indexes[0]) + i)
    if (bad.length === 0 && (indexes.length === 0 || !contiguous)) {
      this.error('rule.bad_time_fields', '/time/fields', 'time fields must be contiguous')
    }
  }
}

/** §9 errors of a calendar rule (the regime is the one in force at the series start). */
export function calendarRuleErrors(
  rule: CalendarRule,
  calendar: CompiledCalendar,
  seriesStart: bigint,
): RuleValidationError[] {
  return new Checker(rule, calendar, activeRegime(calendar, seriesStart)).run()
}

// --- plan ----------------------------------------------------------------------------------------

const UNSET = Symbol('unset')

/** An LRU cache stored on the compiled regime (`COUNTER_CACHE` entries). */
function regimeCache<T>(regime: CompiledRegime, name: string): Map<string, T> {
  let cache = regime.cache.get(name) as Map<string, T> | undefined
  if (cache === undefined) {
    cache = new Map<string, T>()
    regime.cache.set(name, cache)
  }
  return cache
}

function touch<T>(cache: Map<string, T>, key: string, value: T): void {
  cache.delete(key)
  cache.set(key, value)
  if (cache.size > COUNTER_CACHE) cache.delete(defined(cache.keys().next().value))
}

export class CalendarPlan extends Plan {
  readonly top: number
  readonly regime: CompiledRegime
  readonly interval: bigint
  readonly overflow: Overflow
  /** Time-of-day values by level index (`null`: from the series start). */
  readonly time: ReadonlyMap<number, string> | null
  readonly origin: Path
  readonly rounds: CompiledCycle | null
  readonly level: number
  readonly unitFilter: UnitFilter
  readonly roundBase: bigint
  readonly p0: bigint
  /** For rounds: the series start's index in its round (`select: null`). */
  readonly startIndex: bigint
  /** Positions per period when constant (`null`: they vary). */
  readonly perPeriod: bigint | null
  counter: Counter | null | typeof UNSET = UNSET
  readonly #cacheKey: string

  constructor(
    readonly rule: CalendarRule,
    ctx: RecurrenceContext,
    readonly calendar: CompiledCalendar,
    last: bigint,
  ) {
    super(ctx, last)
    this.top = calendar.levels.length - 1
    this.regime = activeRegime(calendar, ctx.seriesStart)
    this.interval = BigInt(rule.interval ?? '1')
    this.overflow = rule.missing === 'constrain' ? 'constrain' : 'reject'
    this.time =
      rule.time == null
        ? null
        : new Map(
            Object.entries(rule.time.fields).map(([key, value]) => [
              calendar.levelIndex(key),
              defined(value),
            ]),
          )
    this.origin = descend(calendar, this.regime, ctx.seriesStart, 0)
    if ('cycle' in rule.freq) {
      const cycleId = rule.freq.cycle
      const rounds = defined(findCycle(this.regime, cycleId))
      this.rounds = rounds
      this.level = rounds.level
      this.unitFilter = cycleFilter(rounds.id)
      // continuous (validated)
      this.roundBase = defined(rounds.anchorOrdinal) - BigInt(rounds.anchorIndex)
    } else {
      this.rounds = null
      this.level = calendar.levelIndex(rule.freq.level)
      this.unitFilter = REGULAR
      this.roundBase = 0n
    }
    // Rounds: the first selector picks units of the round, as if one level up.
    const above = this.rounds !== null ? this.level + 1 : this.level
    this.multi = !single(rule, calendar.levels, above)
    this.#cacheKey = `${JSON.stringify(rule)}\u0000${ctx.seriesStart}`
    const counted = this.#counted(ctx.seriesStart)
    this.p0 = this.#periodOf(counted)
    this.startIndex = counted - this.#firstCounted(this.p0)
    this.perPeriod = this.#perPeriod()
  }

  // periods

  /** Counted ordinal of the `level` unit at `t` (or of the counted unit before it). */
  #counted(t: bigint): bigint {
    const [before, counted] = countedPosition(this.top, this.regime, t, this.level, this.unitFilter)
    return counted ? before : before - 1n
  }

  #periodOf(counted: bigint): bigint {
    if (this.rounds === null) return counted
    return floorDiv(counted - this.roundBase, BigInt(this.rounds.length))
  }

  #firstCounted(period: bigint): bigint {
    if (this.rounds === null) return period
    return this.roundBase + period * BigInt(this.rounds.length)
  }

  kRange(low: bigint, high: bigint): readonly [bigint, bigint] {
    const pLow = this.#periodOf(this.#counted(low))
    const pHigh = this.#periodOf(this.#counted(high))
    const kLo = -floorDiv(this.p0 - pLow, this.interval)
    return [kLo > 0n ? kLo : 0n, floorDiv(pHigh - this.p0, this.interval)]
  }

  get dense(): boolean {
    return this.perPeriod === 1n
  }

  /**
   * The number of positions every period holds, when it is the same for all of them.
   *
   * Without filters, cycle selectors or rounds, a period's positions depend only on its unit's
   * template; if every template of the level gives the same count, `S(k)` is that count times `k`
   * (0: the rule never occurs).
   */
  #perPeriod(): bigint | null {
    const rule = this.rule
    const cyclic = (rule.select?.path ?? []).some((selector) => 'cycle' in selector)
    if (this.rounds !== null || (rule.filters ?? []).length > 0 || cyclic) return null
    if (unitsPerPeriod(this.regime, this.level, this.top) === 0n) return null
    const counts = new Set<bigint>()
    for (const template of this.regime.templates.values()) {
      if (template.level !== this.level) continue
      let found: (bigint | null)[]
      try {
        found = this.#unitPositions(0n, [{ start: 0n, template }])
      } catch (error) {
        if (error instanceof RecurrenceError) return null
        throw error
      }
      counts.add(BigInt(found.filter((p) => p !== null).length))
    }
    return counts.size === 1 ? defined([...counts][0]) : null
  }

  /** The counted `level` unit with this ordinal. */
  #unit(counted: bigint): Unit {
    const levelId = defined(this.calendar.levels[this.level])
    const { start } = fromCountedOrdinal(this.calendar, levelId, counted, this.unitFilter, {
      regime: this.regime.id,
    })
    return { start, template: descend(this.calendar, this.regime, start, this.level).template }
  }

  positions(k: bigint): (bigint | null)[] {
    const period = this.p0 + k * this.interval
    let units: Unit[]
    try {
      if (this.rounds === null) {
        const unit = this.#unit(period)
        if (!this.#passes(period, unit)) return []
        units = [unit]
      } else {
        if (!(this.rule.filters ?? []).every((f) => this.#passesRound(f, period))) return []
        units = []
      }
    } catch (error) {
      if (error instanceof DateError) return [] // no counted unit has this ordinal
      throw error
    }
    if (this.rule.select == null && this.rounds !== null) {
      units = [this.#unit(this.#firstCounted(period) + this.startIndex)]
    }
    return this.#unitPositions(period, units)
  }

  /** The positions inside the period (its unit, or nothing yet for a round). */
  #unitPositions(period: bigint, units: Unit[]): (bigint | null)[] {
    const select = this.rule.select
    if (select == null) return units.map((unit) => this.#tail(unit, this.level))
    const selected = this.#select(period, units)
    const deepest = this.calendar.levelIndex(defined(select.path.at(-1)).level)
    return selected.map((unit) => this.#tail(unit, deepest))
  }

  // counting (§5.4)

  periodCount(k: bigint): bigint {
    let count = 0n
    for (const p of this.positions(k)) if (p !== null) count++
    return count
  }

  /** `S(k)` by enumerating periods, with the prefix kept on the regime (per rule and series
   * start) so repeated queries near the start stay cheap. */
  #enumerated(k: bigint): bigint {
    const cache = regimeCache<bigint[]>(this.regime, 'recurrence-prefixes')
    const prefix = cache.get(this.#cacheKey) ?? [0n]
    touch(cache, this.#cacheKey, prefix)
    while (BigInt(prefix.length) <= k) {
      prefix.push(defined(prefix.at(-1)) + this.periodCount(BigInt(prefix.length - 1)))
    }
    return defined(prefix[Number(k)])
  }

  /** The super-period counter, cached on the regime (per rule and series start). */
  counterOf(build = true): Counter | null {
    if (this.counter === UNSET) {
      const cache = regimeCache<Counter | null>(this.regime, 'recurrence-counters')
      if (cache.has(this.#cacheKey)) {
        this.counter = cache.get(this.#cacheKey) ?? null
        touch(cache, this.#cacheKey, this.counter)
      } else if (!build) {
        return null
      } else {
        this.counter = counterFor(this)
        touch(cache, this.#cacheKey, this.counter)
      }
    }
    return this.counter
  }

  /** `S(k)`: positions in periods `0 … k-1`. Small `k` are enumerated (cheaper than a
   * super-period), large ones counted (`rule.too_complex_to_count` if impossible). */
  #countPeriods(k: bigint): bigint {
    if (this.perPeriod !== null) return this.perPeriod * k
    const counter = this.counterOf(k > ITERATE_LIMIT)
    if (counter !== null) {
      try {
        return counter.count(k)
      } catch (error) {
        if (!(error instanceof TooComplex)) throw error
        this.counter = null
      }
    }
    if (k > SCAN_LIMIT) {
      throw new RecurrenceError('rule.too_complex_to_count', 'counting needs super-periods')
    }
    return this.#enumerated(k)
  }

  countBefore(t: bigint): bigint {
    const [k] = this.kRange(t, t)
    let partial = 0n
    for (const p of this.positions(k)) if (p !== null && p < t) partial++
    return this.#countPeriods(k) + partial
  }

  position(i: bigint): Position | null {
    const k = this.#periodHolding(i)
    if (k === null) return null
    let rank = i - this.#countPeriods(k)
    for (const [j, start] of this.positions(k).entries()) {
      if (start !== null && --rank === 0n) return [k, j, start]
    }
    /* v8 ignore next */
    throw new Error('chronology engine invariant violated: no such position')
  }

  /** The period of the `i`-th position (1-based). */
  #periodHolding(i: bigint): bigint | null {
    if (this.perPeriod !== null) return this.perPeriod > 0n ? (i - 1n) / this.perPeriod : null
    let counter = this.counterOf(false)
    if (counter === null) {
      // nearby positions: enumerate
      if (this.#enumerated(ITERATE_LIMIT) >= i) return this.#firstPeriodReaching(i, ITERATE_LIMIT)
      counter = this.counterOf()
    }
    if (counter !== null) {
      try {
        return counter.periodOf(i)
      } catch (error) {
        if (!(error instanceof TooComplex)) throw error
        this.counter = null
      }
    }
    if (this.#enumerated(SCAN_LIMIT) >= i) return this.#firstPeriodReaching(i, SCAN_LIMIT)
    throw new RecurrenceError('rule.too_complex_to_count', 'counting needs super-periods')
  }

  /** The period holding the `i`-th position, known to be below `limit`. */
  #firstPeriodReaching(i: bigint, limit: bigint): bigint {
    let low = 0n
    let high = limit
    while (low < high) {
      // smallest k with S(k + 1) ≥ i
      const middle = (low + high) / 2n
      if (this.#enumerated(middle + 1n) >= i) high = middle
      else low = middle + 1n
    }
    return low
  }

  // filters (§2.2)

  #passes(period: bigint, unit: Unit): boolean {
    return (this.rule.filters ?? []).every((f) => this.#filter(f, period, unit))
  }

  #filter(item: PeriodFilter, period: bigint, unit: Unit): boolean {
    if ('mod' in item) {
      const value = item.of === 'ordinal' ? period : this.#number(unit)[0]
      return floorMod(value, BigInt(item.mod)) === BigInt(item.eq)
    }
    if ('cycle' in item) {
      const cycle = defined(findCycle(this.regime, item.cycle))
      const found = regimeCycleValue(this.top, this.regime, cycle, unit.start)
      return found !== null && item.in.some((v) => cycleIndex(cycle, v) === found.index)
    }
    if ('in' in item) {
      const [number, slot] = this.#number(unit)
      return item.in.some((v) => (isNumber(v) ? BigInt(v) === number : v === slot))
    }
    if ('all' in item) return item.all.every((f) => this.#filter(f, period, unit))
    if ('any' in item) return item.any.some((f) => this.#filter(f, period, unit))
    return !this.#filter(item.not, period, unit)
  }

  /** Rounds: `mod` filters (number = ordinal = the round ordinal) and combinations. */
  #passesRound(item: PeriodFilter, period: bigint): boolean {
    if ('mod' in item) return floorMod(period, BigInt(item.mod)) === BigInt(item.eq)
    if ('all' in item) return item.all.every((f) => this.#passesRound(f, period))
    if ('any' in item) return item.any.some((f) => this.#passesRound(f, period))
    // in/cycle filters on rounds are invalid (validated)
    return !this.#passesRound((item as { not: PeriodFilter }).not, period)
  }

  /** (regular number within the parent, slot id) of a period unit; the top level: `Y`. */
  #number(unit: Unit): readonly [bigint, string | null] {
    const path = descend(this.calendar, this.regime, unit.start, this.level)
    if (this.level === this.top) return [path.year, null]
    const [, child] = defined(path.children.at(-1))
    // periods are regular units
    const regular = defined(childRegularIndex(child))
    return [regular + defined(this.calendar.numberingStarts[this.level]), child.segment.slotId]
  }

  // selectors (§2.3)

  #select(period: bigint, units: Unit[]): Unit[] {
    let path: readonly LevelSelector[] = defined(this.rule.select).path
    if (this.rounds !== null) {
      units = this.#selectRound(period, defined(path[0]))
      path = path.slice(1)
    }
    for (const selector of path) {
      const level = this.calendar.levelIndex(selector.level)
      const chosen: Unit[] = []
      for (const unit of units) {
        chosen.push(...this.#selectChildren(unit, selector, level))
        if (BigInt(chosen.length) > MAX_POSITIONS) throw tooManyPositions()
      }
      units = chosen
    }
    return units
  }

  #selectRound(period: bigint, selector: LevelSelector): Unit[] {
    const cycle = defined(this.rounds)
    const length = cycle.length
    const first = this.#firstCounted(period)
    let indexes: number[]
    if ('all' in selector) {
      indexes = Array.from({ length }, (_, i) => i)
    } else if ('values' in selector) {
      const found = new Set<number>()
      for (const v of selector.values) found.add(defined(roundIndex(cycle, v))) // validated
      indexes = [...found].sort((a, b) => a - b)
    } else {
      const match = selector.cycle
      const other = defined(findCycle(this.regime, match.id))
      const units = Array.from({ length }, (_, i) => this.#unit(first + BigInt(i)))
      const values = units.map((u) => regimeCycleValue(this.top, this.regime, other, u.start))
      const found = new Set<number>()
      for (const value of match.values) {
        const wanted = cycleIndex(other, value)
        const hits = values.flatMap((v, i) => (v !== null && v.index === wanted ? [i] : []))
        for (const hit of nthOf(hits, match.nth)) found.add(hit)
      }
      return [...found].sort((a, b) => a - b).map((i) => defined(units[i]))
    }
    /* v8 ignore next */
    if (BigInt(indexes.length) > MAX_POSITIONS) throw tooManyPositions()
    return indexes.map((i) => this.#unit(first + BigInt(i)))
  }

  /** The runs of `level` units inside `unit`, in time order (its children when `level` is the
   * next level down, else every descendant run). */
  #runs(unit: Unit, level: number): Run[] {
    const runs: Run[] = []
    const walk = (start: bigint, template: CompiledTemplate): void => {
      for (const segment of template.segments) {
        const first = start + segment.start
        if (template.level - 1 === level) {
          runs.push({ start: first, segment })
          continue
        }
        const child = this.regime.template(defined(segment.child))
        if (BigInt(runs.length) + segment.count * this.#runCount(child, level) > MAX_POSITIONS) {
          throw tooManyPositions()
        }
        for (let i = 0n; i < segment.count; i++) walk(first + i * segment.childLength, child)
      }
    }
    walk(unit.start, unit.template)
    return runs
  }

  #runCount(template: CompiledTemplate, level: number): bigint {
    const key = `runs\u0000${template.id}\u0000${level}`
    let cached = this.regime.cache.get(key) as bigint | undefined
    if (cached === undefined) {
      if (template.level - 1 === level) {
        cached = BigInt(template.segments.length)
      } else {
        cached = 0n
        for (const segment of template.segments) {
          const child = this.regime.template(defined(segment.child))
          cached += segment.count * this.#runCount(child, level)
        }
      }
      this.regime.cache.set(key, cached)
    }
    return cached
  }

  #unitAt(run: Run, i: bigint): Unit {
    const start = run.start + i * run.segment.childLength
    return { start, template: this.regime.template(defined(run.segment.child)) }
  }

  /** The `level` units inside `unit` that `selector` picks, in time order. Numbers count the
   * regular `level` units of `unit` from the level's numbering start (negative: from the end);
   * slot ids, `all` and cycle matches look at every `level` unit in it. */
  #selectChildren(unit: Unit, selector: LevelSelector, level: number): Unit[] {
    const runs = this.#runs(unit, level)
    if ('cycle' in selector) return this.#cycleChildren(runs, selector.cycle)
    const regular = runs.filter((run) => !run.segment.intercalary)
    const total = regular.reduce((sum, run) => sum + run.segment.count, 0n)
    if ('all' in selector) {
      if (total > MAX_POSITIONS) throw tooManyPositions()
      return regular.flatMap((run) =>
        Array.from({ length: Number(run.segment.count) }, (_, i) => this.#unitAt(run, BigInt(i))),
      )
    }
    const chosen = new Map<bigint, Unit>()
    const numbering = defined(this.calendar.numberingStarts[level])
    for (const value of selector.values) {
      if (isNumber(value)) {
        const n = BigInt(value)
        const index = n < 0n ? total + n : n - numbering
        if (index >= 0n && index < total) {
          const [run, i] = nthUnit(regular, index)
          const found = this.#unitAt(run, i)
          chosen.set(found.start, found)
        }
      } else {
        for (const run of runs) {
          if (run.segment.slotId === value) chosen.set(run.start, this.#unitAt(run, 0n))
        }
      }
    }
    return [...chosen.keys()].sort(byTime).map((start) => defined(chosen.get(start)))
  }

  /** Units whose cycle value matches, per value with optional `nth` (arithmetic over each run:
   * the cycle indexes of a run's units are consecutive). */
  #cycleChildren(runs: Run[], match: CycleMatch): Unit[] {
    const cycle = defined(findCycle(this.regime, match.id))
    const counted: [Run, number][] = []
    for (const run of runs) {
      const found = regimeCycleValue(this.top, this.regime, cycle, run.start)
      if (found !== null) counted.push([run, found.index])
    }
    const chosen = new Map<bigint, Unit>()
    for (const value of match.values) {
      const wanted = defined(cycleIndex(cycle, value)) // validated
      for (const [run, i] of new CycleHits(counted, wanted, cycle.length).select(match.nth)) {
        const unit = this.#unitAt(run, i)
        chosen.set(unit.start, unit)
        if (BigInt(chosen.size) > MAX_POSITIONS) throw tooManyPositions()
      }
    }
    return [...chosen.keys()].sort(byTime).map((start) => defined(chosen.get(start)))
  }

  // finer positions (§2.4)

  /** The occurrence start inside the selected `level` unit, or `null` when a finer position
   * doesn't exist (`missing: skip`). */
  #tail(unit: Unit, level: number): bigint | null {
    const { calendar, regime, time } = this
    let start = unit.start
    let template = unit.template
    const finest = time === null ? null : Math.min(...time.keys())
    for (let lower = level - 1; lower >= 0; lower--) {
      // below the time fields: the start of the deepest timed unit
      if (finest !== null && lower < finest) return start
      const value = time?.get(lower)
      let child: Child | null
      if (value !== undefined) {
        child = findChild(calendar, regime, template, lower, value, this.overflow)
      } else {
        const [parent, original] = defined(this.origin.children[this.top - 1 - lower])
        child = reapplyOrNull(template, parent, original, this.overflow)
      }
      if (child === null) return null
      start += child.offset
      template = regime.template(defined(child.segment.child))
    }
    if (time !== null) return start
    let base = this.origin.offset
    if (base >= template.length) {
      if (this.overflow === 'reject') return null
      base = template.length - 1n
    }
    return start + base
  }
}

function nthOf(hits: readonly number[], nth: readonly string[] | null | undefined): number[] {
  if (nth == null) return [...hits]
  const chosen: number[] = []
  for (const item of nth) {
    const n = Number(item)
    const index = n > 0 ? n - 1 : hits.length + n
    if (index >= 0 && index < hits.length) chosen.push(defined(hits[index]))
  }
  return chosen
}

/** The run and position of the `index`-th unit over `runs`. */
function nthUnit(runs: readonly Run[], index: bigint): readonly [Run, bigint] {
  for (const run of runs) {
    if (index < run.segment.count) return [run, index]
    index -= run.segment.count
  }
  /* v8 ignore next */
  throw new Error('chronology engine invariant violated: no such unit')
}

/** The units with one cycle index, over runs whose first unit has a known index. */
class CycleHits {
  readonly #firsts: bigint[]
  readonly #counts: bigint[]
  readonly #length: bigint

  constructor(
    readonly runs: readonly (readonly [Run, number])[],
    wanted: number,
    length: number,
  ) {
    this.#length = BigInt(length)
    this.#firsts = runs.map(([, first]) => BigInt((((wanted - first) % length) + length) % length))
    this.#counts = runs.map(([run], i) => {
      const f = defined(this.#firsts[i])
      return f >= run.segment.count ? 0n : (run.segment.count - 1n - f) / this.#length + 1n
    })
  }

  #at(index: bigint): readonly [Run, bigint] {
    for (const [i, [run]] of this.runs.entries()) {
      const count = defined(this.#counts[i])
      if (index < count) return [run, defined(this.#firsts[i]) + index * this.#length]
      index -= count
    }
    /* v8 ignore next */
    throw new Error('chronology engine invariant violated: no such hit')
  }

  *select(nth: readonly string[] | null | undefined): Generator<readonly [Run, bigint]> {
    const total = this.#counts.reduce((sum, count) => sum + count, 0n)
    let indexes: Iterable<bigint>
    if (nth == null) {
      if (total > MAX_POSITIONS) throw tooManyPositions()
      indexes = (function* () {
        for (let i = 0n; i < total; i++) yield i
      })()
    } else {
      indexes = nth.map((item) => {
        const n = BigInt(item)
        return n > 0n ? n - 1n : total + n
      })
    }
    for (const index of indexes) if (index >= 0n && index < total) yield this.#at(index)
  }
}
