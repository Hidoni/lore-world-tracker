// Moment ⇄ fields conversions (chronology-engine.md §5.5–§5.7, §6), mirroring the Python engine's
// backend/tests/chronology/test_calendar_convert.py. Vectors: cases/conversions/.
// Property tests are seeded; PROPERTY_PROFILE=ci runs more examples (like hypothesis' `ci`).
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import {
  activeRegime,
  type CompiledCalendar,
  DateError,
  type DateFields,
  dateFieldsToJson,
  type FieldsInput,
  type FromFieldsOptions,
  fromFields,
  normalizeFields,
  toFields,
} from '../src/calendar'
import { defined } from '../src/calendar/compiled'
import { at, compiled, load, patched } from './calendars'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 500 : 50
const params = { numRuns: RUNS, seed: 20261002 }
const DAY = 86_400n

const NAMES = ['gregorian-seconds', 'alternating-years', 'intercalary-exceptions'] as const
const CALENDARS = new Map(
  NAMES.map((name) => {
    const { definition, context } = load(name)
    return [name, compiled(definition, context)]
  }),
)
const calendar = (name: (typeof NAMES)[number]): CompiledCalendar => defined(CALENDARS.get(name))
const GREGORIAN = calendar('gregorian-seconds')

const names = fc.constantFrom(...NAMES)
const moments = fc.oneof(
  fc.bigInt({ min: 0n, max: 10n ** 15n }),
  fc.bigInt({ min: 435n * 10n ** 15n - 10n ** 12n, max: 435n * 10n ** 15n + 10n ** 12n }),
  fc.bigInt({ min: 0n, max: 10n ** 110n }),
)

/** Fields as a user would store them: slot ids for named units, numbers otherwise. */
function asInput(date: DateFields): Record<string, string> {
  const fields: Record<string, string> = {}
  for (const [level, value] of date.levels) fields[level] = value.slotId ?? String(value.n)
  return fields
}

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
  test('round trip to the level-0 unit', () => {
    fc.assert(
      fc.property(names, moments, (name, t) => {
        const cal = calendar(name)
        const date = toFields(cal, t)
        expect(fromFields(cal, asInput(date), defined(cal.levels[0]))).toBe(t - date.base)
        expect(date.base >= 0n).toBe(true)
        const level0 = defined(cal.regimes[0]).template(defined(cal.levels[0]))
        expect(date.base < level0.length).toBe(true)
      }),
      params,
    )
  })

  test('year starts strictly increase', () => {
    const years = fc.oneof(
      fc.bigInt({ min: -3000n, max: 3000n }),
      fc.bigInt({ min: -(10n ** 300n), max: 10n ** 300n }),
    )
    fc.assert(
      fc.property(names, years, (name, year) => {
        const regime = defined(calendar(name).regimes[0])
        expect(regime.yearStart(year + 1n) > regime.yearStart(year)).toBe(true)
      }),
      params,
    )
  })

  test('fields round trip at every precision, by number or slot id', () => {
    fc.assert(
      fc.property(names, moments, fc.nat(), fc.boolean(), (name, t, pick, byNumber) => {
        const cal = calendar(name)
        const levels = cal.levels
        const date = toFields(cal, t)
        const index = pick % levels.length
        const precision = defined(levels[index])
        const kept = levels.slice(index)
        const fields: Record<string, string> = {}
        const stored: Record<string, string> = {}
        for (const [level, value] of date.levels) {
          if (!kept.includes(level)) continue
          const number = value.n === null ? null : String(value.n)
          fields[level] = byNumber && number !== null ? number : (value.slotId ?? String(number))
          stored[level] = value.slotId ?? String(number)
        }
        const start = fromFields(cal, fields, precision)
        const back = toFields(cal, start)
        for (const level of kept) {
          const value = defined(back.levels.get(level))
          expect([String(value.n), value.slotId]).toContain(fields[level])
        }
        expect(back.base).toBe(0n)
        for (let finer = 0; finer < index; finer++) {
          // finer levels: the first unit
          const n = defined(back.levels.get(defined(levels[finer]))).n
          expect([cal.numberingStarts[finer], null]).toContain(n)
        }
        expect(normalizeFields(cal, fields)).toEqual(stored)
      }),
      params,
    )
  })
})

