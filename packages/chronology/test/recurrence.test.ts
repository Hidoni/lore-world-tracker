// Recurrence: validation, interval and calendar rules, keys, expansion and counting
// (recurrence.md), mirroring the Python engine's backend/tests/chronology/test_recurrence.py.
// Vectors: cases/recurrence/.
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import { type CompiledCalendar, cycleValue, fromFields } from '../src/calendar'
import { defined } from '../src/calendar/compiled'
import {
  countInWindow,
  expand,
  expansionToJson,
  nextOccurrences,
  occurrence,
  occurrenceAt,
  occurrenceNumber,
  type RecurrenceContext,
  RecurrenceError,
  seriesBounds,
  seriesBoundsToJson,
  validateRule,
} from '../src/recurrence'
import { CalendarPlan } from '../src/recurrence/calendar-rules'
import type { CalendarRule, EndSpec, RecurrenceRule } from '../src/schema.gen'
import { at, compiled, load, patched } from './calendars'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 200 : 25
const params = { numRuns: RUNS, seed: 20261003 }
/** Building a super-period counter takes up to seconds, once per rule. */
const SLOW = 60_000

const DAY = 86400n
const D = 10n ** 120n

function calendarOf(name: string): CompiledCalendar {
  const { definition, context } = load(name)
  return compiled(definition, context)
}

const NAMES = [
  'gregorian-seconds',
  'alternating-years',
  'intercalary-exceptions',
  'intercalary-day',
  'gregorian-week',
  'shire-week',
]
const CALENDARS = new Map(NAMES.map((name) => [name, calendarOf(name)]))
const calendar = (name: string): CompiledCalendar => defined(CALENDARS.get(name))
const GREGORIAN = calendar('gregorian-seconds')
const WEEK = calendar('gregorian-week')

type Members = Record<string, unknown>

function rule(members: Members): RecurrenceRule {
  const data: Members = {
    kind: 'calendar',
    calendar_id: 'cal',
    limit: { kind: 'never' },
    ...members,
  }
  if (data.kind === 'interval') delete data.calendar_id
  return data as unknown as RecurrenceRule
}

function calendarRule(members: Members): CalendarRule {
  return rule(members) as CalendarRule
}

const INSTANT: EndSpec = { kind: 'instant' }

function context(
  start: bigint,
  options: {
    calendar?: CompiledCalendar | null
    end?: EndSpec
    until?: bigint
    resolved?: Record<string, bigint>
  } = {},
): RecurrenceContext {
  const resolved = { ...options.resolved }
  if (options.until !== undefined) resolved['/limit/until'] = options.until
  return {
    seriesStart: start,
    end: options.end ?? INSTANT,
    dimensionDuration: D,
    calendar: options.calendar === undefined ? GREGORIAN : options.calendar,
    resolved,
  }
}

function g(year: number, month: string, day: number, hour = 0): bigint {
  const fields = { year: String(year), month, day: String(day), hour: String(hour) }
  return fromFields(GREGORIAN, fields, 'hour')
}

const UNTIL = { anchor: { kind: 'absolute', t: '0' }, precision: 'base' }
const UNTIL_LIMIT = { kind: 'until', until: UNTIL }
const MONTH: EndSpec = {
  kind: 'duration',
  duration: { kind: 'calendar', calendar_id: 'c', amounts: { month: '1' }, sign: 1 },
}

function errorCode(run: () => unknown): string {
  try {
    run()
  } catch (error) {
    if (error instanceof RecurrenceError) return error.code
    throw error
  }
  throw new Error('expected a RecurrenceError')
}

// --- properties ----------------------------------------------------------------------------------

const day = (values: string[]): Members => ({ level: 'day', values })
const week = (values: string[], nth?: string[]): Members => ({
  level: 'day',
  cycle: nth === undefined ? { id: 'week', values } : { id: 'week', values, nth },
})

/** Rules for calendars with a 7-day `week` cycle at the `day` level (dense enough that property
 * windows don't visit thousands of empty periods). */
const ADVANCED: Members[] = [
  { freq: { level: 'month' }, select: { path: [week(['1'], ['1'])] } },
  { freq: { level: 'month' }, select: { path: [week(['2', '6'], ['-1', '2'])] } },
  { freq: { cycle: 'week' }, select: { path: [day(['1', '5'])] } },
  { freq: { cycle: 'week' } },
  { freq: { level: 'year' }, select: { path: [day(['100', '-1'])] } },
  { freq: { level: 'year' }, select: { path: [week(['5'], ['1', '-1'])] } },
  { freq: { level: 'month' }, select: { path: [{ level: 'day', all: true }] } },
  {
    freq: { level: 'year' },
    filters: [{ mod: '2', eq: '1' }],
    select: { path: [{ level: 'month', values: ['2'] }, day(['3'])] },
  },
  { freq: { level: 'month' }, filters: [{ not: { in: ['1'] } }] },
  { freq: { level: 'day' }, filters: [{ any: [{ cycle: 'week', in: ['1', '2', '3'] }] }] },
]

interface Series {
  readonly rule: RecurrenceRule
  readonly calendar: string
  readonly start: bigint
  readonly end: EndSpec
}

function seriesContext(found: Series): RecurrenceContext {
  return {
    seriesStart: found.start,
    end: found.end,
    dimensionDuration: 10n ** 30n,
    calendar: calendar(found.calendar),
  }
}

