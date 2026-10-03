// Correspondence mapping (time-model.md §12), mirroring the Python engine's
// backend/tests/chronology/test_correspondence.py. Vectors: cases/correspondences/.
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import { defined } from '../src/calendar/compiled'
import {
  compileCorrespondence,
  compose,
  type Correspondence,
  CorrespondenceError,
  type Direction,
  type SyncMoments,
  validateCorrespondence,
} from '../src/correspondence'
import { type BigRational, rational, rationalDiv, rationalFromInt } from '../src/numbers'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 200 : 25
const params = { numRuns: RUNS, seed: 20261003 }

const D = 10n ** 40n
const DIRECTIONS: readonly Direction[] = ['ab', 'ba']

function cumulative(start: bigint, steps: readonly bigint[]): bigint[] {
  const values = [start]
  for (const step of steps.slice(1)) values.push(defined(values.at(-1)) + step)
  return values
}

const rates: fc.Arbitrary<BigRational | null> = fc.option(
  fc
    .tuple(fc.bigInt(1n, 10n ** 6n), fc.bigInt(1n, 10n ** 6n))
    .map(([num, den]) => rational(num, den)),
)

/** Random strictly increasing sync points (2-6), extrapolating by default or random rates. */
const correspondences: fc.Arbitrary<Correspondence> = fc
  .integer({ min: 2, max: 6 })
  .chain((count) =>
    fc.tuple(
      fc.array(fc.bigInt(1n, 10n ** 9n), { minLength: count, maxLength: count }),
      fc.array(fc.bigInt(1n, 10n ** 12n), { minLength: count, maxLength: count }),
      fc.bigInt(10n ** 12n, 10n ** 15n),
      fc.bigInt(10n ** 15n, 10n ** 18n),
      rates,
      rates,
    ),
  )
  .map(([aSteps, bSteps, a0, b0, rateBefore, rateAfter]) => {
    const as = cumulative(a0, aSteps)
    const bs = cumulative(b0, bSteps)
    const points = as.map((a, i): SyncMoments => [a, defined(bs[i])])
    return validateCorrespondence(points, { extrapolation: 'rate', rateBefore, rateAfter })
  })

/** Every slope the mapping uses (B units per A unit). */
function slopes(found: Correspondence): BigRational[] {
  const result = found.points.slice(1).map(([a1, b1], i) => {
    const [a0, b0] = defined(found.points[i])
    return rational(b1 - b0, a1 - a0)
  })
  return [...result, defined(found.rateBefore), defined(found.rateAfter)]
}

describe('properties', () => {
  test('mapping is monotonic', () => {
    fc.assert(
      fc.property(
        correspondences,
        fc.bigInt(0n, 10n ** 20n),
        fc.bigInt(0n, 10n ** 12n),
        (found, t, step) => {
          for (const direction of DIRECTIONS) {
            const low = found.map(t, direction, D)
            const high = found.map(t + step, direction, D)
            if (low !== null && high !== null) expect(low <= high).toBe(true)
          }
        },
      ),
      params,
    )
  })

  test('round trips stay close', () => {
    // A → B → A lands at or before `a`, by less than one B unit (`1/slope` A units) plus one A
    // unit: both directions floor.
    fc.assert(
      fc.property(correspondences, fc.bigInt(0n, 10n ** 20n), (found, a) => {
        const b = found.mapAB(a, D)
        if (b === null) return
        const back = found.mapBA(b, D)
        const worst = slopes(found)
          .map((s) => rationalDiv(rationalFromInt(1n), s))
          .reduce((x, y) => (x.num * y.den >= y.num * x.den ? x : y))
        const limit = (n: bigint) => (n - 1n) * worst.den < worst.num // n < 1 + worst
        if (back === null) {
          // below 0, outside A's bounds: only possible right after A's inception
          expect(limit(a)).toBe(true)
          return
        }
        expect(back <= a).toBe(true)
        expect(limit(a - back)).toBe(true)
        const again = found.mapAB(back, D) // mapping the round trip again lands on b or below
        expect(defined(again) <= b).toBe(true)
      }),
      params,
    )
  })
})

