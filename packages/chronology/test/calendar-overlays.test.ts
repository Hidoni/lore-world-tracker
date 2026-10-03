// Overlays: exact phases and nextPhaseAt (chronology-engine.md §3.9, §8), mirroring the Python
// engine's backend/tests/chronology/test_calendar_overlays.py. Vectors: cases/overlays/.
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import {
  dateFieldsToJson,
  DateError,
  nextPhaseAt,
  overlayPhase,
  overlayValueToJson,
  toFields,
} from '../src/calendar'
import {
  type BigRational,
  rational,
  rationalCompare,
  rationalFloor,
  rationalFrac,
  rationalFromInt,
  rationalMul,
  rationalSub,
} from '../src/numbers'
import { defined } from '../src/calendar/compiled'
import { compiled, load } from './calendars'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 500 : 50
const params = { numRuns: RUNS, seed: 20261003 }

function calendar(name: string) {
  const { definition, context } = load(name)
  return compiled(definition, context)
}

const MOON = calendar('gregorian-moon')
const PERIODS: Record<string, BigRational> = {
  moon: rational(25514428n, 10n),
  seasons: rational(31556925216n, 1000n),
}
const overlays = fc.constantFrom('moon', 'seasons')
const phases = fc.oneof(
  fc.constantFrom(rational(0n), rational(7n, 16n), rational(1n, 4n), rational(15n, 16n)),
  fc
    .tuple(fc.bigInt({ min: 1n, max: 10n ** 9n }), fc.bigInt({ min: 0n, max: 10n ** 9n }))
    .map(([den, num]) => rational(num % den, den)),
)
const moments = fc.oneof(
  fc.bigInt({ min: 0n, max: 10n ** 16n }),
  fc.bigInt({ min: 0n, max: 10n ** 120n }),
)

const ceil = (a: BigRational): bigint => -rationalFloor({ num: -a.num, den: a.den })

describe('properties', () => {
  test('nextPhaseAt reaches the phase', () => {
    // At the result the phase is exactly `phase`, or the result is the first moment after the
    // exact instant (the ceil rule); no earlier instant at or after `t` qualifies.
    fc.assert(
      fc.property(overlays, moments, phases, (overlay, t, phase) => {
        const found = nextPhaseAt(MOON, t, overlay, phase)
        expect(found >= t).toBe(true)
        const period = defined(PERIODS[overlay])
        const reached = overlayPhase(MOON, found, overlay).phase
        const late = rationalFrac(rationalSub(reached, phase)) // turns past the exact instant
        expect(rationalCompare(rationalMul(late, period), rationalFromInt(1n))).toBe(-1)
        if (late.num === 0n) expect(reached).toEqual(phase)
        const instant = rationalSub(rationalFromInt(found), rationalMul(late, period))
        expect(ceil(rationalSub(instant, period)) < t).toBe(true) // the previous instant was before t
        expect(nextPhaseAt(MOON, found, overlay, phase)).toBe(found)
      }),
      params,
    )
  })

  test('phases are in range and named', () => {
    fc.assert(
      fc.property(overlays, moments, (overlay, t) => {
        const value = overlayPhase(MOON, t, overlay)
        expect(value.phase.num >= 0n && value.phase.num < value.phase.den).toBe(true)
        expect(value.name).not.toBe('')
        const json = dateFieldsToJson(toFields(MOON, t)).overlays as Record<string, unknown>
        expect(json[overlay]).toEqual(overlayValueToJson(value))
      }),
      params,
    )
  })
})

describe('examples', () => {
  test('phase names follow the last start', () => {
    const epoch = 100000000497640n
    expect(overlayPhase(MOON, epoch, 'moon').name).toBe('New Moon')
    expect(overlayPhase(MOON, epoch - 1n, 'moon').name).toBe('New Moon') // from 15/16
    expect(overlayPhase(MOON, epoch + 3n * 86400n, 'moon').name).toBe('Waxing Crescent')
  })

  test('errors', () => {
    const code = (call: () => unknown): string | null => {
      try {
        call()
      } catch (error) {
        if (error instanceof DateError) return error.code
        throw error
      }
      return null
    }
    expect(code(() => overlayPhase(MOON, 0n, 'sun'))).toBe('unknown_overlay')
    expect(code(() => nextPhaseAt(MOON, 0n, 'moon', rational(1n)))).toBe('invalid_date')
    expect(code(() => nextPhaseAt(MOON, 0n, 'moon', rational(-1n, 2n)))).toBe('invalid_date')
  })

  test('calendars without overlays', () => {
    const plain = calendar('gregorian-seconds')
    expect(dateFieldsToJson(toFields(plain, 0n)).overlays).toEqual({})
    expect(() => overlayPhase(plain, 0n, 'moon')).toThrow(DateError)
  })
})
