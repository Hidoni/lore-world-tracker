/**
 * Expansion, single occurrences and series bounds (recurrence.md §2–§5, §9). The Python twin is
 * backend/src/lore/chronology/recurrence/engine.py.
 *
 * A rule becomes a plan (`./plan`): candidate period `k = 0, 1, …` holds time-ordered positions.
 * Interval rules have one position, `seriesStart + k·every`. Calendar rules (`./calendar-rules`)
 * use the period `p0 + k·interval` of the frequency level or cycle (`p0` = the period of the series
 * start). Windows map to a `k` range by ordinal arithmetic, so the cost doesn't depend on how far
 * the window is from the series start.
 *
 * Count limits, exclusions, occurrence numbers and window counts use the counting primitives of
 * `Plan` (recurrence.md §5.4).
 */
import { defined } from '../calendar/compiled'
import { floorDiv } from '../numbers'
import type { IntervalRule, RecurrenceRule } from '../schema.gen'
import { CalendarPlan, calendarRuleErrors } from './calendar-rules'
import {
  ITERATE_LIMIT,
  type Occurrence,
  Plan,
  type Position,
  type RecurrenceContext,
  RecurrenceError,
  type RuleValidationError,
  SCAN_LIMIT,
  TRUNCATE_FACTOR,
  occurrenceToJson,
} from './plan'

const KEY = /^(0|[1-9][0-9]*)$/
const SUB_KEY = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/

const max = (a: bigint, b: bigint): bigint => (a > b ? a : b)
const min = (a: bigint, b: bigint): bigint => (a < b ? a : b)

/** The occurrences overlapping a window, or `truncated` with a count and no items. */
export interface Expansion {
  readonly items: readonly Occurrence[]
  readonly truncated: boolean
  /** Set when `truncated`: the number of occurrences (an estimate when it can't be exact). */
  readonly estimatedCount: bigint | null
}

/** The conformance-vector form of an expansion. */
export function expansionToJson(found: Expansion): Record<string, unknown> {
  return {
    items: found.items.map(occurrenceToJson),
    truncated: found.truncated,
    estimated_count: found.estimatedCount?.toString() ?? null,
  }
}

/** `null` members are unbounded (`never`), or absent when the series has no occurrence. */
export interface SeriesBounds {
  readonly firstStart: bigint | null
  readonly lastStart: bigint | null
  readonly lastEnd: bigint | null
  readonly count: bigint | null
}

/** The conformance-vector form of series bounds. */
export function seriesBoundsToJson(found: SeriesBounds): Record<string, string | null> {
  return {
    first_start: found.firstStart?.toString() ?? null,
    last_start: found.lastStart?.toString() ?? null,
    last_end: found.lastEnd?.toString() ?? null,
    count: found.count?.toString() ?? null,
  }
}

/** A window count; `exact: false` marks an estimate (recurrence.md §5.4). */
export interface WindowCount {
  readonly count: bigint
  readonly exact: boolean
}

// --- validation (§9) -----------------------------------------------------------------------------

function error(code: string, path: string, message: string): RuleValidationError {
  return { code, path, message, severity: 'error' }
}

function resolvedAt(ctx: RecurrenceContext, path: string): bigint | null {
  return ctx.resolved?.[path] ?? null
}

