/**
 * Exact numeric utilities shared by the whole chronology engine (chronology-engine.md §2). The
 * Python twin is backend/src/lore/chronology/numbers.py; both pass the vectors in
 * spec/chronology/conformance/cases/numbers/.
 *
 * In-world integers are `bigint`. Never use `number`, `%` or `/` on them directly: bigint `%`
 * and `/` truncate towards zero, so use floorDiv/floorMod.
 */

/** Every moment, duration and offset has at most 1000 decimal digits (time-model.md §2.2). */
export const MAX_DIGITS = 1000

const KEY_PREFIX_LENGTH = 4
const MAX_VALUE = 10n ** BigInt(MAX_DIGITS) // exclusive bound on magnitudes
const MOMENT = /^(0|[1-9][0-9]*)$/
const SIGNED = /^(0|-?[1-9][0-9]*)$/
const KEY = /^([0-9]{4})(0|[1-9][0-9]*)$/

/** Separator between mantissa and exponent in display notation: `3.17 × 10^99`. */
export const TIMES_TEN = ' × 10^'

export type NumberErrorCode = 'invalid_number' | 'invalid_key' | 'division_by_zero'

/** A numeric input the engine rejects. `code` is shared with the Python engine. */
export class NumberError extends Error {
  readonly code: NumberErrorCode

  constructor(code: NumberErrorCode, message: string) {
    super(message)
    this.name = 'NumberError'
    this.code = code
  }
}

function abs(n: bigint): bigint {
  return n < 0n ? -n : n
}

function checkMagnitude(n: bigint): void {
  if (abs(n) >= MAX_VALUE) throw new NumberError('invalid_number', `more than ${MAX_DIGITS} digits`)
}

// --- integer strings ----------------------------------------------------------------------------

/** Parse a canonical non-negative decimal string (no sign, leading zeros or whitespace). */
export function parseMoment(text: string): bigint {
  if (text.length > MAX_DIGITS || !MOMENT.test(text)) {
    throw new NumberError(
      'invalid_number',
      `not a moment string: ${JSON.stringify(text.slice(0, 40))}`,
    )
  }
  return BigInt(text)
}

/** Format a moment (`0 ≤ n < 10^1000`) as its canonical decimal string. */
export function formatMoment(n: bigint): string {
  if (n < 0n) throw new NumberError('invalid_number', 'a moment cannot be negative')
  checkMagnitude(n)
  return n.toString()
}

/** Parse a canonical signed decimal string (`-0` and leading zeros are rejected). */
export function parseSigned(text: string): bigint {
  const digits = text.startsWith('-') ? text.slice(1) : text
  if (digits.length > MAX_DIGITS || !SIGNED.test(text)) {
    throw new NumberError(
      'invalid_number',
      `not a signed integer string: ${JSON.stringify(text.slice(0, 40))}`,
    )
  }
  return BigInt(text)
}

/** Format a signed integer (`|n| < 10^1000`) as its canonical decimal string. */
export function formatSigned(n: bigint): string {
  checkMagnitude(n)
  return n.toString()
}

// --- sortable keys ------------------------------------------------------------------------------

/** Encode `n ≥ 0` so that byte-wise order equals numeric order: 4-digit length + digits. */
export function sortableKey(n: bigint): string {
  const digits = formatMoment(n)
  return String(digits.length).padStart(KEY_PREFIX_LENGTH, '0') + digits
}

/** Decode a sortable key, rejecting any string sortableKey cannot produce. */
export function fromSortableKey(key: string): bigint {
  const [, prefix = '', digits = ''] = KEY.exec(key) ?? [] // digits is '' only without a match
  if (digits === '' || Number(prefix) !== digits.length || digits.length > MAX_DIGITS) {
    throw new NumberError('invalid_key', `not a sortable key: ${JSON.stringify(key.slice(0, 40))}`)
  }
  return BigInt(digits)
}

// --- floor division -----------------------------------------------------------------------------

/** `⌊a / b⌋` (rounds towards −∞, unlike bigint `/`, which truncates). */
export function floorDiv(a: bigint, b: bigint): bigint {
  if (b === 0n) throw new NumberError('division_by_zero', 'division by zero')
  const q = a / b
  return a % b !== 0n && a < 0n !== b < 0n ? q - 1n : q
}

/** `a − b·⌊a / b⌋`: the result has the sign of `b` (`-1 mod 7 = 6`). */
export function floorMod(a: bigint, b: bigint): bigint {
  return a - b * floorDiv(a, b)
}

// --- rationals ----------------------------------------------------------------------------------

/**
 * An exact rational, always normalized: `gcd(num, den) = 1` and `den > 0` (time-model.md §2.4).
 * (The JSON wire form is the generated `Rational` type, with decimal strings.)
 */
export interface BigRational {
  readonly num: bigint
  readonly den: bigint
}

/** The greatest common divisor of `|a|` and `|b|` (`gcd(0, 0) = 0`). */
export function gcd(a: bigint, b: bigint): bigint {
  let x = abs(a)
  let y = abs(b)
  while (y !== 0n) [x, y] = [y, x % y]
  return x
}