const series: fc.Arbitrary<Series> = fc
  .record({
    name: fc.constantFrom(...NAMES),
    start: fc.bigInt(0n, 10n ** 18n),
    duration: fc.constantFrom('instant', 'base', 'calendar'),
    kind: fc.constantFrom('interval', 'simple', 'advanced'),
    every: fc.bigInt(1n, 10n ** 12n),
    advanced: fc.constantFrom(...ADVANCED),
    interval: fc.integer({ min: 1, max: 30 }),
    levelPick: fc.nat(),
    missing: fc.constantFrom('skip', 'constrain'),
  })
  .map(({ name, start, duration, kind, every, advanced, interval, levelPick, missing }) => {
    const levels = calendar(name).levels
    const end: EndSpec =
      duration === 'instant'
        ? INSTANT
        : duration === 'base'
          ? { kind: 'duration', duration: { kind: 'base', units: '100000' } }
          : {
              kind: 'duration',
              duration: {
                kind: 'calendar',
                calendar_id: 'cal',
                amounts: { [defined(levels.at(-2))]: '1' },
                sign: 1,
              },
            }
    let found: RecurrenceRule
    if (kind === 'interval') {
      found = rule({ kind: 'interval', every: String(every) })
    } else if (kind === 'advanced' && name.includes('week')) {
      // An interval can starve a filter forever (every 2nd year, odd years only): searches then
      // scan their whole limit, which is correct but slow, so filtered rules keep interval 1.
      const step = 'filters' in advanced ? 1 : (interval % 3) + 1
      found = rule({ ...advanced, interval: String(step), missing })
    } else {
      const level = defined(levels[levelPick % levels.length])
      found = rule({ freq: { level }, interval: String(interval), missing })
    }
    return { rule: found, calendar: name, start, end }
  })

describe('properties', () => {
  test(
    'expanded items are their occurrences',
    () => {
      fc.assert(
        fc.property(series, fc.bigInt(0n, 10n ** 19n), fc.bigInt(0n, 10n ** 17n), (s, w0, w) => {
          const ctx = seriesContext(s)
          const result = expand(s.rule, ctx, [w0, w0 + w], 50)
          const starts = result.items.map((item) => item.start)
          expect(starts).toEqual([...starts].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)))
          for (const item of result.items) {
            expect(occurrence(s.rule, ctx, item.key)).toEqual(item)
            expect(item.start >= ctx.seriesStart).toBe(true)
            expect(item.start < w0 + w || item.start === w0).toBe(true)
          }
          if (result.truncated) {
            expect(result.items).toEqual([])
            expect(result.estimatedCount).not.toBeNull()
          }
        }),
        params,
      )
    },
    SLOW,
  )

  test(
    'next occurrences agree with expand',
    () => {
      fc.assert(
        fc.property(series, fc.bigInt(0n, 10n ** 19n), (s, after) => {
          const ctx = seriesContext(s)
          const upcoming = nextOccurrences(s.rule, ctx, after, 3)
          for (const item of upcoming) {
            expect(item.start >= after).toBe(true)
            expect(occurrence(s.rule, ctx, item.key)).toEqual(item)
          }
          if (upcoming.length >= 2) {
            const first = defined(upcoming[0]).start
            const last = defined(upcoming.at(-1)).start
            const window = expand(s.rule, ctx, [first, last], 1000)
            if (window.truncated) {
              // long occurrences (e.g. a month every base unit) overlap en masse
              expect(defined(window.estimatedCount) >= BigInt(upcoming.length - 1)).toBe(true)
            } else {
              const starts = new Set(window.items.map((item) => item.start))
              for (const item of upcoming.slice(0, -1)) expect(starts.has(item.start)).toBe(true)
            }
          }
        }),
        params,
      )
    },
    SLOW,
  )

  test(
    'counts agree with expansion',
    () => {
      fc.assert(
        fc.property(series, fc.bigInt(0n, 10n ** 19n), fc.bigInt(0n, 10n ** 12n), (s, w0, w) => {
          const ctx = seriesContext(s)
          const window = [w0, w0 + w] as const
          let counted
          try {
            counted = countInWindow(s.rule, ctx, window)
          } catch (error) {
            expect(error).toBeInstanceOf(RecurrenceError)
            expect((error as RecurrenceError).code).toBe('rule.too_complex_to_count')
            return
          }
          const result = expand(s.rule, ctx, window, 200)
          if (counted.exact && !result.truncated) {
            expect(counted.count).toBe(BigInt(result.items.length))
          }
          const numbers = result.items
            .slice(0, 5)
            .map((item) => occurrenceNumber(s.rule, ctx, item.key))
          numbers.forEach((n, i) => {
            expect(n).toBe(defined(numbers[0]) + BigInt(i))
          })
        }),
        params,
      )
    },
    SLOW,
  )
})

// --- examples ------------------------------------------------------------------------------------

