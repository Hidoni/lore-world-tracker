// Unit and property tests of src/numbers.ts (vectors: spec/chronology/conformance/cases/numbers/).
// Property tests are seeded; PROPERTY_PROFILE=ci runs more examples (like hypothesis' `ci`).
import fc from 'fast-check'
import { describe, expect, test } from 'vitest'

import {
  type BigRational,
  floorDiv,
  floorMod,
  formatInteger,
  formatMoment,
  formatRational,
  formatSigned,
  fromSortableKey,
  MAX_DIGITS,
  NumberError,
  parseMoment,
  parseRational,
  parseSigned,
  rational,
  rationalAdd,
  rationalCompare,
  rationalDiv,
  rationalFloor,
  rationalFrac,
  rationalFromInt,
  rationalMul,
  rationalSub,
  sortableKey,
  TIMES_TEN,
} from '../src/numbers'

const RUNS = process.env.PROPERTY_PROFILE === 'ci' ? 500 : 50
const params = { numRuns: RUNS, seed: 20261001 }
function check<Ts extends [unknown, ...unknown[]]>(prop: fc.IPropertyWithHooks<Ts>): void {
  fc.assert(prop, params)
}

const MAX = 10n ** BigInt(MAX_DIGITS) - 1n
const moments = fc.oneof(fc.bigInt({ min: 0n, max: 10n ** 6n }), fc.bigInt({ min: 0n, max: MAX }))
const signed = fc.oneof(
  fc.bigInt({ min: -(10n ** 6n), max: 10n ** 6n }),
  fc.bigInt({ min: -MAX, max: MAX }),
)
const nonzero = signed.filter((n) => n !== 0n)
const BOUND = 10n ** 30n
const rationals = fc
  .tuple(fc.bigInt({ min: -BOUND, max: BOUND }), fc.bigInt({ min: 1n, max: BOUND }))
  .map(([num, den]) => rational(num, den))

function codeOf(call: () => unknown): string | undefined {
  try {
    call()
  } catch (error) {
    if (error instanceof NumberError) return error.code
    throw error
  }
  return undefined
}

function gcd(a: bigint, b: bigint): bigint {
  let [x, y] = [a < 0n ? -a : a, b < 0n ? -b : b]
  while (y !== 0n) [x, y] = [y, x % y]
  return x
}

const eq = (a: BigRational, b: BigRational) => rationalCompare(a, b) === 0

describe('integer strings', () => {
  test('moments round-trip', () => {
    check(fc.property(moments, (n) => parseMoment(formatMoment(n)) === n))
  })

  test('signed integers round-trip', () => {
    check(fc.property(signed, (n) => parseSigned(formatSigned(n)) === n))
  })

  test.each(['', '01', '-1', '+1', ' 1', '1 ', '١', '1'.repeat(1001)])(
    'parseMoment rejects %j',
    (text) => {
      expect(codeOf(() => parseMoment(text))).toBe('invalid_number')
    },
  )

  test.each(['-0', '-01', '--1', '-', `-${'1'.repeat(1001)}`, '1'.repeat(1001)])(
    'parseSigned rejects %j',
    (text) => {
      expect(codeOf(() => parseSigned(text))).toBe('invalid_number')
    },
  )

  test('formatting rejects out-of-range values', () => {
    expect(codeOf(() => formatMoment(-1n))).toBe('invalid_number')
    expect(codeOf(() => formatMoment(MAX + 1n))).toBe('invalid_number')
    expect(codeOf(() => formatSigned(-MAX - 1n))).toBe('invalid_number')
    expect(formatSigned(-MAX)).toBe(`-${'9'.repeat(1000)}`)
  })
})

describe('sortable keys', () => {
  test('key order is numeric order', () => {
    check(
      fc.property(moments, moments, (a, b) => {
        const [ka, kb] = [sortableKey(a), sortableKey(b)]
        return ka < kb === a < b && (ka === kb) === (a === b)
      }),
    )
  })

  test('keys round-trip', () => {
    check(fc.property(moments, (n) => fromSortableKey(sortableKey(n)) === n))
  })

  test('spec examples', () => {
    expect([0n, 7n, 1023n].map(sortableKey)).toEqual(['00010', '00017', '00041023'])
  })

  test.each(['', '0001', '00021', '000201', '00000', '0001x', `1001${'1'.repeat(1001)}`])(
    'fromSortableKey rejects %j',
    (key) => {
      expect(codeOf(() => fromSortableKey(key))).toBe('invalid_key')
    },
  )
})

describe('floor division', () => {
  test('identities', () => {
    check(
      fc.property(signed, nonzero, (a, b) => {
        const [q, r] = [floorDiv(a, b), floorMod(a, b)]
        const inRange = b > 0n ? r >= 0n && r < b : r <= 0n && r > b
        return a === b * q + r && inRange && q === rationalFloor(rational(a, b))
      }),
    )
  })

  test('examples (bigint % truncates, these must not)', () => {
    expect([floorDiv(-7n, 2n), floorMod(-7n, 2n)]).toEqual([-4n, 1n])
    expect(floorMod(-1n, 7n)).toBe(6n)
    expect(floorMod(1n, -7n)).toBe(-6n)
    expect(floorDiv(7n, -2n)).toBe(-4n)
    expect(floorDiv(-6n, 3n)).toBe(-2n)
  })

  test('division by zero', () => {
    expect(codeOf(() => floorDiv(1n, 0n))).toBe('division_by_zero')
    expect(codeOf(() => floorMod(1n, 0n))).toBe('division_by_zero')
  })
})