function structuralErrors(rule: RecurrenceRule, ctx: RecurrenceContext): RuleValidationError[] {
  const errors: RuleValidationError[] = []
  const end = ctx.end
  if (end.kind !== 'duration' && end.kind !== 'instant' && end.kind !== 'unknown') {
    errors.push(error('rule.series_end_not_duration', '/end', 'a series end must be a duration'))
  } else if (end.kind === 'duration' && end.duration.kind === 'calendar' && ctx.calendar == null) {
    errors.push(error('rule.unknown_calendar', '/end/duration/calendar_id', 'no calendar given'))
  }
  if (rule.limit.kind === 'until') {
    const until = resolvedAt(ctx, '/limit/until')
    if (until === null) {
      errors.push(error('anchor.unresolved', '/limit/until', 'until is not resolved'))
    } else if (until < ctx.seriesStart) {
      errors.push(error('rule.until_before_start', '/limit/until', 'until is before the start'))
    }
  }
  ;(rule.exclusions ?? []).forEach((_, i) => {
    const begin = resolvedAt(ctx, `/exclusions/${i}/from`)
    const to = resolvedAt(ctx, `/exclusions/${i}/to`)
    for (const [member, value] of [
      ['from', begin],
      ['to', to],
    ] as const) {
      if (value === null) {
        errors.push(error('anchor.unresolved', `/exclusions/${i}/${member}`, 'unresolved'))
      }
    }
    if (begin !== null && to !== null && to < begin) {
      errors.push(error('rule.bad_exclusion', `/exclusions/${i}`, 'to is before from'))
    }
  })
  if (rule.kind === 'calendar') {
    if (ctx.calendar == null) {
      errors.push(error('rule.unknown_calendar', '/calendar_id', 'no calendar given'))
    } else {
      errors.push(...calendarRuleErrors(rule, ctx.calendar, ctx.seriesStart))
    }
  }
  return errors
}

/**
 * §9: errors, plus the warning `rule.series_start_not_occurrence` (path `""`) when the first
 * occurrence isn't at the series start. Paths point into the rule, except `/end…`, which points
 * into the series' end spec.
 */
export function validateRule(rule: RecurrenceRule, ctx: RecurrenceContext): RuleValidationError[] {
  const errors = structuralErrors(rule, ctx)
  if (errors.length > 0) return errors
  if (seriesBounds(rule, ctx).firstStart !== ctx.seriesStart) {
    return [
      {
        code: 'rule.series_start_not_occurrence',
        path: '',
        message: 'the series start is not an occurrence; the first occurrence is later',
        severity: 'warning',
      },
    ]
  }
  return []
}

// --- plans ---------------------------------------------------------------------------------------

class IntervalPlan extends Plan {
  readonly every: bigint

  constructor(rule: IntervalRule, ctx: RecurrenceContext, last: bigint) {
    super(ctx, last)
    this.every = BigInt(rule.every)
  }

  positions(k: bigint): (bigint | null)[] {
    return [this.ctx.seriesStart + k * this.every]
  }

  kRange(low: bigint, high: bigint): readonly [bigint, bigint] {
    const start = this.ctx.seriesStart
    return [max(0n, -floorDiv(start - low, this.every)), floorDiv(high - start, this.every)]
  }

  readonly dense = true

  countBefore(t: bigint): bigint {
    return max(0n, -floorDiv(this.ctx.seriesStart - t, this.every))
  }

  position(i: bigint): Position {
    return [i - 1n, 0, this.ctx.seriesStart + (i - 1n) * this.every]
  }
}

function plan(rule: RecurrenceRule, ctx: RecurrenceContext): Plan {
  const errors = structuralErrors(rule, ctx).filter((e) => e.severity === 'error')
  if (errors.length > 0) {
    throw new RecurrenceError('rule.invalid', defined(errors[0]).message, errors)
  }
  let last = ctx.dimensionDuration
  if (rule.limit.kind === 'until') last = min(last, defined(resolvedAt(ctx, '/limit/until')))
  const found =
    rule.kind === 'interval'
      ? new IntervalPlan(rule, ctx, last)
      : new CalendarPlan(rule, ctx, defined(ctx.calendar), last)
  const ranges = (rule.exclusions ?? [])
    .map((_, i): [bigint, bigint] => [
      defined(resolvedAt(ctx, `/exclusions/${i}/from`)),
      defined(resolvedAt(ctx, `/exclusions/${i}/to`)),
    ])
    .sort(([a, b], [c, d]) => (a !== c ? (a < c ? -1 : 1) : b < d ? -1 : b > d ? 1 : 0))
  for (const [begin, to] of ranges) {
    if (begin >= to) continue
    const previous = found.exclusions.at(-1)
    if (previous !== undefined && begin <= previous[1]) previous[1] = max(previous[1], to)
    else found.exclusions.push([begin, to])
  }
  found.exclusionStarts = found.exclusions.map(([begin]) => begin)
  if (rule.limit.kind === 'count') {
    // §5.4: the count-th generated occurrence (exclusions still use up the count) ends it.
    const index = found.countBefore(ctx.seriesStart) + BigInt(rule.limit.count)
    const position = found.position(index)
    if (position !== null && position[2] <= found.last) found.last = position[2]
  }
  return found
}