describe('expansion', () => {
  test('a far window is fast', () => {
    // No iteration from the series start: a window 10^90 years away expands at once.
    const start = g(2023, 'jan', 31, 8)
    const monthly = rule({ freq: { level: 'month' }, time: { fields: { hour: '9' } } })
    const ctx = context(start, { calendar: calendarOf('gregorian-seconds') }) // cold caches
    const far = start + 10n ** 90n * 365n * DAY
    const begun = performance.now()
    const result = expand(monthly, ctx, [far, far + 400n * DAY], 100)
    const elapsed = performance.now() - begun
    expect(result.items.length).toBeGreaterThanOrEqual(7)
    expect(result.items.length).toBeLessThanOrEqual(9)
    expect(elapsed).toBeLessThan(50)
  })

  test('next occurrences', () => {
    const leap = rule({ freq: { level: 'year' } })
    const ctx = context(g(2024, 'feb', 29, 10))
    const keys = nextOccurrences(leap, ctx, g(2025, 'jan', 1), 3).map((item) => item.key)
    expect(keys).toEqual(['4', '8', '12'])
    const bounded = rule({ freq: { level: 'year' }, limit: UNTIL_LIMIT })
    const until = context(g(2024, 'feb', 29, 10), { until: g(2030, 'jan', 1) })
    expect(nextOccurrences(bounded, until, 0n, 5).map((item) => item.key)).toEqual(['0', '4'])
    expect(nextOccurrences(bounded, until, g(2031, 'jan', 1), 5)).toEqual([])
  })

  test('a series without occurrences', () => {
    const timed = rule({
      freq: { level: 'year' },
      time: { fields: { hour: '9' } },
      limit: UNTIL_LIMIT,
    })
    const start = g(2024, 'mar', 1, 15)
    const ctx = context(start, { until: start })
    const bounds = seriesBounds(timed, ctx)
    expect([bounds.firstStart, bounds.count]).toEqual([null, 0n])
    expect(expand(timed, ctx, [0n, D], 10).items).toEqual([])
  })

  test(
    'aperiodic rules count only nearby',
    () => {
      // Year-number `in` filters aren't periodic: counting falls back to enumerating periods,
      // which works near the start and is `rule.too_complex_to_count` far from it.
      const years = rule({
        freq: { level: 'year' },
        filters: [{ in: ['2001', '2003'] }],
        limit: UNTIL_LIMIT,
      })
      const start = g(2000, 'jan', 1)
      const near = seriesBounds(years, context(start, { until: g(2010, 'jan', 1) }))
      expect([near.firstStart, near.lastStart, near.count]).toEqual([
        g(2001, 'jan', 1),
        g(2003, 'jan', 1),
        2n,
      ])
      const far = context(start, { until: start + 10n ** 30n })
      expect(errorCode(() => seriesBounds(years, far))).toBe('rule.too_complex_to_count')
    },
    SLOW,
  )

  test('reversed and empty windows', () => {
    const yearly = rule({ freq: { level: 'year' } })
    const ctx = context(g(2000, 'jan', 1))
    expect(expand(yearly, ctx, [g(2010, 'jan', 1), g(2005, 'jan', 1)]).items).toEqual([])
    const instant = expand(yearly, ctx, [g(2010, 'jan', 1), g(2010, 'jan', 1)])
    expect(defined(instant.items[0]).key).toBe('10')
  })

  test('keys ignore the time of day', () => {
    const keys = (fields: Record<string, string>): string[] => {
      const found = rule({
        freq: { cycle: 'week' },
        select: { path: [{ level: 'day', values: ['mon', 'fri'] }] },
        time: { fields },
      })
      const ctx = context(g(2024, 'jan', 1), { calendar: WEEK })
      const window = [g(2024, 'jan', 1), g(2024, 'feb', 1)] as const
      return expand(found, ctx, window).items.map((item) => item.key)
    }
    expect(keys({ hour: '6' })).toEqual(keys({ hour: '21', minute: '45' }))
    expect(keys({ hour: '6' }).slice(0, 3)).toEqual(['0.0', '0.1', '1.0'])
  })

  test('round filters and selectors', () => {
    const monday = g(2024, 'jan', 1, 9)
    const ctx = context(monday, { calendar: WEEK })
    const window = [monday, monday + 12n * 7n * DAY] as const
    const items = (members: Members) =>
      expand(rule({ freq: { cycle: 'week' }, ...members }), ctx, window).items
    const keys = (members: Members): string[] => items(members).map((item) => item.key)
    const floor = (key: string): bigint => BigInt(defined(key.split('.')[0]))

    const filters = [{ all: [{ mod: '2', eq: '0' }, { not: { mod: '3', eq: '0' } }] }]
    // round 0: the anchor (Sat 1 Jan 2000) week
    const first = (monday - g(1999, 'dec', 27, 9)) / (7n * DAY)
    for (const k of keys({ filters }).map(floor)) {
      expect((first + k) % 2n).toBe(0n)
      expect((first + k) % 3n).not.toBe(0n)
    }
    const any = [{ any: [{ mod: '4', eq: String((first + 1n) % 4n) }] }]
    expect(keys({ filters: any })).toEqual(['1', '5', '9'])
    const sundays = { select: { path: [{ level: 'day', values: ['-1'] }] } }
    expect(keys(sundays).slice(0, 2)).toEqual(['0', '1'])
    expect(defined(items(sundays)[0]).start).toBe(g(2024, 'jan', 7, 9))
    const nth = { id: 'week', values: ['sat', 'sun'], nth: ['1'] }
    const weekend = items({ select: { path: [{ level: 'day', cycle: nth }] } })
    expect(weekend.slice(0, 2).map((item) => item.start)).toEqual([
      g(2024, 'jan', 6, 9),
      g(2024, 'jan', 7, 9),
    ])
    const all = items({ select: { path: [{ level: 'day', all: true }] } })
    expect(all.slice(0, 2).map((item) => item.key)).toEqual(['0.0', '0.1'])
  })

  test('selectors can skip several levels', () => {
    const hour100 = rule({
      freq: { level: 'year' },
      select: { path: [{ level: 'hour', values: ['100'] }] },
    })
    const ctx = context(g(2024, 'jan', 1), { calendar: WEEK })
    const found = expand(hour100, ctx, [g(2024, 'jan', 1), g(2025, 'jan', 1)]).items
    expect(found.map((item) => item.start)).toEqual([g(2024, 'jan', 5, 4)]) // hours count from 0
  })

  test('sparse windows beyond the visit limit are estimated', () => {
    const days = rule({ freq: { level: 'day' }, time: { fields: { hour: '9' } } })
    const ctx = context(g(2000, 'jan', 1, 9), { calendar: WEEK })
    const result = expand(days, ctx, [g(2000, 'jan', 1), g(2060, 'jan', 1)], 10)
    expect(result.truncated).toBe(true)
    const estimate = defined(result.estimatedCount)
    expect(estimate >= 21915n - 400n && estimate <= 21915n + 400n).toBe(true) // sampled
  })

  test('truncated interval rules are counted exactly', () => {
    const hourly = rule({ kind: 'interval', every: '3600' })
    const ctx = context(0n, { calendar: null })
    expect(expand(hourly, ctx, [0n, 1000n * 3600n], 10)).toEqual({
      items: [],
      truncated: true,
      estimatedCount: 1000n,
    })
    expect(expand(hourly, ctx, [0n, 20n * 3600n], 10)).toEqual({
      items: [],
      truncated: true,
      estimatedCount: 20n,
    })
  })

  test('calendar duration ends', () => {
    const monthly = rule({ freq: { level: 'month' } })
    const ctx = context(g(2024, 'jan', 31), { calendar: WEEK, end: MONTH })
    const found = expand(monthly, ctx, [g(2024, 'feb', 20), g(2024, 'feb', 21)]).items
    expect(found.map((item) => [item.start, item.end])).toEqual([
      [g(2024, 'jan', 31), g(2024, 'feb', 29)],
    ])
  })

  test('slot ids below skipped levels use sub-keys', () => {
    // A slot id is unique only within its template: picked across months it gets k.j keys.
    const midyear = calendar('intercalary-day')
    const bySlot = rule({
      freq: { level: 'year' },
      select: { path: [{ level: 'day', values: ['midyear'] }] },
    })
    const ctx = context(0n, { calendar: midyear })
    const found = expand(bySlot, ctx, [0n, 91n * 3n]).items
    expect(found.map((item) => [item.key, item.start])).toEqual([
      ['0.0', 60n],
      ['1.0', 151n],
      ['2.0', 242n],
    ])
    const byNumber = rule({
      freq: { level: 'year' },
      select: { path: [{ level: 'day', values: ['61'] }] },
    })
    expect(expand(byNumber, ctx, [0n, 91n * 3n]).items.map((item) => item.key)).toEqual([
      '0',
      '1',
      '2',
    ])
  })

  test('too many positions', () => {
    const { definition, context: compileContext } = load('cycles-showcase')
    const count = '/regimes/0/templates/year/sequence/0/run/count'
    expect(at(definition, count)).toBeDefined()
    const huge = compiled(patched(definition, { [count]: '6000' }), compileContext) // 6,000 x 20 days
    const ctx = context(1_000_000n, { calendar: huge })
    const everyDay = rule({
      freq: { level: 'year' },
      select: { path: [{ level: 'day', all: true }] },
    })
    expect(errorCode(() => expand(everyDay, ctx, [1_000_000n, 1_000_010n]))).toBe(
      'rule.too_many_positions',
    )
    const firstDays = rule({ freq: { level: 'year' }, select: { path: [day(['1'])] } })
    expect(defined(expand(firstDays, ctx, [1_000_000n, 1_000_010n]).items[0]).key).toBe('0')
  })

  test('occurrence keys', () => {
    const yearly = rule({ freq: { level: 'year' } })
    const ctx = context(g(2000, 'jan', 1))
    expect(occurrence(yearly, ctx, '3').start).toBe(g(2003, 'jan', 1))
    for (const key of ['03', '3.0', '-1', 'x']) {
      expect(errorCode(() => occurrence(yearly, ctx, key))).toBe('not_found')
    }
  })

  test('exclusions skip occurrences and merge', () => {
    const yearly = rule({
      freq: { level: 'year' },
      exclusions: [
        { from: UNTIL, to: UNTIL },
        { from: UNTIL, to: UNTIL },
        { from: UNTIL, to: UNTIL },
      ],
    })
    const resolved = {
      '/exclusions/0/from': g(2002, 'jan', 1),
      '/exclusions/0/to': g(2003, 'jun', 1),
      '/exclusions/1/from': g(2003, 'jan', 1),
      '/exclusions/1/to': g(2004, 'jan', 2),
      '/exclusions/2/from': g(2006, 'jan', 1),
      '/exclusions/2/to': g(2006, 'jan', 1),
    }
    const ctx = context(g(2000, 'jan', 1), { resolved })
    const found = expand(yearly, ctx, [g(2000, 'jan', 1), g(2008, 'jan', 1)]).items
    expect(found.map((item) => item.key)).toEqual(['0', '1', '5', '6', '7'])
    expect(occurrenceNumber(yearly, ctx, '5')).toBe(3n)
    expect(errorCode(() => occurrence(yearly, ctx, '3'))).toBe('not_found')
    expect(occurrenceAt(yearly, ctx, g(2003, 'jan', 1))).toBeNull()
  })
})

