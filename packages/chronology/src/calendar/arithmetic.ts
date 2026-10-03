/**
 * Calendar arithmetic: add, diff and duration bounds (chronology-engine.md §9). The Python twin is
 * backend/src/lore/chronology/calendar/arithmetic.py.
 *
 * Durations are applied level by level from the coarsest to the finest. **Uniform** levels (every
 * template of the level, in every regime, has the same length) add exact base units, so the
 * intercalary units they contain are counted like any other. **Variable** levels use ordinal
 * arithmetic in the regime active at the current moment, extended proleptically past that regime's
 * end (§7): the target unit is `n` regular units away (intercalary units are skipped), and the
 * finer positions are re-applied inside it, constrained where they don't exist. Every step jumps
 * with ordinals and prefix sums; nothing iterates over units or years.
 */
import { floorDiv } from '../numbers'
import type { CalendarDuration, Duration } from '../schema.gen'
import {
  type Child,
  type CompiledCalendar,
  type CompiledRegime,
  type CompiledTemplate,
  DateError,
  activeRegime,
  childRegularIndex,
  defined,
} from './compiled'
import type { Overflow } from './convert'
import { REGULAR, countedPosition, fromCountedOrdinal } from './units'

/** The result of `diff`: `t2 − t1` in calendar units (chronology-engine §9.3). */
export interface Difference {
  /** Every level from `largest` down to `smallest` (coarse to fine), each `≥ 0`. */
  readonly amounts: ReadonlyMap<string, bigint>
  /** Base units left over below `smallest` (`≥ 0`). */
  readonly base: bigint
  /** `-1` when `t1 > t2` (the amounts then measure `t1 − t2`). */
  readonly sign: 1 | -1
}

/** The conformance-vector form of a `Difference`. */
export function differenceToJson(found: Difference): Record<string, unknown> {
  const amounts = Object.fromEntries([...found.amounts].map(([level, n]) => [level, n.toString()]))
  return { amounts, base: found.base.toString(), sign: found.sign }
}

/** The amounts of a `Difference` as a calendar duration (the base remainder is not included). */
export function differenceDuration(found: Difference, calendarId: string): CalendarDuration {
  const amounts = Object.fromEntries([...found.amounts].map(([level, n]) => [level, n.toString()]))
  return { kind: 'calendar', calendar_id: calendarId, amounts, sign: found.sign }
}

// --- levels --------------------------------------------------------------------------------------

function levelOf(calendar: CompiledCalendar, level: string): number {
  const index = calendar.levelIndex(level)
  if (index < 0) throw new DateError('invalid_date', `unknown level ${level}`, level)
  return index
}

function templatesOf(calendar: CompiledCalendar, level: number): CompiledTemplate[] {
  return calendar.regimes.flatMap((regime) =>
    [...regime.templates.values()].filter((template) => template.level === level),
  )
}

function uniformLength(calendar: CompiledCalendar, level: number): bigint | null {
  const lengths = new Set(templatesOf(calendar, level).map((template) => template.length))
  return lengths.size === 1 ? defined([...lengths][0]) : null
}

/** §9.1: every template of `level`, in every regime, has the same length. */
export function isUniform(calendar: CompiledCalendar, level: string): boolean {
  return uniformLength(calendar, levelOf(calendar, level)) !== null
}

/** (level index, amount) for the non-zero amounts, coarsest level first. */
function ordered(calendar: CompiledCalendar, duration: CalendarDuration): [number, bigint][] {
  const amounts: [number, bigint][] = []
  for (const [level, amount] of Object.entries(duration.amounts)) {
    const n = BigInt(defined(amount))
    const index = levelOf(calendar, level)
    if (n !== 0n) amounts.push([index, n])
  }
  return amounts.sort(([a], [b]) => b - a)
}

const abs = (n: bigint): bigint => (n < 0n ? -n : n)

// --- add -----------------------------------------------------------------------------------------

/**
 * §9.2: `t` moved by `duration`. The result may lie outside `[0, D]`. With `overflow: 'reject'`,
 * a step that has to constrain a position (31 January + 1 month, a slot missing from the target
 * unit) throws `invalid_date` instead.
 */
export function add(
  calendar: CompiledCalendar,
  t: bigint,
  duration: Duration,
  overflow: Overflow = 'constrain',
): bigint {
  if (duration.kind === 'base') return t + BigInt(duration.units)
  const sign = BigInt(duration.sign)
  for (const [level, amount] of ordered(calendar, duration)) {
    t = step(calendar, t, level, sign * amount, overflow)
  }
  return t
}

/** Move `t` by `n` (signed) units of one level. */
function step(
  calendar: CompiledCalendar,
  t: bigint,
  level: number,
  n: bigint,
  overflow: Overflow,
): bigint {
  if (n === 0n) return t
  const length = uniformLength(calendar, level)
  if (length !== null) return t + n * length
  return variableStep(calendar, activeRegime(calendar, t), t, level, n, overflow)
}

