// Unit bounds, ordinals, fromOrdinal and options (chronology-engine.md §5.8, §6), mirroring the
// Python engine's backend/tests/chronology/test_calendar_units.py. Vectors: cases/navigation/.
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import {
  type CompiledCalendar,
  countedOrdinal,
  DateError,
  fromCountedOrdinal,
  fromOrdinal,
  options,
  ordinal,
  REGULAR,
  toFields,
  type UnitFilter,
  unitBounds,
} from '../src/calendar'
import { defined } from '../src/calendar/compiled'
import { unitsPerPeriod } from '../src/calendar/units'
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

const NAMES = ['gregorian-seconds', 'alternating-years', 'intercalary-exceptions'] as const
const CALENDARS = new Map<string, CompiledCalendar>(
  NAMES.map((name) => {
    const { definition, context } = load(name)
    return [name, compiled(definition, context)]
  }),
)
CALENDARS.set('void-years', withVoidYears())
const calendar = (name: string): CompiledCalendar => defined(CALENDARS.get(name))
const SHIRE = calendar('intercalary-exceptions')

/** Counts every unit (intercalary ones too) except Yule and everything inside it. */
const NO_YULE: UnitFilter = {
  key: 'no-yule',
  counts: () => true,
  excludes: (segment) => segment.slotId === 'yule',
}

const names = fc.constantFrom(...CALENDARS.keys())
const moments = fc.oneof(
  fc.bigInt({ min: 0n, max: 2n * 10n ** 6n }),
  fc.bigInt({ min: 0n, max: 10n ** 15n }),
  fc.bigInt({ min: 435n * 10n ** 15n - 10n ** 12n, max: 435n * 10n ** 15n + 10n ** 12n }),
  fc.bigInt({ min: 0n, max: 10n ** 120n }),
)

function dateError(call: () => unknown): [string, string | null] {
  try {
    call()
  } catch (error) {
    if (error instanceof DateError) return [error.code, error.level]
    throw error
  }
  throw new Error('expected a DateError')
}

// --- properties ----------------------------------------------------------------------------------

describe('properties', () => {
  test('fromOrdinal inverts ordinal', () => {
    fc.assert(
      fc.property(names, moments, fc.nat(), (name, t, pick) => {
        const cal = calendar(name)
        const level = defined(cal.levels[pick % cal.levels.length])
        const found = ordinal(cal, t, level)
        const bounds = fromOrdinal(cal, level, found.value)
        expect(bounds.start <= t).toBe(true)
        const containing = unitBounds(cal, t, level)
        expect(containing.start <= t && t < containing.end).toBe(true)
        if (found.counted) {
          expect(bounds).toEqual(containing)
          expect(ordinal(cal, bounds.start, level)).toEqual(found)
        } else {
          // t is in an intercalary unit: the preceding regular unit ends before it
          expect(bounds.end <= containing.start).toBe(true)
        }
      }),
      params,
    )
  })

  test('ordinal inverts fromOrdinal', () => {
    const ordinals = fc.oneof(
      fc.bigInt({ min: -5000n, max: 5000n }),
      fc.bigInt({ min: -(10n ** 200n), max: 10n ** 200n }),
    )
    fc.assert(
      fc.property(names, ordinals, fc.nat(), (name, m, pick) => {
        const cal = calendar(name)
        const level = defined(cal.levels[pick % cal.levels.length])
        const bounds = fromOrdinal(cal, level, m)
        expect(ordinal(cal, bounds.start, level).value).toBe(m)
        expect(ordinal(cal, bounds.end - 1n, level).value).toBe(m)
        expect(fromOrdinal(cal, level, m + 1n).start >= bounds.end).toBe(true)
      }),
      params,
    )
  })

  test('counted ordinals with an excluding filter', () => {
    const shires = fc.constantFrom('intercalary-exceptions', 'void-years')
    fc.assert(
      fc.property(shires, moments, fc.constantFrom('day', 'month'), (name, t, level) => {
        const cal = calendar(name)
        const found = countedOrdinal(cal, t, level, NO_YULE)
        const bounds = fromCountedOrdinal(cal, level, found.value, NO_YULE)
        expect(bounds.start <= t).toBe(true)
        const inYule = defined(toFields(cal, t).levels.get('month')).slotId === 'yule'
        expect(found.counted).toBe(!inYule)
        if (found.counted) expect(bounds).toEqual(unitBounds(cal, t, level))
        expect(countedOrdinal(cal, bounds.start, level, NO_YULE).value).toBe(found.value)
      }),
      params,
    )
  })
})

// --- examples ------------------------------------------------------------------------------------