describe('validation', () => {
  const codes = (found: RecurrenceRule, ctx: RecurrenceContext): [string, string][] =>
    validateRule(found, ctx).map((e) => [e.code, e.path])

  test('errors', () => {
    const start = g(2000, 'jan', 1)
    expect(codes(rule({ freq: { level: 'year' } }), context(start, { calendar: null }))).toEqual([
      ['rule.unknown_calendar', '/calendar_id'],
    ])
    expect(codes(rule({ freq: { level: 'week' } }), context(start))).toEqual([
      ['rule.bad_freq_level', '/freq/level'],
    ])
    const month = rule({ freq: { level: 'day' }, time: { fields: { month: '1' } } })
    expect(codes(month, context(start))).toEqual([['rule.bad_time_fields', '/time/fields/month']])
    const gap = rule({ freq: { level: 'day' }, time: { fields: { hour: '9', second: '0' } } })
    expect(codes(gap, context(start))).toEqual([['rule.bad_time_fields', '/time/fields']])
    const none = rule({ freq: { level: 'day' }, time: { fields: {} } })
    expect(codes(none, context(start))).toEqual([['rule.bad_time_fields', '/time/fields']])
    const until = rule({ freq: { level: 'year' }, limit: UNTIL_LIMIT })
    expect(codes(until, context(start))).toEqual([['anchor.unresolved', '/limit/until']])
    expect(codes(until, context(start, { until: start - 1n }))).toEqual([
      ['rule.until_before_start', '/limit/until'],
    ])
    const explicit: EndSpec = { kind: 'time_point', time_point: UNTIL as never }
    expect(codes(rule({ freq: { level: 'year' } }), context(start, { end: explicit }))).toEqual([
      ['rule.series_end_not_duration', '/end'],
    ])
    const interval = rule({ kind: 'interval', every: '10' })
    const noCalendar = context(start, { calendar: null, end: MONTH })
    expect(codes(interval, noCalendar)).toEqual([
      ['rule.unknown_calendar', '/end/duration/calendar_id'],
    ])
    try {
      expand(interval, noCalendar, [0n, 1n])
      expect.unreachable()
    } catch (error) {
      expect(error).toBeInstanceOf(RecurrenceError)
      expect((error as RecurrenceError).code).toBe('rule.invalid')
      expect(defined((error as RecurrenceError).errors[0]).code).toBe('rule.unknown_calendar')
    }
  })

  test('a start mismatch is a warning', () => {
    const timed = rule({ freq: { level: 'month' }, time: { fields: { hour: '9', minute: '0' } } })
    const found = validateRule(timed, context(g(2023, 'jan', 31, 15)))
    expect(found.map((e) => [e.code, e.severity])).toEqual([
      ['rule.series_start_not_occurrence', 'warning'],
    ])
    expect(validateRule(timed, context(g(2023, 'jan', 31, 9)))).toEqual([])
  })

  test('advanced errors', () => {
    const errors = (members: Members): [string, string][] =>
      validateRule(rule(members), context(g(2000, 'jan', 3), { calendar: WEEK }))
        .filter((e) => e.severity === 'error')
        .map((e) => [e.code, e.path])
    const first = day(['1'])
    const cases: [Members, [string, string][]][] = [
      [{ freq: { cycle: 'fortnight' } }, [['rule.bad_freq_level', '/freq/cycle']]],
      [
        { freq: { level: 'month' }, filters: [{ mod: '2', eq: '2' }] },
        [['rule.bad_filter', '/filters/0/eq']],
      ],
      [{ freq: { cycle: 'week' }, filters: [{ in: ['1'] }] }, [['rule.bad_filter', '/filters/0']]],
      [
        { freq: { level: 'month' }, filters: [{ cycle: 'week', in: ['mon'] }] },
        [['rule.bad_filter', '/filters/0/cycle']],
      ],
      [
        { freq: { level: 'day' }, filters: [{ not: { cycle: 'week', in: ['moon'] } }] },
        [['rule.unknown_slot', '/filters/0/not/in/0']],
      ],
      [
        { freq: { level: 'month' }, filters: [{ any: [{ in: ['frostfall'] }] }] },
        [['rule.unknown_slot', '/filters/0/any/0/in/0']],
      ],
      [
        { freq: { level: 'month' }, filters: [{ all: [{ in: ['frostfall'] }] }] },
        [['rule.unknown_slot', '/filters/0/all/0/in/0']],
      ],
      [
        { freq: { level: 'month' }, select: { path: [{ level: 'month', all: true }] } },
        [['rule.bad_selector_level', '/select/path/0/level']],
      ],
      [
        { freq: { level: 'year' }, select: { path: [first, { level: 'month', all: true }] } },
        [['rule.bad_selector_level', '/select/path/1/level']],
      ],
      [
        { freq: { cycle: 'week' }, select: { path: [{ level: 'hour', all: true }] } },
        [['rule.bad_selector_level', '/select/path/0/level']],
      ],
      [
        { freq: { level: 'year' }, select: { path: [{ level: 'month', values: ['x'] }] } },
        [['rule.unknown_slot', '/select/path/0/values/0']],
      ],
      [
        { freq: { cycle: 'week' }, select: { path: [day(['8'])] } },
        [['rule.unknown_slot', '/select/path/0/values/0']],
      ],
      [
        {
          freq: { level: 'year' },
          select: { path: [{ level: 'month', cycle: { id: 'week', values: ['mon'] } }] },
        },
        [['rule.bad_selector_level', '/select/path/0/cycle/id']],
      ],
      [
        { freq: { level: 'year' }, select: { path: [week(['moon'])] } },
        [['rule.unknown_slot', '/select/path/0/cycle/values/0']],
      ],
      [
        { freq: { level: 'month' }, select: { path: [week(['mon'], ['1', '0'])] } },
        [['rule.bad_nth', '/select/path/0/cycle/nth/1']],
      ],
      [
        { freq: { level: 'year' }, select: { path: [first] }, time: { fields: { day: '2' } } },
        [['rule.bad_time_fields', '/time/fields/day']],
      ],
      [{ freq: { level: 'year' }, select: { path: [first] }, time: { fields: { hour: '9' } } }, []],
    ]
    for (const [members, expected] of cases) expect(errors(members)).toEqual(expected)
  })

  test('reset cycles have no rounds', () => {
    const showcase = calendarOf('cycles-showcase')
    const found = validateRule(
      rule({ freq: { cycle: 'decan' } }),
      context(1_000_000n, { calendar: showcase }),
    )
    expect(found.map((e) => [e.code, e.path])).toEqual([
      ['rule.cycle_not_continuous', '/freq/cycle'],
    ])
  })

  test('exclusions', () => {
    const excluded = rule({ freq: { level: 'year' }, exclusions: [{ from: UNTIL, to: UNTIL }] })
    const start = g(2000, 'jan', 1)
    const withRanges = (resolved: Record<string, bigint>) =>
      context(start, { calendar: WEEK, resolved })
    expect(codes(excluded, withRanges({}))).toEqual([
      ['anchor.unresolved', '/exclusions/0/from'],
      ['anchor.unresolved', '/exclusions/0/to'],
    ])
    const reversed = { '/exclusions/0/from': start + 10n, '/exclusions/0/to': start }
    expect(codes(excluded, withRanges(reversed))).toEqual([['rule.bad_exclusion', '/exclusions/0']])
    const empty = { '/exclusions/0/from': start, '/exclusions/0/to': start }
    expect(seriesBounds(excluded, withRanges(empty)).firstStart).toBe(start)
  })
})

