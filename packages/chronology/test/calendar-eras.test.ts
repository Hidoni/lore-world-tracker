// Eras, regimes and local anchors (chronology-engine.md §3.3, §3.8, §3.10, §7), mirroring the
// Python engine's backend/tests/chronology/test_calendar_eras.py. Vectors: cases/eras/,
// cases/regimes/.
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import { activeRegime, type DateFields, eraOf, fromFields, toFields } from '../src/calendar'
import { defined } from '../src/calendar/compiled'
import { eraAt } from '../src/calendar/eras'
import { compiled, load, patched } from './calendars'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 500 : 50
const params = { numRuns: RUNS, seed: 20261003 }

function calendar(name: string) {
  const { definition, context } = load(name)
  return compiled(definition, context)
}

const REFORM_CALENDAR = calendar('julian-gregorian')
const JAPANESE = calendar('japanese-eras')
const REFORM = defined(defined(REFORM_CALENDAR.regimes[1]).startsAt)
const moments = fc.oneof(
  fc.bigInt({ min: REFORM - 10n ** 11n, max: REFORM + 10n ** 11n }),
  fc.bigInt({ min: REFORM - 10n ** 6n, max: REFORM + 10n ** 6n }),
  fc.bigInt({ min: 0n, max: 10n ** 20n }),
)

function asInput(date: DateFields): Record<string, string> {
  const fields: Record<string, string> = {}
  for (const [level, value] of date.levels) fields[level] = value.slotId ?? String(value.n)
  return fields
}

describe('properties', () => {
  test('toFields uses the regime active at t', () => {
    fc.assert(
      fc.property(moments, (t) => {
        const expected = t >= REFORM ? 'gregorian' : 'julian'
        expect(toFields(REFORM_CALENDAR, t).regime).toBe(expected)
        expect(activeRegime(REFORM_CALENDAR, t).id).toBe(expected)
      }),
      params,
    )
  })

  test('dates in force round trip without naming the regime', () => {
    // Regimes partition time: every moment's date resolves back to it, with or without the
    // regime, so boundaries leave no gap or overlap in absolute time.
    fc.assert(
      fc.property(moments, (t) => {
        const date = toFields(REFORM_CALENDAR, t)
        const fields = asInput(date)
        expect(fromFields(REFORM_CALENDAR, fields, 'second')).toBe(t)
        expect(fromFields(REFORM_CALENDAR, fields, 'second', { regime: date.regime })).toBe(t)
      }),
      params,
    )
  })

  test('era years invert', () => {
    fc.assert(
      fc.property(
        fc.bigInt({ min: -(10n ** 6n), max: 10n ** 6n }),
        fc.constantFrom(REFORM_CALENDAR, JAPANESE),
        (year, cal) => {
          for (const era of cal.eras) expect(era.year(era.eraYear(year))).toBe(year)
        },
      ),
      params,
    )
  })

  test('eraOf matches the era bounds', () => {
    fc.assert(
      fc.property(moments, (t) => {
        const era = defined(eraAt(REFORM_CALENDAR, t))
        expect(era.start === null || era.start <= t).toBe(true)
        expect(era.end === null || t < era.end).toBe(true)
        const value = defined(eraOf(REFORM_CALENDAR, t))
        const year = activeRegime(REFORM_CALENDAR, t).yearOf(t)
        expect(value.year).toBe(value.id === 'ad' ? year : 1n - year)
      }),
      params,
    )
  })
})

describe('examples', () => {
  test('the reform boundary is continuous', () => {
    const before = toFields(REFORM_CALENDAR, REFORM - 1n)
    const after = toFields(REFORM_CALENDAR, REFORM)
    expect([before.regime, defined(before.levels.get('day')).n]).toEqual(['julian', 4n])
    expect([after.regime, defined(after.levels.get('day')).n]).toEqual(['gregorian', 15n])
  })

  test('a calendar without eras', () => {
    const cal = calendar('gregorian-seconds')
    expect(eraAt(cal, 0n)).toBeNull()
    expect(eraOf(cal, 0n)).toBeNull()
  })

  test('overlay epochs are resolved', () => {
    const { definition, context } = load('julian-gregorian')
    const local = {
      anchor: { kind: 'local', fields: { year: '2000', month: 'jan', day: '6' } },
      precision: 'day',
    }
    const phases = [{ name: 'New', from: { num: '0', den: '1' } }]
    const period = { num: '2551443', den: '1' }
    const cal = compiled(
      patched(definition, {
        '/overlays': [
          { id: 'moon', name: 'Moon', period, epoch: local, phases },
          {
            id: 'other',
            name: 'Other',
            period,
            epoch: { anchor: { kind: 'absolute', t: '42' }, precision: 'base' },
            phases,
          },
        ],
      }),
      patched(context, { '/resolved/~1overlays~11~1epoch': '42' }),
    )
    const jan6 = fromFields(cal, { year: '2000', month: 'jan', day: '6' }, 'day')
    expect(cal.overlayEpochs).toEqual([jan6, 42n])
  })
})