// --- examples ------------------------------------------------------------------------------------

describe('examples', () => {
  test('the §5.6 JSON shape', () => {
    const date = toFields(calendar('intercalary-exceptions'), 1_000_000n + 30n * 24n + 5n)
    expect(dateFieldsToJson(date)).toStrictEqual({
      regime: 'shire',
      levels: {
        year: { n: '1' },
        month: { n: null, id: 'yule', name: 'Yule', intercalary: true },
        day: { n: '1' },
      },
      base: '5',
      era: null,
      cycles: {},
      overlays: {},
    })
    expect(Object.keys(dateFieldsToJson(toFields(GREGORIAN, 0n)).levels as object)).toEqual([
      'year',
      'month',
      'day',
      'hour',
      'minute',
      'second',
    ])
  })

  test('errors name the offending level', () => {
    const cases: [FieldsInput, string, string][] = [
      [{ year: '2023', month: 'feb', day: '29' }, 'day', 'day'],
      [{ year: '2023', month: 'frostfall' }, 'month', 'month'],
      [{ year: '2023', day: '1' }, 'day', 'month'],
      [{ year: '2023', month: 'jan' }, 'year', 'month'],
      [{ year: 'x' }, 'year', 'year'],
      [{ year: '1', week: '1' }, 'year', 'week'],
      [{ year: '1' }, 'week', 'week'],
    ]
    for (const [fields, precision, level] of cases) {
      expect(dateError(() => fromFields(GREGORIAN, fields, precision))).toEqual([
        'invalid_date',
        level,
      ])
    }
  })

  test('constrained overflow', () => {
    const shire = calendar('intercalary-exceptions')
    const constrain: FromFieldsOptions = { overflow: 'constrain' }
    const feb = { year: '2023', month: 'feb' }
    expect(fromFields(GREGORIAN, { ...feb, day: '31' }, 'day', constrain)).toBe(
      fromFields(GREGORIAN, { ...feb, day: '28' }, 'day'),
    )
    expect(fromFields(GREGORIAN, { ...feb, day: '-4' }, 'day', constrain)).toBe(
      fromFields(GREGORIAN, { ...feb, day: '1' }, 'day'),
    )
    // An unknown slot id with no default template on the parent level stays invalid.
    expect(
      dateError(() => fromFields(GREGORIAN, { year: '2023', month: 'nope' }, 'month', constrain)),
    ).toEqual(['invalid_date', 'month'])
    expect(
      dateError(() => fromFields(shire, { year: '1', month: 'nope' }, 'month', constrain)),
    ).toEqual(['invalid_date', 'month'])
  })

  test('normalizeFields', () => {
    const shire = calendar('intercalary-exceptions')
    expect(normalizeFields(shire, { year: '4', month: '12', day: '05' })).toEqual({
      year: '4',
      month: 'lastmonth',
      day: '5',
    })
    expect(normalizeFields(shire, { year: '4', month: '2' })).toEqual({ year: '4', month: '2' })
    // an intercalary unit (no regular number) by its slot id
    expect(normalizeFields(shire, { year: '1', month: 'yule', day: '01' })).toEqual({
      year: '1',
      month: 'yule',
      day: '1',
    })
    expect(normalizeFields(GREGORIAN, { year: '2024', month: '3' })).toEqual({
      year: '2024',
      month: 'mar',
    })
    for (const invalid of [{}, { year: '2023', month: '2', day: '29' }]) {
      expect(() => normalizeFields(GREGORIAN, invalid)).toThrow(DateError)
    }
  })
})

// --- regimes (single-regime engine; full reform semantics arrive with #24) -----------------------

const SWITCH = 10n ** 14n // 2000-01-01 in regime 0