describe('examples', () => {
  test('excluding filter counts', () => {
    const year1 = 1_000_000n
    const yule = year1 + 30n * 24n
    expect(countedOrdinal(SHIRE, yule, 'day', NO_YULE).counted).toBe(false)
    // Year 0 has 363 days, one of them Yule: 362 counted days before year 1.
    expect(countedOrdinal(SHIRE, year1, 'day', NO_YULE).value).toBe(362n)
    expect(countedOrdinal(SHIRE, yule + 24n, 'day', NO_YULE).value).toBe(362n + 30n)
    // Months: NO_YULE counts Lithe (intercalary) but not Yule: 13 months per common year.
    expect(countedOrdinal(SHIRE, year1, 'month', NO_YULE).value).toBe(13n)
    expect(fromCountedOrdinal(SHIRE, 'month', 13n, NO_YULE).start).toBe(year1)
  })

  test('void exception years', () => {
    const cal = calendar('void-years')
    const regime = defined(cal.regimes[0])
    const year2 = regime.yearStart(2n)
    const found = ordinal(cal, year2, 'month')
    expect(found.counted).toBe(false) // the Void month is intercalary
    expect(fromOrdinal(cal, 'month', found.value).end).toBe(year2)
    expect(fromOrdinal(cal, 'month', found.value + 1n).start).toBe(regime.yearStart(3n))
  })

  test('no counted units at all', () => {
    const { definition, context } = load('intercalary-exceptions')
    const cal = compiled(
      patched(definition, {
        '/regimes/0/templates/year_void': {
          level: 'year',
          sequence: [{ id: 'void', template: 'm30', name: 'Void', intercalary: true }],
        },
        '/regimes/0/top': { pattern: { kind: 'fixed', template: 'year_void' } },
        '/regimes/0/alignment/fields': { year: '1' },
      }),
      context,
    )
    expect(ordinal(cal, 0n, 'month').counted).toBe(false)
    expect(dateError(() => fromOrdinal(cal, 'month', 0n))).toEqual(['invalid_date', 'month'])
    const epoch = defined(cal.regimes[0]).epoch
    expect(fromOrdinal(cal, 'day', 0n)).toEqual({ start: epoch, end: epoch + 24n })
  })

  test('units per period', () => {
    const regime = defined(SHIRE.regimes[0])
    const top = SHIRE.levels.length - 1
    expect(unitsPerPeriod(regime, top, top)).toBe(regime.period)
    const months = unitsPerPeriod(regime, SHIRE.levelIndex('month'), top)
    expect(months).toBe(unitsPerPeriod(regime, SHIRE.levelIndex('month'), top, REGULAR))
    expect(unitsPerPeriod(regime, SHIRE.levelIndex('month'), top, NO_YULE)).toBeGreaterThan(months)
  })

  test('options', () => {
    expect(options(SHIRE, {}, 'year')).toEqual([{ kind: 'range', first: null, last: null }])
    const found = options(SHIRE, { year: '1' }, 'month')
    expect(found[1]).toEqual({
      kind: 'slot',
      slotId: 'yule',
      n: null,
      name: 'Yule',
      intercalary: true,
    })
    expect(found[2]).toEqual({ kind: 'range', first: 2n, last: 11n })
    expect(options(SHIRE, { year: '1' }, 'month', { regime: 'shire' })).toEqual(found)
    expect(() => options(SHIRE, { year: '1' }, 'week')).toThrow(DateError)
    expect(() => options(SHIRE, { year: '1' }, 'year')).toThrow(DateError)
    expect(() => options(SHIRE, { year: '1' }, 'month', { regime: 'nope' })).toThrow(DateError)
  })

  test('unknown levels', () => {
    for (const call of [
      () => ordinal(SHIRE, 0n, 'week'),
      () => unitBounds(SHIRE, 0n, 'week'),
      () => fromOrdinal(SHIRE, 'week', 0n),
      () => countedOrdinal(SHIRE, 0n, 'week', REGULAR),
    ]) {
      expect(call).toThrow(DateError)
    }
  })
})

// --- regimes -------------------------------------------------------------------------------------

function reformed(): CompiledCalendar {
  const { definition, context } = load('gregorian-seconds')
  const switchAt = String(10n ** 14n + 12n * 3600n) // noon, 1 January 2000
  const point = { anchor: { kind: 'absolute', t: switchAt }, precision: 'base' }
  const second = patched(at(definition, '/regimes/0'), {
    '/id': 'reformed',
    '/starts_at': point,
    '/alignment/at': point,
  })
  return compiled(
    patched(definition, { '/regimes/-': second }),
    patched(context, {
      '/resolved/~1regimes~11~1starts_at': switchAt,
      '/resolved/~1regimes~11~1alignment~1at': switchAt,
    }),
  )
}

test('bounds are clipped at regime boundaries', () => {
  const cal = reformed()
  const switchAt = 10n ** 14n + 12n * 3600n
  // regime 0's 1 January ends at the switch; the reformed 1 January starts at noon
  expect(unitBounds(cal, switchAt - 1n, 'day')).toEqual({ start: 10n ** 14n, end: switchAt })
  expect(unitBounds(cal, switchAt, 'day')).toEqual({ start: switchAt, end: switchAt + 86_400n })
  expect(ordinal(cal, switchAt, 'year').value).toBe(2000n)
  // each regime counts in its own structure (§7)
  const shift =
    fromOrdinal(cal, 'day', 0n, { regime: 'reformed' }).start - fromOrdinal(cal, 'day', 0n).start
  expect(shift).toBe(12n * 3600n)
  expect(() => fromOrdinal(cal, 'day', 0n, { regime: 'julian' })).toThrow(DateError)
})

// --- performance (testing.md §4) -----------------------------------------------------------------

test('navigation is logarithmic in the period', () => {
  const { definition, context } = load('gregorian-seconds')
  const cal = compiled(
    patched(definition, {
      '/regimes/0/top/pattern': {
        kind: 'rules',
        default: 'year_common',
        rules: [
          { when: { mod: '64', eq: '0' }, template: 'year_leap' },
          { when: { mod: '15625', eq: '3' }, template: 'year_leap' },
        ],
      },
    }),
    context,
  )
  expect(defined(cal.regimes[0]).period).toBe(1_000_000n)
  let started = performance.now()
  ordinal(cal, 0n, 'day') // builds the per-period day counts once
  const setup = (performance.now() - started) / 1000
  const random = fc.sample(fc.bigInt({ min: 0n, max: 10n ** 30n }), { numRuns: 10_000, seed: 7 })
  started = performance.now()
  for (const t of random) fromOrdinal(cal, 'day', ordinal(cal, t, 'day').value)
  const rate = random.length / ((performance.now() - started) / 1000)
  expect(setup).toBeLessThan(2)
  expect(rate).toBeGreaterThanOrEqual(10_000)
})