/** The normalized rational `num/den` (`den` may be negative, not zero). */
export function rational(num: bigint, den = 1n): BigRational {
  if (den === 0n) throw new NumberError('division_by_zero', 'rational with a zero denominator')
  const sign = den < 0n ? -1n : 1n
  const divisor = gcd(num, den)
  return { num: (sign * num) / divisor, den: (sign * den) / divisor }
}

export function rationalFromInt(n: bigint): BigRational {
  return { num: n, den: 1n }
}

export function rationalAdd(a: BigRational, b: BigRational): BigRational {
  return rational(a.num * b.den + b.num * a.den, a.den * b.den)
}

export function rationalSub(a: BigRational, b: BigRational): BigRational {
  return rational(a.num * b.den - b.num * a.den, a.den * b.den)
}

export function rationalMul(a: BigRational, b: BigRational): BigRational {
  return rational(a.num * b.num, a.den * b.den)
}

export function rationalDiv(a: BigRational, b: BigRational): BigRational {
  if (b.num === 0n) throw new NumberError('division_by_zero', 'division by zero')
  return rational(a.num * b.den, a.den * b.num)
}

export function rationalCompare(a: BigRational, b: BigRational): -1 | 0 | 1 {
  const left = a.num * b.den
  const right = b.num * a.den
  return left < right ? -1 : left > right ? 1 : 0
}

export function rationalFloor(a: BigRational): bigint {
  return floorDiv(a.num, a.den)
}

/** `a − ⌊a⌋`, in `[0, 1)`. */
export function rationalFrac(a: BigRational): BigRational {
  return { num: floorMod(a.num, a.den), den: a.den }
}

/** Parse integer strings into a normalized rational (non-normalized input is normalized). */
export function parseRational(num: string, den: string): BigRational {
  return rational(parseSigned(num), parseSigned(den))
}

/** The wire form `{num, den}` with decimal strings (normalized). */
export function formatRational(value: BigRational): { num: string; den: string } {
  return { num: formatSigned(value.num), den: formatSigned(value.den) }
}

// --- display ------------------------------------------------------------------------------------

export interface IntegerDisplayOptions {
  /** Group separator for digits below the threshold; `''` disables grouping. Default `,`. */
  digitGroup?: string
  /** Digit count from which scientific notation is used. Default 16. */
  scientificThreshold?: number
  /** Significant digits of the scientific mantissa. Default 4. */
  significantDigits?: number
  /** `3.17e99` instead of `3.17 × 10^99`. Default false. */
  plain?: boolean
}

function group(digits: string, separator: string): string {
  if (separator === '') return digits
  const head = digits.length % 3 || 3
  const groups = [digits.slice(0, head)]
  for (let i = head; i < digits.length; i += 3) groups.push(digits.slice(i, i + 3))
  return groups.join(separator)
}

/** Round the digit string to `keep` digits, half to even; returns [digits, exponent carry]. */
function roundHalfEven(digits: string, keep: number): [string, number] {
  const kept = digits.slice(0, keep)
  const first = digits.charAt(keep)
  const tail = digits.slice(keep + 1)
  const lastOdd = Number(kept.charAt(kept.length - 1)) % 2 === 1
  const roundUp = first > '5' || (first === '5' && (/[1-9]/.test(tail) || lastOdd))
  if (!roundUp) return [kept, 0]
  const bumped = (BigInt(kept) + 1n).toString()
  // 999… → 1000…: one more digit before the point.
  return bumped.length > keep ? [bumped.slice(0, keep), 1] : [bumped, 0]
}

/**
 * Display an integer: grouped digits, or scientific notation from `scientificThreshold` digits.
 * Scientific notation rounds to `significantDigits` significant digits, half to even, drops
 * trailing zeros of the mantissa and joins it with TIMES_TEN (`3.17e99` when `plain`). The
 * mantissa is never grouped. Negative numbers get a leading `-`. The options are the calendar
 * `display` values (chronology-engine.md §3.11); the defaults match.
 */
export function formatInteger(n: bigint, options: IntegerDisplayOptions = {}): string {
  const {
    digitGroup = ',',
    scientificThreshold = 16,
    significantDigits = 4,
    plain = false,
  } = options
  if (
    !Number.isSafeInteger(scientificThreshold) ||
    !Number.isSafeInteger(significantDigits) ||
    scientificThreshold < 1 ||
    significantDigits < 1
  ) {
    throw new NumberError('invalid_number', 'threshold and significant digits must be integers ≥ 1')
  }
  checkMagnitude(n)
  const sign = n < 0n ? '-' : ''
  const digits = abs(n).toString()
  if (digits.length < scientificThreshold) return sign + group(digits, digitGroup)
  let exponent = digits.length - 1
  let mantissa = digits
  if (digits.length > significantDigits) {
    const [rounded, carry] = roundHalfEven(digits, significantDigits)
    mantissa = rounded
    exponent += carry
  }
  mantissa = mantissa.replace(/0+$/, '') || '0'
  const text = mantissa.length > 1 ? `${mantissa.charAt(0)}.${mantissa.slice(1)}` : mantissa
  return plain ? `${sign}${text}e${exponent}` : `${sign}${text}${TIMES_TEN}${exponent}`
}
