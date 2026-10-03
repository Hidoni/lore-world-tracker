// Parallel cycles (chronology-engine.md §3.7, §8), mirroring the Python engine's
// backend/tests/chronology/test_calendar_cycles.py. Vectors: cases/cycles/.
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import type { DateError } from '../src/calendar'
import {
  type CompiledCalendar,
  countedOrdinal,
  cycleFilter,
  cycleValue,
  fromCountedOrdinal,
  toFields,
  unitBounds,
} from '../src/calendar'
import { defined } from '../src/calendar/compiled'
import { at, compiled, load, patched } from './calendars'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 500 : 50
const params = { numRuns: RUNS, seed: 20261003 }
const DAY = 86_400n

const CALENDARS = new Map(
  ['gregorian-week', 'shire-week', 'cycles-showcase'].map((name) => {
    const { definition, context } = load(name)
    return [name, compiled(definition, context)]
  }),
)
const calendar = (name: string): CompiledCalendar => defined(CALENDARS.get(name))
const CONTINUOUS = [
  ['gregorian-week', 'week'],
  ['shire-week', 'week'],
  ['cycles-showcase', 'trecena'],
  ['cycles-showcase', 'veintena'],
] as const
const moments = fc.oneof(
  fc.bigInt({ min: 0n, max: 10n ** 12n }),
  fc.bigInt({ min: 0n, max: 10n ** 60n }),
)

// --- properties ----------------------------------------------------------------------------------

describe('properties', () => {
  test('consecutive counted units have consecutive indices', () => {
    fc.assert(
      fc.property(fc.constantFrom(...CONTINUOUS), moments, ([name, cycleId], t) => {
        const cal = calendar(name)
        const filter = cycleFilter(cycleId)
        const here = countedOrdinal(cal, t, 'day', filter)
        const unit = fromCountedOrdinal(cal, 'day', here.value, filter)
        const following = fromCountedOrdinal(cal, 'day', here.value + 1n, filter)
        const first = defined(cycleValue(cal, unit.start, cycleId))
        const second = defined(cycleValue(cal, following.start, cycleId))
        const length = defined(defined(cal.regimes[0]).cycles.find((c) => c.id === cycleId)).length
        expect(second.index).toBe((first.index + 1) % length)
        expect(cycleValue(cal, t, cycleId) === null).toBe(!here.counted)
      }),
      params,
    )
  })

  test('a reset cycle restarts with every month', () => {
    const cal = calendar('cycles-showcase')
    fc.assert(
      fc.property(moments, (t) => {
        const month = unitBounds(cal, t, 'month')
        const value = cycleValue(cal, t, 'decan')
        if (defined(toFields(cal, t).levels.get('month')).slotId === 'wayeb') {
          expect(value).toBeNull()
          return
        }
        // one-day units: days since the month start
        expect(defined(value).index).toBe(Number((t - month.start) % 10n))
        expect(defined(cycleValue(cal, month.start, 'decan')).index).toBe(0)
      }),
      params,
    )
  })

  test('Shire years start on Sterday', () => {
    const cal = calendar('shire-week')
    fc.assert(
      fc.property(fc.bigInt({ min: -3000n, max: 3000n }), (year) => {
        const start = defined(cal.regimes[0]).yearStart(year)
        expect(defined(cycleValue(cal, start, 'week')).name).toBe('Sterday')
      }),
      params,
    )
  })
})

// --- regimes -------------------------------------------------------------------------------------

const SWITCH = 10n ** 14n + 12n * 3600n

/**
 * gregorian-week plus a regime from noon on 1 January 2000 whose week continues regime 0's. The
 * new regime's 1 January 2000 starts at the switch, so it repeats half a day.
 */
function reform(start: unknown, resolved: string | null): CompiledCalendar {
  const { definition, context } = load('gregorian-week')
  const second = patched(at(definition, '/regimes/0'), {
    '/id': 'reformed',
    '/starts_at': start,
    '/alignment/at': { anchor: { kind: 'absolute', t: String(SWITCH) }, precision: 'base' },
    '/cycles': [
      {
        id: 'week',
        level: 'day',
        length: 7,
        names: at(definition, '/regimes/0/cycles/0/names'),
        number_start: 1,
        continue_from_previous_regime: true,
      },
    ],
  })
  const patches: Record<string, unknown> = {
    '/resolved/~1regimes~11~1alignment~1at': String(SWITCH),
  }
  if (resolved !== null) patches['/resolved/~1regimes~11~1starts_at'] = resolved
  return compiled(patched(definition, { '/regimes/-': second }), patched(context, patches))
}

describe('regimes', () => {
  test('the week continues across a regime start', () => {
    const point = { anchor: { kind: 'absolute', t: String(SWITCH) }, precision: 'base' }
    const cal = reform(point, String(SWITCH))
    // the repeated 1 January is a Sunday
    expect(defined(cycleValue(cal, SWITCH - 1n, 'week')).name).toBe('Saturday')
    expect(defined(cycleValue(cal, SWITCH, 'week')).name).toBe('Sunday')
    expect(defined(cycleValue(cal, SWITCH + 6n * DAY, 'week')).name).toBe('Saturday')
  })

  test('the week continues across a local regime start', () => {
    const noon = { year: '2000', month: 'jan', day: '1', hour: '12' }
    const cal = reform({ anchor: { kind: 'local', fields: noon }, precision: 'hour' }, null)
    expect(defined(cal.regimes[1]).startsAt).toBe(SWITCH)
    expect(defined(cycleValue(cal, SWITCH, 'week')).name).toBe('Sunday')
  })
})

test('unknown cycle', () => {
  expect(() => cycleValue(calendar('gregorian-week'), 0n, 'fortnight')).toThrow(
    expect.objectContaining({ code: 'unknown_cycle' }) as DateError,
  )
})