// --- public API (§4) -----------------------------------------------------------------------------

/** `time-model.md` §2.1 overlap of an occurrence and a window (either may be an instant). */
function overlaps(start: bigint, end: bigint, w0: bigint, w1: bigint): boolean {
  if (start === end && w0 === w1) return start === w0
  if (start === end) return w0 <= start && start < w1
  if (w0 === w1) return start <= w0 && w0 < end
  return start < w1 && w0 < end
}

/**
 * §5.1–§5.3: the occurrences overlapping `[w0, w1)`, in time order.
 *
 * When more than `maxItems` occurrences overlap the window, the result is `truncated` with no
 * items and their count in `estimatedCount` (recurrence.md §5.1 says when it is exact).
 */
export function expand(
  rule: RecurrenceRule,
  ctx: RecurrenceContext,
  window: readonly [bigint, bigint],
  maxItems = 100,
): Expansion {
  const found = plan(rule, ctx)
  const [w0, w1] = window
  const most = BigInt(maxItems)
  const [low, high] = startsRange(found, w0, w1)
  const [kLo, kHi] = w0 <= w1 && low <= high ? found.kRange(low, high) : [0n, -1n]
  const periods = kHi - kLo + 1n
  if (periods <= 0n) return { items: [], truncated: false, estimatedCount: null }
  if (
    periods > max(ITERATE_LIMIT, TRUNCATE_FACTOR * most) ||
    (found instanceof IntervalPlan && periods > TRUNCATE_FACTOR * most)
  ) {
    return { items: [], truncated: true, estimatedCount: count(found, w0, w1, kLo, kHi).count }
  }
  const items: Occurrence[] = []
  for (let k = kLo; k <= kHi; k++) {
    for (const item of found.occurrences(k)) {
      if (overlaps(item.start, item.end, w0, w1)) items.push(item)
    }
    if (BigInt(items.length) > TRUNCATE_FACTOR * most) {
      return { items: [], truncated: true, estimatedCount: count(found, w0, w1, kLo, kHi).count }
    }
  }
  if (BigInt(items.length) > most) {
    return { items: [], truncated: true, estimatedCount: BigInt(items.length) }
  }
  return { items, truncated: false, estimatedCount: null }
}

/** Starts that may overlap `[w0, w1)` (§5.1), within the series bounds. */
function startsRange(found: Plan, w0: bigint, w1: bigint): readonly [bigint, bigint] {
  const length = found.exactLength() ?? found.upperLength()
  const low = max(found.ctx.seriesStart, length > 0n ? w0 - length + 1n : w0)
  return [low, min(w1 > w0 ? w1 - 1n : w0, found.last)]
}

/** Occurrences overlapping the window: by counting, else sampled periods. */
function count(found: Plan, w0: bigint, w1: bigint, kLo: bigint, kHi: bigint): WindowCount {
  try {
    return countExactly(found, w0, w1)
  } catch (error) {
    if (!(error instanceof RecurrenceError) || error.code !== 'rule.too_complex_to_count') {
      throw error
    }
  }
  return { count: found.estimate(kLo, kHi), exact: false }
}

function countExactly(found: Plan, w0: bigint, w1: bigint): WindowCount {
  const [low, high] = startsRange(found, w0, w1) // callers ensure low ≤ high
  if (found.exactLength() !== null) {
    return { count: found.actualBefore(high + 1n) - found.actualBefore(low), exact: true }
  }
  // Calendar durations: starts in the window overlap it; earlier ones are checked one by one.
  const inside = found.actualBefore(high + 1n) - found.actualBefore(max(low, w0))
  const earlier = found.actualBefore(w0) - found.actualBefore(low)
  if (earlier > ITERATE_LIMIT) return { count: inside + earlier, exact: false }
  let hits = 0n
  let t = low
  for (let i = 0n; i < earlier; i++) {
    const item = defined(found.nextOccurrence(t))
    if (overlaps(item.start, item.end, w0, w1)) hits++
    t = item.start + 1n
  }
  return { count: inside + hits, exact: true }
}