describe('rationals', () => {
  test('rational() normalizes', () => {
    check(
      fc.property(
        fc.bigInt({ min: -BOUND, max: BOUND }),
        fc.bigInt({ min: -BOUND, max: BOUND }).filter((d) => d !== 0n),
        (num, den) => {
          const value = rational(num, den)
          const { num: n, den: d } = formatRational(value)
          return (
            value.den > 0n &&
            gcd(value.num, value.den) === 1n &&
            value.num * den === num * value.den &&
            eq(parseRational(n, d), value)
          )
        },
      ),
    )
  })

  test('field laws', () => {
    const zero = rationalFromInt(0n)
    const one = rationalFromInt(1n)
    check(
      fc.property(rationals, rationals, rationals, (a, b, c) => {
        const laws = [
          eq(rationalAdd(rationalAdd(a, b), c), rationalAdd(a, rationalAdd(b, c))),
          eq(rationalAdd(a, b), rationalAdd(b, a)),
          eq(rationalMul(rationalMul(a, b), c), rationalMul(a, rationalMul(b, c))),
          eq(rationalMul(a, b), rationalMul(b, a)),
          eq(rationalMul(a, rationalAdd(b, c)), rationalAdd(rationalMul(a, b), rationalMul(a, c))),
          eq(rationalAdd(a, zero), a),
          eq(rationalMul(a, one), a),
          eq(rationalSub(a, a), zero),
          a.num === 0n || eq(rationalMul(a, rationalDiv(one, a)), one),
          rationalCompare(a, b) === -rationalCompare(b, a),
        ]
        return laws.every(Boolean)
      }),
    )
  })

  test('floor + frac = value, frac in [0, 1)', () => {
    check(
      fc.property(rationals, (a) => {
        const frac = rationalFrac(a)
        const sum = rationalAdd(rationalFromInt(rationalFloor(a)), frac)
        return eq(sum, a) && frac.num >= 0n && frac.num < frac.den
      }),
    )
  })

  test('errors', () => {
    expect(codeOf(() => rational(1n, 0n))).toBe('division_by_zero')
    expect(codeOf(() => rationalDiv(rational(1n), rational(0n)))).toBe('division_by_zero')
    expect(codeOf(() => parseRational('1', '02'))).toBe('invalid_number')
  })
})

describe('display', () => {
  // Independent half-even reference: round |n| / 10^(len - k) to an integer, ties to even.
  function reference(n: bigint, k: number): string {
    const digits = (n < 0n ? -n : n).toString()
    let exponent = digits.length - 1
    let kept = digits
    if (digits.length > k) {
      const scale = 10n ** BigInt(digits.length - k)
      const value = BigInt(digits)
      let q = value / scale
      const twice = (value % scale) * 2n
      if (twice > scale || (twice === scale && q % 2n === 1n)) q += 1n
      kept = q.toString()
      if (kept.length > k) {
        kept = kept.slice(0, k)
        exponent += 1
      }
    }
    kept = kept.replace(/0+$/, '') || '0'
    const text = kept.length > 1 ? `${kept.charAt(0)}.${kept.slice(1)}` : kept
    return `${n < 0n ? '-' : ''}${text}e${exponent}`
  }

  test('scientific notation rounds half to even', () => {
    check(
      fc.property(
        signed,
        fc.integer({ min: 1, max: 30 }),
        fc.integer({ min: 1, max: 1001 }),
        (n, significantDigits, scientificThreshold) => {
          const text = formatInteger(n, { significantDigits, scientificThreshold, plain: true })
          const length = (n < 0n ? -n : n).toString().length
          return length < scientificThreshold
            ? text.replaceAll(',', '') === n.toString()
            : text === reference(n, significantDigits)
        },
      ),
    )
  })

  test('grouping keeps the digits', () => {
    check(
      fc.property(signed, fc.constantFrom(',', ' ', '.', "'"), (n, digitGroup) => {
        const text = formatInteger(n, { digitGroup, scientificThreshold: 1002 })
        const groups = text.replace(/^-/, '').split(digitGroup)
        const [head = '', ...rest] = groups
        return (
          groups.join('') === (n < 0n ? -n : n).toString() &&
          rest.every((group) => group.length === 3) &&
          head.length >= 1 &&
          head.length <= 3
        )
      }),
    )
  })

  test('examples', () => {
    expect(formatInteger(317n * 10n ** 97n, { significantDigits: 3 })).toBe(`3.17${TIMES_TEN}99`)
    expect(formatInteger(0n, { scientificThreshold: 1 })).toBe(`0${TIMES_TEN}0`)
    expect(formatInteger(-1234567n)).toBe('-1,234,567')
    expect(formatInteger(1234567n, { digitGroup: '' })).toBe('1234567')
  })

  test.each([
    [5n, { scientificThreshold: 0 }],
    [5n, { significantDigits: 0 }],
    [5n, { significantDigits: 1.5 }],
    [MAX + 1n, {}],
  ])('rejects %s with %j', (n, options) => {
    expect(codeOf(() => formatInteger(n, options))).toBe('invalid_number')
  })
})