// --- counting (recurrence III) -------------------------------------------------------------------

const COUNTING_RULES: Members[] = [
  { freq: { level: 'month' }, time: { fields: { day: '30' } } },
  { freq: { level: 'month' }, interval: '5', filters: [{ mod: '3', eq: '1' }] },
  { freq: { level: 'year' }, filters: [{ mod: '4', eq: '2' }] },
  { freq: { level: 'day' }, interval: '3', filters: [{ mod: '7', eq: '2', of: 'ordinal' }] },
  { freq: { level: 'year' }, select: { path: [{ level: 'month', values: ['yule', '4'] }] } },
  { freq: { level: 'year' }, select: { path: [day(['-1', '100'])] } },
  {
    freq: { level: 'day' },
    filters: [
      {
        all: [
          { any: [{ mod: '7', eq: '2', of: 'ordinal' }, { in: ['1'] }] },
          { not: { mod: '2', eq: '0', of: 'ordinal' } },
        ],
      },
    ],
  },
  { freq: { level: 'year' }, interval: '10' },
]

function voidYears(): CompiledCalendar {
  const { definition, context: compileContext } = load('intercalary-exceptions')
  const exceptions = at(definition, '/regimes/0/top/exceptions') as unknown[]
  return compiled(
    patched(definition, {
      '/regimes/0/templates/year_void': {
        level: 'year',
        sequence: [{ id: 'void', template: 'm30', name: 'Void', intercalary: true }],
      },
      '/regimes/0/top/exceptions': [
        ...exceptions,
        { year: '2', template: 'year_void' },
        { year: '30', template: 'year_void' },
      ],
    }),
    compileContext,
  )
}

