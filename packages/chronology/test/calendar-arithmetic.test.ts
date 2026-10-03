// Calendar arithmetic: add, diff, isUniform and duration bounds (chronology-engine.md §9),
// mirroring the Python engine's backend/tests/chronology/test_calendar_arithmetic.py.
// Vectors: cases/arithmetic/.
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import {
  add,
  type CompiledCalendar,
  DateError,
  diff,
  differenceDuration,
  durationUpperBound,
  fromFields,
  isUniform,
  type Overflow,
  toFields,
} from '../src/calendar'
import { defined } from '../src/calendar/compiled'
import type { CalendarDuration } from '../src/schema.gen'
import { at, compiled, load, patched } from './calendars'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 500 : 50
const params = { numRuns: RUNS, seed: 20261003 }

/** intercalary-exceptions plus exception years 2 and −7 whose only month is intercalary. */
function withVoidYears(): CompiledCalendar {
  const { definition, context } = load('intercalary-exceptions')
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
        { year: '-7', template: 'year_void' },
      ],
    }),
    context,
  )
}

const NAMES = [
  'gregorian-seconds',
  'alternating-years',
  'intercalary-exceptions',
  'intercalary-day',
  'julian-gregorian',
]
const CALENDARS = new Map<string, CompiledCalendar>(
  NAMES.map((name) => {
    const { definition, context } = load(name)
    return [name, compiled(definition, context)]
  }),
)
CALENDARS.set('void-years', withVoidYears())
const calendar = (name: string): CompiledCalendar => defined(CALENDARS.get(name))
const GREGORIAN = calendar('gregorian-seconds')
const JULIAN_GREGORIAN = calendar('julian-gregorian')

const names = fc.constantFrom(...CALENDARS.keys())
const moments = fc.oneof(
  fc.bigInt({ min: 0n, max: 2n * 10n ** 6n }),
  fc.bigInt({ min: 99_000_000_000_000n, max: 101_000_000_000_000n }),
  fc.bigInt({ min: 435n * 10n ** 15n - 10n ** 12n, max: 435n * 10n ** 15n + 10n ** 12n }),
  fc.bigInt({ min: 0n, max: 10n ** 120n }),
)
const amounts = fc.oneof(fc.bigInt({ min: 0n, max: 30n }), fc.bigInt({ min: 0n, max: 10n ** 40n }))

function duration(sign: 1 | -1, levels: Record<string, bigint | number>): CalendarDuration {
  const strings = Object.fromEntries(Object.entries(levels).map(([k, n]) => [k, String(n)]))
  return { kind: 'calendar', calendar_id: 'cal', amounts: strings, sign }
}

/** A calendar and a duration of 1–3 of its levels. */
const withDuration = names.chain((name) => {
  const levels = calendar(name).levels
  return fc
    .tuple(
      fc.uniqueArray(fc.constantFrom(...levels), { minLength: 1, maxLength: 3 }),
      fc.constantFrom(1 as const, -1 as const),
      fc.array(amounts, { minLength: 3, maxLength: 3 }),
    )
    .map(([chosen, sign, values]) => {
      const entries = chosen.map((level, i) => [level, defined(values[i])] as const)
      return [name, duration(sign, Object.fromEntries(entries))] as const
    })
})

function code(call: () => unknown): string | null {
  try {
    call()
  } catch (error) {
    if (error instanceof DateError) return error.code
    throw error
  }
  return null
}

// --- properties ----------------------------------------------------------------------------------

