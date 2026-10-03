/**
 * Unit navigation: bounds, ordinals and fromOrdinal (chronology-engine.md §5.8, §7). The Python
 * twin is backend/src/lore/chronology/calendar/units.py.
 *
 * Ordinals count units of a level from the start of year 0 (the first counted unit of year 0 is 0;
 * units before year 0 are negative). Which units count is a `UnitFilter`: `REGULAR` (intercalary
 * units don't count) for ordinals, a cycle's exclusions for counted ordinals. Counts come from
 * prefix sums (per template over its segments, per period over its years, plus exception deltas),
 * computed on first use per (level, filter) and cached on the regime. Queries cost
 * `O(log P + depth · log width)`; nothing iterates over units or years.
 */
import { floorDiv } from '../numbers'
import {
  type CompiledCalendar,
  type CompiledRegime,
  type CompiledTemplate,
  DateError,
  type Segment,
  activeRegime,
  bisectRight,
  defined,
} from './compiled'

/**
 * Which units of a level count. A unit counts if `counts(segment)` holds for its own segment and
 * no segment on its path (itself or an ancestor) `excludes` its subtree. `key` identifies the
 * filter in caches.
 */
export interface UnitFilter {
  readonly key: string
  readonly counts: (segment: Segment) => boolean
  readonly excludes: (segment: Segment) => boolean
}

/** Regular units: everything except intercalary units themselves (§3.4). */
export const REGULAR: UnitFilter = {
  key: 'regular',
  counts: (segment) => !segment.intercalary,
  excludes: () => false,
}

/**
 * The units a cycle counts: all units except those excluded from it with their subtrees
 * (`cycle_excluded`, §3.4, §3.7). Intercalary units count unless excluded (R-CAL-4).
 */
export function cycleFilter(cycleId: string): UnitFilter {
  return {
    key: `cycle:${cycleId}`,
    counts: () => true,
    excludes: (segment) => segment.cycleExcluded.includes(cycleId),
  }
}

/** `[start, end)` of a unit, in base units. */
export interface Bounds {
  readonly start: bigint
  readonly end: bigint
}

export interface Ordinal {
  /** Ordinal of the unit, or of the preceding counted unit when `counted` is false. */
  readonly value: bigint
  /** False for a unit the filter skips (for `REGULAR`: an intercalary unit). */
  readonly counted: boolean
}

// --- counts (cached per regime) ------------------------------------------------------------------

/** Counted units of `level` inside one child of `segment` (a unit of `childLevel`). */
function perChild(
  regime: CompiledRegime,
  segment: Segment,
  level: number,
  childLevel: number,
  filter: UnitFilter,
): bigint {
  if (filter.excludes(segment)) return 0n
  if (childLevel === level) return filter.counts(segment) ? 1n : 0n
  return templateCount(regime, regime.template(defined(segment.child)), level, filter)
}

/** Counted `level` units before each segment of `template` (length = segments + 1). */
function templatePrefix(
  regime: CompiledRegime,
  template: CompiledTemplate,
  level: number,
  filter: UnitFilter,
): readonly bigint[] {
  const key = `prefix\u0000${template.id}\u0000${level}\u0000${filter.key}`
  let cached = regime.cache.get(key) as readonly bigint[] | undefined
  if (cached === undefined) {
    const childLevel = template.level - 1
    const prefix = [0n]
    for (const segment of template.segments) {
      const count = segment.count * perChild(regime, segment, level, childLevel, filter)
      prefix.push(defined(prefix.at(-1)) + count)
    }
    cached = prefix
    regime.cache.set(key, cached)
  }
  return cached
}

function templateCount(
  regime: CompiledRegime,
  template: CompiledTemplate,
  level: number,
  filter: UnitFilter,
): bigint {
  return defined(templatePrefix(regime, template, level, filter).at(-1))
}

/** Counted units before each year: `before(Y) = k·total + prefix[i] + cum(Y)` (like §5.2). */
class YearCounts {
  constructor(
    readonly prefix: readonly bigint[],
    readonly total: bigint,
    readonly exceptionYears: readonly bigint[],
    readonly exceptionCounts: readonly bigint[],
    readonly deltas: readonly bigint[],
    readonly starts: readonly bigint[],
  ) {}

  cumulative(year: bigint): bigint {
    const years = this.exceptionYears
    const before = defined(this.deltas[bisectRight(years, year - 1n)])
    return before - defined(this.deltas[bisectRight(years, -1n)])
  }