/** Gregorian, plus a regime from 2000-01-01 (regime 0) whose 2000-01-01 is shifted. */
function reformed(startShiftDays: bigint): CompiledCalendar {
  const { definition, context } = load('gregorian-seconds')
  const aligned = String(SWITCH + startShiftDays * DAY)
  const second = patched(at(definition, '/regimes/0'), {
    '/id': 'reformed',
    '/name': 'Reformed',
    '/starts_at': { anchor: { kind: 'absolute', t: String(SWITCH) }, precision: 'base' },
    '/alignment/at': { anchor: { kind: 'absolute', t: aligned }, precision: 'base' },
  })
  return compiled(
    patched(definition, { '/regimes/-': second }),
    patched(context, {
      '/resolved/~1regimes~11~1starts_at': String(SWITCH),
      '/resolved/~1regimes~11~1alignment~1at': aligned,
    }),
  )
}

describe('regimes', () => {
  test('reform gap and regime choice', () => {
    const cal = reformed(-10n) // 2000-01-11 (reformed) is the switch: 1–10 January are skipped
    expect(defined(toFields(cal, SWITCH).levels.get('day')).n).toBe(11n)
    expect(toFields(cal, SWITCH).regime).toBe('reformed')
    expect(toFields(cal, SWITCH - 1n).regime).toBe('gregorian')
    expect(activeRegime(cal, SWITCH).id).toBe('reformed')
    const jan = { year: '2000', month: 'jan' }
    expect(fromFields(cal, { ...jan, day: '15' }, 'day')).toBe(SWITCH + 4n * DAY)
    expect(fromFields(cal, { year: '1999', month: 'dec', day: '31' }, 'day')).toBe(SWITCH - DAY)
    expect(dateError(() => fromFields(cal, { ...jan, day: '5' }, 'day'))).toEqual([
      'reform_gap',
      null,
    ])
    expect(fromFields(cal, { ...jan, day: '5' }, 'day', { regime: 'gregorian' })).toBe(
      SWITCH + 4n * DAY,
    )
    expect(
      dateError(() => fromFields(cal, { ...jan, day: '5' }, 'day', { regime: 'julian' })),
    ).toEqual(['invalid_date', null])
    // invalid in every regime: regime 0's error
    expect(
      dateError(() => fromFields(cal, { year: '2001', month: 'feb', day: '30' }, 'day')),
    ).toEqual(['invalid_date', 'day'])
    expect(normalizeFields(cal, { ...jan, day: '15' })).toEqual({ ...jan, day: '15' })
    expect(normalizeFields(cal, { ...jan, day: '5' }, { regime: 'gregorian' })).toEqual({
      ...jan,
      day: '5',
    })
  })

  test('a reform overlap is ambiguous', () => {
    const cal = reformed(10n) // the reformed 2000-01-01 is 10 days after the switch: dates repeat
    const fields = { year: '1999', month: 'dec', day: '25' }
    expect(dateError(() => fromFields(cal, fields, 'day'))).toEqual(['reform_ambiguous', null])
  })

  test('regimes with a local start wait for local resolution', () => {
    const { definition, context } = load('gregorian-seconds')
    const second = patched(at(definition, '/regimes/0'), {
      '/id': 'later',
      '/starts_at': { anchor: { kind: 'local', fields: { year: '2100' } }, precision: 'year' },
    })
    const cal = compiled(
      patched(definition, { '/regimes/-': second }),
      patched(context, { '/resolved/~1regimes~11~1alignment~1at': '0' }),
    )
    expect(toFields(cal, 10n ** 16n).regime).toBe('gregorian')
    expect(fromFields(cal, { year: '2200' }, 'year')).toBe(defined(cal.regimes[0]).yearStart(2200n))
  })
})

// --- performance (testing.md §4) -----------------------------------------------------------------

test('gregorian throughput', () => {
  const random = fc.sample(fc.bigInt({ min: 0n, max: 2n * 10n ** 14n }), {
    numRuns: 20_000,
    seed: 1,
  })
  let started = performance.now()
  const dates = random.map((t) => toFields(GREGORIAN, t))
  const toRate = random.length / ((performance.now() - started) / 1000)
  const inputs = dates.map(asInput)
  started = performance.now()
  for (const fields of inputs) fromFields(GREGORIAN, fields, 'second')
  const fromRate = inputs.length / ((performance.now() - started) / 1000)
  expect(toRate).toBeGreaterThanOrEqual(50_000)
  expect(fromRate).toBeGreaterThanOrEqual(50_000)
})