/** The units containing a moment, from the top level down to some level. */
export interface Path {
  /** The year containing the moment. */
  readonly year: bigint
  /** (parent template, child) per level below the top, coarse to fine. */
  readonly children: readonly (readonly [CompiledTemplate, Child])[]
  /** The template of the unit at the lowest level reached. */
  readonly template: CompiledTemplate
  /** `t` minus the start of the unit at the lowest level reached. */
  readonly offset: bigint
}

/** The path to the `level` unit containing `t` in `regime` (proleptically). */
export function descend(
  calendar: CompiledCalendar,
  regime: CompiledRegime,
  t: bigint,
  level: number,
): Path {
  const top = calendar.levels.length - 1
  const rel = t - regime.epoch
  const year = regime.yearOfRel(rel)
  let template = regime.yearTemplate(year)
  let offset = rel - regime.relStart(year)
  const children: (readonly [CompiledTemplate, Child])[] = []
  for (let child = top - 1; child >= level; child--) {
    const found = template.childAt(offset)
    children.push([template, found])
    offset -= found.offset
    template = regime.template(defined(found.segment.child))
  }
  return { year, children, template, offset }
}

function variableStep(
  calendar: CompiledCalendar,
  regime: CompiledRegime,
  t: bigint,
  level: number,
  n: bigint,
  overflow: Overflow,
): bigint {
  const top = calendar.levels.length - 1
  const origin = descend(calendar, regime, t, 0)
  const [before, counted] = countedPosition(top, regime, t, level, REGULAR)
  // Inside an intercalary unit (between regular units before-1 and before), one unit forward is
  // the next regular unit and one unit back the previous one.
  const target = before + n - (!counted && n > 0n ? 1n : 0n)
  const levelId = defined(calendar.levels[level])
  let start = fromCountedOrdinal(calendar, levelId, target, REGULAR, { regime: regime.id }).start
  let template = descend(calendar, regime, start, level).template
  for (const [parent, child] of origin.children.slice(top - level)) {
    const placed = reapply(calendar, template, parent, child, overflow)
    start += placed.offset
    template = regime.template(defined(placed.segment.child))
  }
  let base = origin.offset
  if (base >= template.length) {
    if (overflow === 'reject') {
      throw new DateError(
        'invalid_date',
        "the base remainder doesn't fit",
        defined(calendar.levels[0]),
      )
    }
    base = template.length - 1n
  }
  return start + base
}

/**
 * The child of `template` at the position `child` had in `parent` (§9.2). The same slot id if
 * `template` has it, else the same regular number constrained to the last one; an intercalary
 * position missing from `template` becomes the last regular child before its original index (or
 * the first regular child). Anything but the same slot id or the same number is a constraining
 * step, which `reject` refuses.
 */
export function reapply(
  calendar: CompiledCalendar,
  template: CompiledTemplate,
  parent: CompiledTemplate,
  child: Child,
  overflow: Overflow,
): Child {
  const found = reapplyOrNull(template, parent, child, overflow)
  if (found === null) {
    const levelId = defined(calendar.levels[parent.level - 1])
    throw new DateError('invalid_date', `the ${levelId} doesn't exist in the target`, levelId)
  }
  return found
}

/** `reapply`, but `null` where `reject` refuses a constraining step (no exception: recurrence
 * rules with `missing: skip` hit this in most periods). */
export function reapplyOrNull(
  template: CompiledTemplate,
  parent: CompiledTemplate,
  child: Child,
  overflow: Overflow,
): Child | null {
  const segment = child.segment
  let regular = childRegularIndex(child)
  const found =
    segment.slotId !== null
      ? template.childBySlot(segment.slotId)
      : template.childByRegularIndex(defined(regular)) // unnamed children are never intercalary
  if (found !== null) return found
  if (overflow === 'reject') return null
  regular ??= regularBefore(template, childIndex(parent, child)) - 1n
  if (template.regularCount === 0n) return template.childAt(0n)
  const last = template.regularCount - 1n
  return defined(template.childByRegularIndex(regular < 0n ? 0n : regular > last ? last : regular))
}

/** 0-based index of `child` among all children of `template`. */
function childIndex(template: CompiledTemplate, child: Child): bigint {
  let index = child.index
  for (const segment of template.segments.slice(0, child.position)) index += segment.count
  return index
}

/** Number of regular children of `template` whose index is below `index`. */
function regularBefore(template: CompiledTemplate, index: bigint): bigint {
  let first = 0n
  for (const segment of template.segments) {
    if (index < first + segment.count) {
      const inside = segment.intercalary ? 0n : index - first
      return segment.regularStart + inside
    }
    first += segment.count
  }
  return template.regularCount
}

// --- diff ----------------------------------------------------------------------------------------

/**
 * §9.3: `t2 − t1` in the levels `largest` … `smallest`, greedily from the coarsest. For
 * `t1 ≤ t2`: `add(t1, amounts) ≤ t2 < add(t1, amounts + 1·smallest)`, and `base` is
 * `t2 − add(t1, amounts)`. For `t1 > t2` the result is `diff(t2, t1)` with sign `-1`.
 */