  before(year: bigint, period: bigint): bigint {
    const k = floorDiv(year, period)
    return k * this.total + defined(this.prefix[Number(year - k * period)]) + this.cumulative(year)
  }
}

function yearCounts(regime: CompiledRegime, level: number, filter: UnitFilter): YearCounts {
  const key = `years\u0000${level}\u0000${filter.key}`
  const cached = regime.cache.get(key)
  if (cached instanceof YearCounts) return cached
  const perTemplate = regime.topTemplates.map((id) =>
    templateCount(regime, regime.template(id), level, filter),
  )
  const period = Number(regime.period)
  const prefix = new Array<bigint>(period + 1)
  prefix[0] = 0n
  for (let i = 0; i < period; i++) {
    prefix[i + 1] = defined(prefix[i]) + defined(perTemplate[defined(regime.topSequence[i])])
  }
  const total = defined(prefix[period])
  const years = regime.exceptionYears
  const counts = regime.exceptionTemplates.map((id) =>
    templateCount(regime, regime.template(id), level, filter),
  )
  const deltas = [0n]
  years.forEach((year, e) => {
    const regular = defined(perTemplate[defined(regime.topSequence[regularIndex(regime, year)])])
    deltas.push(defined(deltas.at(-1)) + defined(counts[e]) - regular)
  })
  const partial = new YearCounts(prefix, total, years, counts, deltas, [])
  const starts = years.map((year) => partial.before(year, regime.period))
  const result = new YearCounts(prefix, total, years, counts, deltas, starts)
  regime.cache.set(key, result)
  return result
}

function regularIndex(regime: CompiledRegime, year: bigint): number {
  return Number(year - floorDiv(year, regime.period) * regime.period)
}

/** The year containing counted unit `m` (inverse of `before`), or null if none does. */
function yearOfCount(regime: CompiledRegime, counts: YearCounts, m: bigint): bigint | null {
  const position = bisectRight(counts.starts, m) - 1
  if (
    position >= 0 &&
    m < defined(counts.starts[position]) + defined(counts.exceptionCounts[position])
  ) {
    return defined(counts.exceptionYears[position])
  }
  if (counts.total === 0n) return null
  const offset =
    position >= 0
      ? counts.cumulative(defined(counts.exceptionYears[position]) + 1n)
      : counts.cumulative(counts.exceptionYears[0] ?? 0n)
  const regular = m - offset
  const k = floorDiv(regular, counts.total)
  const s = regular - k * counts.total
  return k * regime.period + BigInt(bisectRight(counts.prefix, s, Number(regime.period)) - 1)
}

/** Counted `level` units in one period of the top pattern (`P` years, no exceptions). */
export function unitsPerPeriod(
  regime: CompiledRegime,
  level: number,
  top: number,
  filter: UnitFilter = REGULAR,
): bigint {
  if (level === top) return regime.period
  return yearCounts(regime, level, filter).total
}

// --- levels and regimes --------------------------------------------------------------------------

function levelOf(calendar: CompiledCalendar, level: string): number {
  const index = calendar.levelIndex(level)
  if (index < 0) throw new DateError('invalid_date', `unknown level ${level}`, level)
  return index
}

function regimeOf(calendar: CompiledCalendar, regime: string | null | undefined): CompiledRegime {
  if (regime == null) return defined(calendar.regimes[0])
  const found = calendar.regimes.find((r) => r.id === regime)
  if (found === undefined) throw new DateError('invalid_date', `unknown regime ${regime}`)
  return found
}

/** Clip a unit to its regime's validity interval (§7). */
function clip(calendar: CompiledCalendar, regime: CompiledRegime, start: bigint, end: bigint) {
  if (regime.index > 0 && regime.startsAt !== null && regime.startsAt > start) {
    start = regime.startsAt
  }
  for (const later of calendar.regimes.slice(regime.index + 1)) {
    if (later.startsAt !== null && later.startsAt < end) end = later.startsAt
  }
  return { start, end }
}

interface Located {
  readonly start: bigint
  readonly length: bigint
  /** Counted units of the level before this unit. */
  readonly before: bigint
  readonly counted: boolean
}

/**
 * Descend from the year containing `t` to the unit of `level` containing it. `top` is the index
 * of the top level (the number of levels minus one).
 */