describe('properties', () => {
  test('diff brackets the later moment', () => {
    fc.assert(
      fc.property(names, moments, moments, fc.nat(), fc.nat(), (name, a, b, i, j) => {
        const cal = calendar(name)
        const count = cal.levels.length
        const [low, high] = [i % count, j % count].sort((x, y) => x - y) as [number, number]
        const [largest, smallest] = [defined(cal.levels[high]), defined(cal.levels[low])]
        const [t1, t2] = a < b ? [a, b] : [b, a]
        const found = diff(cal, t1, t2, largest, smallest)
        expect(found.sign).toBe(1)
        expect([...found.amounts.keys()]).toEqual(cal.levels.slice(low, high + 1).reverse())
        const reached = add(cal, t1, differenceDuration(found, 'cal'))
        const amounts = new Map(found.amounts)
        amounts.set(smallest, defined(amounts.get(smallest)) + 1n)
        const next = add(cal, t1, duration(1, Object.fromEntries(amounts)))
        expect(reached <= t2 && t2 < next).toBe(true)
        expect(found.base).toBe(t2 - reached)
        const reverse = diff(cal, t2, t1, largest, smallest)
        expect(reverse).toEqual({ ...found, sign: t1 < t2 ? -1 : 1 })
      }),
      params,
    )
  })

  test('the upper bound holds', () => {
    fc.assert(
      fc.property(withDuration, moments, ([name, moved], t) => {
        const cal = calendar(name)
        const distance = add(cal, t, moved) - t
        expect((distance < 0n ? -distance : distance) <= durationUpperBound(cal, moved)).toBe(true)
      }),
      params,
    )
  })

  test('steps are strictly increasing', () => {
    fc.assert(
      fc.property(names, moments, fc.nat(), fc.nat({ max: 50 }), (name, t, pick, n) => {
        const cal = calendar(name)
        const level = defined(cal.levels[pick % cal.levels.length])
        const here = add(cal, t, duration(1, { [level]: n }))
        expect(add(cal, t, duration(1, { [level]: n + 1 })) > here).toBe(true)
        const back = add(cal, t, duration(-1, { [level]: n }))
        expect(add(cal, t, duration(-1, { [level]: n + 1 })) < back).toBe(true)
      }),
      params,
    )
  })

  test('reject agrees with constrain or refuses', () => {
    fc.assert(
      fc.property(withDuration, moments, ([name, moved], t) => {
        const cal = calendar(name)
        let rejected: bigint | string
        try {
          rejected = add(cal, t, moved, 'reject')
        } catch (error) {
          if (!(error instanceof DateError)) throw error
          rejected = error.code
        }
        expect([add(cal, t, moved), 'invalid_date']).toContain(rejected)
      }),
      params,
    )
  })

  test('zero amounts are the identity', () => {
    fc.assert(
      fc.property(names, moments, fc.nat(), (name, t, mask) => {
        const cal = calendar(name)
        const levels = cal.levels.filter((_, i) => i === 0 || (mask >> i) % 2 === 1)
        const zeros = Object.fromEntries(levels.map((level) => [level, 0]))
        expect(add(cal, t, duration(1, zeros), 'reject')).toBe(t)
      }),
      params,
    )
  })

  test('base durations are exact', () => {
    fc.assert(
      fc.property(fc.bigInt({ min: -(10n ** 30n), max: 10n ** 30n }), moments, (units, t) => {
        const moved = { kind: 'base', units: String(units) } as const
        expect(add(GREGORIAN, t, moved)).toBe(t + units)
        expect(durationUpperBound(GREGORIAN, moved)).toBe(units < 0n ? -units : units)
      }),
      params,
    )
  })
})

// --- examples ------------------------------------------------------------------------------------