function checkCounter(plan: CalendarPlan, periods: number): bigint {
  const counter = defined(plan.counterOf())
  let running = 0n
  for (let k = 0n; k < BigInt(periods); k++) {
    expect([k, counter.count(k)]).toEqual([k, running])
    running += plan.periodCount(k)
  }
  return running
}

describe('counting', () => {
  const calendars = {
    'intercalary-exceptions': () => calendar('intercalary-exceptions'),
    'void-years': voidYears,
  }
  test.each(
    Object.keys(calendars).flatMap((name) =>
      COUNTING_RULES.map((members, i) => ({ name, i, members })),
    ),
  )('super-period counts match enumeration ($name, rule $i)', ({ name, members }) => {
    const compiledCalendar = calendars[name as keyof typeof calendars]()
    for (const start of [0n, 1_000_000n - 9n * 24n, 1_000_000n + 400n * 24n]) {
      const ctx = context(start, { calendar: compiledCalendar })
      const plan = new CalendarPlan(calendarRule(members), ctx, compiledCalendar, D)
      const counter = defined(plan.counterOf())
      const running = checkCounter(plan, 600)
      for (const i of [1n, 7n, running / 2n, running]) {
        if (i < 1n) continue
        const found = defined(counter.periodOf(i))
        expect(counter.count(found) < i && i <= counter.count(found + 1n)).toBe(true)
      }
    }
  })

  test('weekly counts match enumeration', () => {
    const shire = calendar('shire-week')
    const members = { freq: { cycle: 'week' }, select: { path: [day(['-1'])] } }
    const plan = new CalendarPlan(
      calendarRule(members),
      context(10_000_000n, { calendar: shire }),
      shire,
      D,
    )
    checkCounter(plan, 400)
  })

  test('a count limit far away is fast', () => {
    // Acceptance: count = 10^12 on a yearly rule computes series bounds in < 100 ms.
    const fresh = calendarOf('gregorian-week') // no cached counters
    const yearly = rule({
      freq: { level: 'year' },
      limit: { kind: 'count', count: '1000000000000' },
    })
    const begun = performance.now()
    const bounds = seriesBounds(yearly, context(g(2024, 'feb', 29, 9), { calendar: fresh }))
    const elapsed = performance.now() - begun
    expect(bounds.count).toBe(10n ** 12n)
    expect(elapsed).toBeLessThan(100)
  })

  test('rules that never occur are found at once', () => {
    // An interval that never meets the filter: no occurrence, and no long scan.
    const starved = rule({
      freq: { level: 'year' },
      interval: '2',
      filters: [{ mod: '2', eq: '1' }],
    })
    const ctx = context(g(2024, 'jan', 1), { calendar: WEEK })
    const begun = performance.now()
    expect(seriesBounds(starved, ctx).firstStart).toBeNull()
    expect(nextOccurrences(starved, ctx, 0n, 3)).toEqual([])
    expect(performance.now() - begun).toBeLessThan(500)
  })

  test(
    'too complex rules are estimated',
    () => {
      const showcase = calendarOf('cycles-showcase')
      const huge = rule({
        freq: { level: 'day' },
        filters: [{ mod: '999983', eq: '0', of: 'ordinal' }],
      })
      const ctx = context(1_000_000n, { calendar: showcase })
      const found = countInWindow(huge, ctx, [1_000_000n, 1_000_000n + 10n ** 12n])
      expect(found.exact).toBe(false)
      expect(found.count >= 0n).toBe(true)
      const key = String(10n ** 9n * 999983n)
      expect(errorCode(() => occurrenceNumber(huge, ctx, key))).toBe('rule.too_complex_to_count')
    },
    SLOW,
  )

  test('occurrence_at without occurrences', () => {
    const yearly = rule({ freq: { level: 'year' } })
    const ctx = context(g(2024, 'jan', 1), { calendar: WEEK })
    expect(occurrenceAt(yearly, ctx, g(2023, 'jun', 1))).toBeNull()
    expect(occurrenceAt(yearly, ctx, g(2025, 'jan', 1))).toBe('1')
    // instants: only at their start
    expect(occurrenceAt(yearly, ctx, g(2025, 'jan', 1, 9))).toBeNull()
  })

  test(
    'cycle filters count like enumeration',
    () => {
      const showcase = calendarOf('cycles-showcase')
      const members = {
        freq: { level: 'day' },
        filters: [
          {
            any: [
              { cycle: 'veintena', in: ['0', '7'] },
              { cycle: 'trecena', in: ['13'] },
            ],
          },
          { not: { mod: '2', eq: '0', of: 'ordinal' } },
        ],
      }
      const plan = new CalendarPlan(
        calendarRule(members),
        context(1_000_000n, { calendar: showcase }),
        showcase,
        D,
      )
      // 365-day years: the 20-day veintena realigns after 4 years, the 13-day trecena after 13
      // (and the ordinal parity after 2): the super-period is 52 years of days.
      expect(defined(plan.counterOf()).q).toBe(52n * 365n)
      checkCounter(plan, 3000)
    },
    SLOW,
  )
})