function valid(found: Plan, key: string): Occurrence {
  const match = (found.multi ? SUB_KEY : KEY).exec(key)
  const item =
    match === null
      ? undefined
      : found.occurrences(BigInt(defined(match[1]))).find((o) => o.key === key)
  if (item === undefined) throw new RecurrenceError('not_found', `no occurrence has key ${key}`)
  return item
}

/** The occurrence with `key` (`k`, or `k.j` for multi-position rules, §3); `not_found` if the key
 * has none (or it is excluded or beyond the limit). */
export function occurrence(rule: RecurrenceRule, ctx: RecurrenceContext, key: string): Occurrence {
  return valid(plan(rule, ctx), key)
}

/** §3: the 1-based number of the occurrence among the series' actual occurrences. */
export function occurrenceNumber(
  rule: RecurrenceRule,
  ctx: RecurrenceContext,
  key: string,
): bigint {
  const found = plan(rule, ctx)
  return found.actualBefore(valid(found, key).start + 1n)
}

/** §4: the occurrences overlapping `[w0, w1)`. Exact for interval rules and for calendar rules
 * that super-periods can count; otherwise sampled (`exact` false). */
export function countInWindow(
  rule: RecurrenceRule,
  ctx: RecurrenceContext,
  window: readonly [bigint, bigint],
): WindowCount {
  const found = plan(rule, ctx)
  const [w0, w1] = window
  const [low, high] = startsRange(found, w0, w1)
  if (w1 < w0 || low > high) return { count: 0n, exact: true }
  const [kLo, kHi] = found.kRange(low, high)
  if (kHi < kLo) return { count: 0n, exact: true }
  return count(found, w0, w1, kLo, kHi)
}

/** §4: the key of the occurrence starting at `t`, else of the latest-starting occurrence whose
 * span contains `t` (product decision, 2026-10-02); `null` if none does. */
export function occurrenceAt(
  rule: RecurrenceRule,
  ctx: RecurrenceContext,
  t: bigint,
): string | null {
  const found = plan(rule, ctx)
  let item = found.previousOccurrence(t)
  if (item === null || item.start === t) return item?.key ?? null
  // earlier occurrences end earlier
  if (found.exactLength() !== null) return item.end > t ? item.key : null
  const earliest = t - found.upperLength() + 1n
  for (let i = 0n; i < SCAN_LIMIT; i++) {
    if (item === null || item.start < earliest) return null
    if (item.end > t) return item.key
    item = found.previousOccurrence(item.start - 1n)
  }
  /* v8 ignore next */
  return null
}

/** The first `n` occurrences starting at or after `after` (editor previews). */
export function nextOccurrences(
  rule: RecurrenceRule,
  ctx: RecurrenceContext,
  after: bigint,
  n: number,
): Occurrence[] {
  const found = plan(rule, ctx)
  const items: Occurrence[] = []
  let t = after
  while (items.length < n) {
    const item = found.nextOccurrence(t)
    if (item === null) break
    items.push(item)
    t = item.start + 1n
  }
  return items
}

/**
 * §4 `seriesBounds`: the first and last occurrences and their number.
 *
 * `never`: only `firstStart` (the rest is unbounded). `until` and `count`: the last occurrence and
 * the exact count of actual occurrences (exclusions applied); a `count` limit counts generated
 * occurrences, so excluded ones use it up (product decision, 2026-10-02).
 */
export function seriesBounds(rule: RecurrenceRule, ctx: RecurrenceContext): SeriesBounds {
  const found = plan(rule, ctx)
  const first = found.nextOccurrence(ctx.seriesStart)
  const bounded = rule.limit.kind !== 'never'
  if (first === null) {
    return { firstStart: null, lastStart: null, lastEnd: null, count: bounded ? 0n : null }
  }
  if (!bounded) return { firstStart: first.start, lastStart: null, lastEnd: null, count: null }
  const last = defined(found.previousOccurrence(found.last)) // the first occurrence qualifies
  return {
    firstStart: first.start,
    lastStart: last.start,
    lastEnd: last.end,
    count: found.actualBefore(found.last + 1n),
  }
}