test('round trip example', () => {
  // Slope 5/2: 1 → 2 → 0, off by one A unit (less than one B unit plus one A unit).
  const found = validateCorrespondence([
    [0n, 0n],
    [2n, 5n],
  ])
  expect(found.mapAB(1n, D)).toBe(2n)
  expect(found.mapBA(2n, D)).toBe(0n)
})

test('compile from a document', () => {
  const absolute = { anchor: { kind: 'absolute', t: '0' }, precision: 'base' } as const
  const found = compileCorrespondence(
    {
      extrapolation: 'rate',
      rate_after: { num: '365', den: '1' },
      rate_before: { num: '365', den: '1' },
      points: [{ a: absolute, b: absolute }],
    },
    { '/points/0/a': 1000n, '/points/0/b': 7n },
  )
  expect(found.mapAB(1001n, D)).toBe(372n)
  expect(found.mapBA(372n, D)).toBe(1001n)
  expect(() => compileCorrespondence({ points: [{ a: absolute, b: absolute }] }, {})).toThrow(
    '/points/0/a',
  )
})

function errorsOf(...args: Parameters<typeof validateCorrespondence>) {
  try {
    validateCorrespondence(...args)
  } catch (error) {
    if (!(error instanceof CorrespondenceError)) throw error
    return { code: error.code, errors: error.errors.map(({ code, path }) => [code, path]) }
  }
  throw new Error('expected a CorrespondenceError')
}

test('validation reports every error', () => {
  const points: SyncMoments[] = [
    [10n, 5n],
    [20n, 5n],
    [30n, 1n],
  ]
  expect(errorsOf(points, { rateBefore: rationalFromInt(-1n) })).toEqual({
    code: 'correspondence.non_monotonic',
    errors: [
      ['correspondence.non_monotonic', '/points/1'],
      ['correspondence.non_monotonic', '/points/2'],
      ['correspondence.bad_rate', '/rate_before'],
    ],
  })
  expect(errorsOf([[10n, 5n]], { extrapolation: 'rate' }).errors).toEqual([
    ['correspondence.missing_rate', '/rate_before'],
    ['correspondence.missing_rate', '/rate_after'],
  ])
})

test('points are sorted by a', () => {
  const found = validateCorrespondence([
    [20n, 200n],
    [10n, 100n],
  ])
  expect(found.points).toEqual([
    [10n, 100n],
    [20n, 200n],
  ])
  expect(found.mapAB(15n, D)).toBe(150n)
  expect(
    errorsOf([
      [20n, 100n],
      [10n, 200n],
    ]).errors,
  ).toEqual([['correspondence.non_monotonic', '/points/0']])
})

test('compose through dimensions', () => {
  const secondsDays = validateCorrespondence(
    [
      [0n, 0n],
      [8_640_000n, 100n],
    ],
    { extrapolation: 'rate' },
  )
  const daysYears = validateCorrespondence(
    [
      [0n, 0n],
      [36_500n, 100n],
    ],
    { extrapolation: 'rate' },
  )
  const step = (correspondence: Correspondence, direction: Direction, targetDuration = D) => ({
    correspondence,
    direction,
    targetDuration,
  })
  expect(compose([step(secondsDays, 'ab'), step(daysYears, 'ab')], 365n * 86_400n * 3n)).toBe(3n)
  expect(compose([step(daysYears, 'ba'), step(secondsDays, 'ba')], 3n)).toBe(3n * 365n * 86_400n)
  expect(compose([step(secondsDays, 'ab', 10n)], 8_640_000n)).toBeNull() // 100 days > D = 10
  expect(compose([], 5n)).toBe(5n)
})