// --- edge cases ----------------------------------------------------------------------------------

describe('edge cases', () => {
  const DAY_END: EndSpec = {
    kind: 'duration',
    duration: { kind: 'calendar', calendar_id: 'c', amounts: { day: '1' }, sign: 1 },
  }

  test('rules whose periods never hold a position', () => {
    const day400 = { freq: { level: 'year' }, select: { path: [day(['400'])] } }
    const ctx = context(g(2024, 'jan', 1))
    expect(seriesBounds(rule(day400), ctx)).toEqual({
      firstStart: null,
      lastStart: null,
      lastEnd: null,
      count: null,
    })
    const counted = rule({ ...day400, limit: { kind: 'count', count: '5' } })
    expect(seriesBoundsToJson(seriesBounds(counted, ctx))).toEqual({
      first_start: null,
      last_start: null,
      last_end: null,
      count: '0',
    })
    expect(nextOccurrences(rule(day400), ctx, 0n, 3)).toEqual([])
  })

  test('occurrence_at with calendar durations', () => {
    const weekly = rule({ freq: { level: 'day' }, interval: '7' })
    const monthLong = context(g(2024, 'jan', 1), { end: MONTH })
    expect(occurrenceAt(weekly, monthLong, g(2024, 'jan', 20))).toBe('2') // the latest start
    const firsts = rule({ freq: { level: 'month' }, select: { path: [day(['1'])] } })
    const fromJanuary = context(g(2024, 'jan', 1), { end: DAY_END })
    expect(occurrenceAt(firsts, fromJanuary, g(2024, 'jan', 1, 5))).toBe('0')
    expect(occurrenceAt(firsts, fromJanuary, g(2024, 'jan', 15))).toBeNull()
    const fromDecember = context(g(2023, 'dec', 1), { end: DAY_END })
    expect(occurrenceAt(firsts, fromDecember, g(2024, 'jan', 15))).toBeNull()
  })

  test('occurrence_at before the first occurrence', () => {
    const sparse = rule({ freq: { level: 'year' }, filters: [{ mod: '500', eq: '0' }] })
    expect(occurrenceAt(sparse, context(g(2001, 'jan', 1)), g(2300, 'jan', 1))).toBeNull()
    const newYear = rule({ freq: { level: 'year' }, select: { path: [day(['1'])] } })
    const start = g(2024, 'jan', 2)
    expect(occurrenceAt(newYear, context(start), start + 100n)).toBeNull()
    const yearEnd = rule({ freq: { level: 'year' }, select: { path: [day(['-1'])] } })
    expect(occurrenceAt(yearEnd, context(g(2024, 'jan', 1)), g(2024, 'jun', 1))).toBeNull()
  })

  test('window counts with long calendar durations are estimated', () => {
    const seconds = rule({ freq: { level: 'second' } })
    const fourHours: EndSpec = {
      kind: 'duration',
      duration: { kind: 'calendar', calendar_id: 'c', amounts: { hour: '4' }, sign: 1 },
    }
    const ctx = context(g(2024, 'jan', 1), { end: fourHours })
    const w0 = g(2024, 'jan', 2)
    // 3,600 starts inside the window and 14,399 earlier ones, too many to check one by one
    expect(countInWindow(seconds, ctx, [w0, w0 + 3600n])).toEqual({ count: 17999n, exact: false })
  })

  test('expand stops visiting periods once the items overflow', () => {
    const hours = rule({ freq: { level: 'day' }, select: { path: [{ level: 'hour', all: true }] } })
    const start = g(2024, 'jan', 1)
    const found = expand(hours, context(start), [start, start + 30n * DAY], 10)
    expect(expansionToJson(found)).toEqual({ items: [], truncated: true, estimated_count: '720' })
  })

  test('exclusions with the same start merge', () => {
    const yearly = rule({
      freq: { level: 'year' },
      exclusions: [
        { from: UNTIL, to: UNTIL },
        { from: UNTIL, to: UNTIL },
        { from: UNTIL, to: UNTIL },
      ],
    })
    const resolved = {
      '/exclusions/0/from': g(2002, 'jan', 1),
      '/exclusions/0/to': g(2004, 'jan', 2),
      '/exclusions/1/from': g(2002, 'jan', 1),
      '/exclusions/1/to': g(2002, 'jan', 2),
      '/exclusions/2/from': g(2002, 'jan', 1),
      '/exclusions/2/to': g(2002, 'jan', 2),
    }
    const ctx = context(g(2000, 'jan', 1), { resolved })
    const keys = expand(yearly, ctx, [g(2000, 'jan', 1), g(2006, 'jan', 1)]).items
    expect(keys.map((item) => item.key)).toEqual(['0', '1', '5'])
  })

  test('cycle matches skip units excluded from the cycle', () => {
    const shire = calendar('shire-week')
    const sterdays = rule({
      freq: { level: 'year' },
      select: {
        path: [{ level: 'day', cycle: { id: 'week', values: ['sterday'], nth: ['1', '-1'] } }],
      },
    })
    const ctx = context(10_000_000n, { calendar: shire })
    const found = expand(sterdays, ctx, [10_000_000n, 10_000_000n + 3n * 366n]).items
    expect(found.map((item) => item.key).slice(0, 2)).toEqual(['0.0', '0.1'])
    for (const item of found) expect(cycleValue(shire, item.start, 'week')?.n).toBe(1)
  })

  test('nth in rounds counts from the end and ignores missing matches', () => {
    const saturdays = rule({
      freq: { cycle: 'week' },
      select: {
        path: [{ level: 'day', cycle: { id: 'week', values: ['sat'], nth: ['-1', '5'] } }],
      },
    })
    const ctx = context(g(2024, 'jan', 1, 9), { calendar: WEEK })
    const found = expand(saturdays, ctx, [g(2024, 'jan', 1), g(2024, 'jan', 15)]).items
    expect(found.map((item) => [item.key, item.start])).toEqual([
      ['0.0', g(2024, 'jan', 6, 9)],
      ['1.0', g(2024, 'jan', 13, 9)],
    ])
  })

  test('cycle values without ids and out-of-range round positions', () => {
    const showcase = calendarOf('cycles-showcase')
    const unnamed = rule({ freq: { level: 'day' }, filters: [{ cycle: 'trecena', in: ['foo'] }] })
    expect(
      validateRule(unnamed, context(1_000_000n, { calendar: showcase })).map((e) => e.path),
    ).toEqual(['/filters/0/in/0'])
    const tooFar = rule({ freq: { cycle: 'week' }, select: { path: [day(['-8'])] } })
    expect(
      validateRule(tooFar, context(g(2024, 'jan', 1), { calendar: WEEK })).map((e) => e.code),
    ).toEqual(['rule.unknown_slot'])
  })

  test('counter and prefix caches keep the 64 most recent rules', () => {
    const fresh = calendarOf('gregorian-week')
    const ctx = context(g(2024, 'jan', 1), { calendar: fresh })
    for (let m = 2; m < 2 + 70; m++) {
      const members = { freq: { level: 'year' }, filters: [{ mod: String(m), eq: '0' }] }
      const plan = new CalendarPlan(calendarRule(members), ctx, fresh, D)
      plan.countBefore(g(2030, 'jan', 1)) // near: enumerated
      plan.counterOf()
    }
    const regime = defined(fresh.regimes[0])
    expect((regime.cache.get('recurrence-counters') as Map<string, unknown>).size).toBe(64)
    expect((regime.cache.get('recurrence-prefixes') as Map<string, unknown>).size).toBe(64)
  })

  test('length bounds', () => {
    const yearly = calendarRule({ freq: { level: 'year' } })
    const plan = (end: EndSpec) => new CalendarPlan(yearly, context(0n, { end }), GREGORIAN, D)
    expect(plan(INSTANT).upperLength()).toBe(0n)
    const back: EndSpec = { kind: 'duration', duration: { kind: 'base', units: '-5' } }
    expect([plan(back).exactLength(), plan(back).upperLength()]).toEqual([-5n, 5n])
    const forward: EndSpec = { kind: 'duration', duration: { kind: 'base', units: '5' } }
    expect(plan(forward).upperLength()).toBe(5n)
  })

  test('occurrence_at past the end of a calendar-length occurrence', () => {
    const yearly = rule({ freq: { level: 'year' } })
    const ctx = context(g(2023, 'feb', 1), { end: MONTH })
    expect(occurrenceAt(yearly, ctx, g(2023, 'feb', 28))).toBe('0')
    expect(occurrenceAt(yearly, ctx, g(2023, 'mar', 2))).toBeNull()
  })

  test('count limits skip missing positions', () => {
    const febMar = rule({
      freq: { level: 'year' },
      select: { path: [{ level: 'month', values: ['2', '3'] }] },
      limit: { kind: 'count', count: '3' },
    })
    // the start's day 30 doesn't exist in February: only March 30 occurs
    const bounds = seriesBounds(febMar, context(g(2023, 'jan', 30)))
    expect([bounds.firstStart, bounds.lastStart, bounds.count]).toEqual([
      g(2023, 'mar', 30),
      g(2025, 'mar', 30),
      3n,
    ])
  })

  test('cycle matches without nth pick every match', () => {
    const mondays = rule({
      freq: { level: 'month' },
      select: { path: [{ level: 'day', cycle: { id: 'week', values: ['mon'] } }] },
    })
    const ctx = context(g(2024, 'jan', 1), { calendar: WEEK })
    const found = expand(mondays, ctx, [g(2024, 'jan', 1), g(2024, 'feb', 1)]).items
    expect(found.map((item) => item.start)).toEqual(
      [1, 8, 15, 22, 29].map((n) => g(2024, 'jan', n)),
    )
  })

  test(
    'aperiodic count limits beyond the scan limit are too complex',
    () => {
      const years = rule({
        freq: { level: 'year' },
        filters: [{ in: ['2001', '2003'] }],
        limit: { kind: 'count', count: '200000' },
      })
      expect(errorCode(() => seriesBounds(years, context(g(2000, 'jan', 1))))).toBe(
        'rule.too_complex_to_count',
      )
    },
    SLOW,
  )
})