function locate(
  top: number,
  regime: CompiledRegime,
  t: bigint,
  level: number,
  filter: UnitFilter,
): Located {
  const rel = t - regime.epoch
  const year = regime.yearOfRel(rel)
  let start = regime.relStart(year)
  let template = regime.yearTemplate(year)
  if (level === top) {
    return { start: regime.epoch + start, length: template.length, before: year, counted: true }
  }
  let before = yearCounts(regime, level, filter).before(year, regime.period)
  let offset = rel - start
  let excluded = false
  for (let childLevel = top - 1; ; childLevel--) {
    const child = template.childAt(offset)
    const segment = child.segment
    if (!excluded) {
      // nothing inside an excluded subtree counts
      const each = perChild(regime, segment, level, childLevel, filter)
      before += defined(templatePrefix(regime, template, level, filter)[child.position])
      before += child.index * each
    }
    excluded ||= filter.excludes(segment)
    start += child.offset
    offset -= child.offset
    if (childLevel === level) {
      const counted = !excluded && filter.counts(segment)
      return { start: regime.epoch + start, length: segment.childLength, before, counted }
    }
    template = regime.template(defined(segment.child))
  }
}

/**
 * (counted units of `level` before the unit containing `t`, whether that unit counts, the unit's
 * start) in `regime`. `level` is a level index, `top` the top level's index.
 */
export function countedPosition(
  top: number,
  regime: CompiledRegime,
  t: bigint,
  level: number,
  filter: UnitFilter,
): readonly [bigint, boolean, bigint] {
  const located = locate(top, regime, t, level, filter)
  return [located.before, located.counted, located.start]
}

// --- public API ----------------------------------------------------------------------------------

/** `[start, end)` of the `level` unit containing `t`, clipped at regime boundaries. */
export function unitBounds(calendar: CompiledCalendar, t: bigint, level: string): Bounds {
  const regime = activeRegime(calendar, t)
  const top = calendar.levels.length - 1
  const located = locate(top, regime, t, levelOf(calendar, level), REGULAR)
  return clip(calendar, regime, located.start, located.start + located.length)
}

/**
 * Ordinal of the `level` unit containing `t` among the units `filter` counts. For a unit the
 * filter skips, the ordinal of the preceding counted unit, with `counted: false`. Computed in the
 * regime active at `t` (§7).
 */
export function countedOrdinal(
  calendar: CompiledCalendar,
  t: bigint,
  level: string,
  filter: UnitFilter = REGULAR,
): Ordinal {
  const regime = activeRegime(calendar, t)
  const top = calendar.levels.length - 1
  const located = locate(top, regime, t, levelOf(calendar, level), filter)
  if (located.counted) return { value: located.before, counted: true }
  return { value: located.before - 1n, counted: false }
}

/** §5.8 `ordinal`: regular units; `counted: false` means `t` is in an intercalary unit. */
export function ordinal(calendar: CompiledCalendar, t: bigint, level: string): Ordinal {
  return countedOrdinal(calendar, t, level, REGULAR)
}

/** Bounds of the counted `level` unit with ordinal `m` (default: regime 0). */
export function fromCountedOrdinal(
  calendar: CompiledCalendar,
  level: string,
  m: bigint,
  filter: UnitFilter = REGULAR,
  options: { readonly regime?: string | null } = {},
): Bounds {
  const chosen = regimeOf(calendar, options.regime)
  const index = levelOf(calendar, level)
  const top = calendar.levels.length - 1
  if (index === top) return { start: chosen.yearStart(m), end: chosen.yearStart(m + 1n) }
  const counts = yearCounts(chosen, index, filter)
  const year = yearOfCount(chosen, counts, m)
  if (year === null)
    throw new DateError('invalid_date', `no counted ${level} has ordinal ${m}`, level)
  let remaining = m - counts.before(year, chosen.period)
  let start = chosen.yearStart(year)
  let template = chosen.yearTemplate(year)
  for (let childLevel = top - 1; ; childLevel--) {
    const prefix = templatePrefix(chosen, template, index, filter)
    const position = bisectRight(prefix, remaining) - 1
    const segment = defined(template.segments[position])
    const each = perChild(chosen, segment, index, childLevel, filter)
    const inside = remaining - defined(prefix[position])
    const within = inside / each // both non-negative: truncation is the floor
    remaining = inside - within * each
    start += segment.start + within * segment.childLength
    if (childLevel === index) return { start, end: start + segment.childLength }
    template = chosen.template(defined(segment.child))
  }
}

/** §5.8 `fromOrdinal`: bounds of the regular `level` unit with ordinal `m`. */
export function fromOrdinal(
  calendar: CompiledCalendar,
  level: string,
  m: bigint,
  options: { readonly regime?: string | null } = {},
): Bounds {
  return fromCountedOrdinal(calendar, level, m, REGULAR, options)
}