export function diff(
  calendar: CompiledCalendar,
  t1: bigint,
  t2: bigint,
  largest: string,
  smallest: string,
): Difference {
  const high = levelOf(calendar, largest)
  const low = levelOf(calendar, smallest)
  if (high < low)
    throw new DateError('invalid_date', `${largest} is finer than ${smallest}`, largest)
  if (t1 > t2) return { ...diff(calendar, t2, t1, largest, smallest), sign: -1 }
  const amounts = new Map<string, bigint>()
  let current = t1
  for (let level = high; level >= low; level--) {
    const count = fit(calendar, current, level, t2)
    amounts.set(defined(calendar.levels[level]), count)
    current = step(calendar, current, level, count, 'constrain')
  }
  return { amounts, base: t2 - current, sign: 1 }
}

/**
 * The largest `n ≥ 0` with `step(t, level, n) ≤ limit` (`t ≤ limit`). Steps are strictly
 * increasing in `n`, so an ordinal estimate is corrected by galloping and bisecting (a couple of
 * probes in practice).
 */
function fit(calendar: CompiledCalendar, t: bigint, level: number, limit: bigint): bigint {
  const length = uniformLength(calendar, level)
  if (length !== null) return floorDiv(limit - t, length)
  const regime = activeRegime(calendar, t)
  const top = calendar.levels.length - 1
  const estimate =
    countedPosition(top, regime, limit, level, REGULAR)[0] -
    countedPosition(top, regime, t, level, REGULAR)[0]
  const fits = (n: bigint): boolean =>
    n === 0n || variableStep(calendar, regime, t, level, n, 'constrain') <= limit
  const atLeastZero = (n: bigint): bigint => (n < 0n ? 0n : n)
  let low = atLeastZero(estimate)
  let high: bigint
  let gap = 1n
  if (fits(low)) {
    // gallop up to a failing count
    while (fits(low + gap)) {
      low += gap
      gap *= 2n
    }
    high = low + gap
  } else {
    // gallop down to a fitting count
    high = low
    while (!fits(atLeastZero(high - gap))) {
      high -= gap
      gap *= 2n
    }
    low = atLeastZero(high - gap)
  }
  while (high - low > 1n) {
    const middle = (low + high) / 2n
    if (fits(middle)) low = middle
    else high = middle
  }
  return low
}

// --- upper bound ---------------------------------------------------------------------------------

/**
 * A safe bound on `|add(t, duration) − t|` for every `t` (recurrence window widening). Uniform
 * levels contribute their exact length. A variable step of `n` units moves the unit start by at
 * most `n` maximal units plus the intercalary units skipped in the years crossed, and the position
 * inside the unit by less than one maximal unit.
 */
export function durationUpperBound(calendar: CompiledCalendar, duration: Duration): bigint {
  if (duration.kind === 'base') return abs(BigInt(duration.units))
  let total = 0n
  for (const [level, n] of ordered(calendar, duration)) total += levelBound(calendar, level, n)
  return total
}

function levelBound(calendar: CompiledCalendar, level: number, n: bigint): bigint {
  const length = uniformLength(calendar, level)
  if (length !== null) return n * length
  const longest = templatesOf(calendar, level).reduce(
    (most, template) => (template.length > most ? template.length : most),
    0n,
  )
  const top = calendar.levels.length - 1
  let skipped = 0n
  for (const regime of calendar.regimes) {
    const memo = new Map<string, bigint>()
    for (const template of regime.templates.values()) {
      if (template.level !== top) continue
      const length = intercalaryLength(regime, template, level, memo)
      if (length > skipped) skipped = length
    }
  }
  if (skipped === 0n) return (n + 1n) * longest
  const fewest = templatesOf(calendar, top).reduce<bigint | null>((least, year) => {
    const regular = defined(year.units.get(level))[1]
    return least === null || regular < least ? regular : least
  }, null)
  let crossed: bigint
  if (defined(fewest) > 0n) {
    crossed = n / defined(fewest) + 2n
  } else {
    // runs of years without regular units: bounded by the period and the exceptions
    const run = calendar.regimes.reduce((most, r) => {
      const length = BigInt(r.exceptionYears.length + 1) * r.period
      return length > most ? length : most
    }, 0n)
    crossed = n * (run + 1n) + 2n
  }
  return (n + 1n) * longest + crossed * skipped
}

/** Total length of the intercalary `level` units inside one unit of `template`. */
function intercalaryLength(
  regime: CompiledRegime,
  template: CompiledTemplate,
  level: number,
  memo: Map<string, bigint>,
): bigint {
  if (template.level <= level) return 0n // the top level: years are never intercalary
  const cached = memo.get(template.id)
  if (cached !== undefined) return cached
  let total = 0n
  for (const segment of template.segments) {
    if (template.level - 1 === level) {
      if (segment.intercalary) total += segment.count * segment.childLength
    } else {
      const child = regime.template(defined(segment.child))
      total += segment.count * intercalaryLength(regime, child, level, memo)
    }
  }
  memo.set(template.id, total)
  return total
}