describe('examples', () => {
  test('uniform levels', () => {
    expect(GREGORIAN.levels.map((level) => isUniform(GREGORIAN, level))).toEqual([
      true,
      true,
      true,
      true,
      false,
      false,
    ])
    expect(isUniform(calendar('intercalary-day'), 'day')).toBe(true)
    expect(isUniform(calendar('intercalary-day'), 'month')).toBe(false)
    // Julian and Gregorian days have the same length: still uniform across regimes.
    expect(isUniform(JULIAN_GREGORIAN, 'day')).toBe(true)
    expect(() => isUniform(GREGORIAN, 'week')).toThrow(
      expect.objectContaining({ level: 'week' }) as Error,
    )
  })

  test('uniform bounds are exact', () => {
    expect(durationUpperBound(GREGORIAN, duration(1, { day: 3, hour: 2 }))).toBe(
      3n * 86400n + 2n * 3600n,
    )
  })

  test('the month bound covers the longest month', () => {
    const bound = durationUpperBound(GREGORIAN, duration(1, { month: 1 }))
    expect(31n * 86400n <= bound && bound <= 62n * 86400n).toBe(true)
  })

  test('a year without regular months is bounded', () => {
    const cal = calendar('void-years')
    expect(durationUpperBound(cal, duration(1, { month: 1 })) > 0n).toBe(true)
    const deepwinter = fromFields(cal, { year: '1', month: 'deepwinter', day: '10' }, 'day')
    const moved = add(cal, deepwinter, duration(1, { year: 1 }))
    expect(defined(toFields(cal, moved).levels.get('month')).slotId).toBe('void')
  })

  test('a reform is reckoned in the starting regime', () => {
    const start = fromFields(JULIAN_GREGORIAN, { year: '1582', month: 'jan', day: '1' }, 'day')
    const moved = toFields(JULIAN_GREGORIAN, add(JULIAN_GREGORIAN, start, duration(1, { year: 1 })))
    expect(moved.regime).toBe('gregorian')
    const value = (level: string) => defined(moved.levels.get(level))
    expect([value('year').n, value('month').slotId, value('day').n]).toEqual([1583n, 'jan', 11n])
  })

  test('errors', () => {
    expect(() => add(GREGORIAN, 0n, duration(1, { week: 1 }))).toThrow(
      expect.objectContaining({ code: 'invalid_date', level: 'week' }) as Error,
    )
    expect(code(() => diff(GREGORIAN, 0n, 1n, 'day', 'year'))).toBe('invalid_date')
    expect(code(() => diff(GREGORIAN, 0n, 1n, 'year', 'week'))).toBe('invalid_date')
  })

  test('reject names the constrained level', () => {
    const jan31 = fromFields(GREGORIAN, { year: '2023', month: 'jan', day: '31' }, 'day')
    expect(() => add(GREGORIAN, jan31, duration(1, { month: 1 }), 'reject')).toThrow(
      expect.objectContaining({ level: 'day' }) as Error,
    )
  })

  test('the base remainder is constrained', () => {
    // A level-0 unit shorter than the base remainder (variable level 0) constrains it.
    const { definition, context } = load('intercalary-exceptions')
    const cal = compiled(
      patched(definition, {
        '/regimes/0/templates/short_day': { level: 'day', uniform: { count: '10' } },
        '/regimes/0/templates/m30': {
          level: 'month',
          sequence: [{ run: { count: '29' } }, { run: { count: '1', template: 'short_day' } }],
        },
      }),
      context,
    )
    expect(isUniform(cal, 'day')).toBe(false)
    const day29 = fromFields(cal, { year: '2', month: '2', day: '29' }, 'day')
    const oneDay = duration(1, { day: 1 })
    expect(add(cal, day29 + 20n, oneDay)).toBe(day29 + 24n + 9n)
    const reject: Overflow = 'reject'
    expect(() => add(cal, day29 + 20n, oneDay, reject)).toThrow(
      expect.objectContaining({ level: 'day' }) as Error,
    )
    expect(add(cal, day29 + 5n, oneDay, reject)).toBe(day29 + 24n + 5n)
  })

  test('nested intercalary units are bounded', () => {
    // intercalary-day with a 2-unit Midyear's Day: the day level is variable and its
    // intercalary day sits two levels below the year.
    const { definition, context } = load('intercalary-day')
    const cal = compiled(
      patched(definition, {
        '/regimes/0/templates/long_day': { level: 'day', uniform: { count: '2' } },
        '/regimes/0/templates/m30x/sequence/1/template': 'long_day',
      }),
      context,
    )
    expect(isUniform(cal, 'day')).toBe(false)
    const samples = fc.sample(
      fc.tuple(
        fc.bigInt({ min: 0n, max: 10n ** 4n }),
        fc.nat({ max: 199 }),
        fc.constantFrom(1 as const, -1 as const),
      ),
      { numRuns: 500, seed: 16 },
    )
    for (const [t, n, sign] of samples) {
      const moved = duration(sign, { day: n })
      const distance = add(cal, t, moved) - t
      expect((distance < 0n ? -distance : distance) <= durationUpperBound(cal, moved)).toBe(true)
    }
    // 30 Second + 1 day skips the intercalary Midyear's Day at the variable day level.
    const second30 = fromFields(cal, { year: '3', month: 'second', day: '30' }, 'day')
    expect(add(cal, second30, duration(1, { day: 1 }))).toBe(second30 + 3n)
  })
})

// --- performance (testing.md §4) -----------------------------------------------------------------

test('arithmetic jumps with ordinals', () => {
  const pairs = fc.sample(
    fc.tuple(fc.bigInt({ min: 0n, max: 10n ** 200n }), fc.bigInt({ min: 0n, max: 10n ** 200n })),
    { numRuns: 300, seed: 16 },
  )
  const started = performance.now()
  for (const [a, b] of pairs) {
    const found = diff(GREGORIAN, a < b ? a : b, a < b ? b : a, 'year', 'second')
    add(GREGORIAN, a, differenceDuration(found, 'cal'))
  }
  expect((performance.now() - started) / 1000).toBeLessThan(3)
})
