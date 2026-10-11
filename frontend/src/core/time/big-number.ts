import { MAX_DIGITS } from '@lore/chronology'

/** Why a big number didn't parse (shown under the input). */
export class BigNumberError extends Error {
  override readonly name = 'BigNumberError'
}

/** Digit grouping a user may type: commas, spaces (incl. thin/no-break), apostrophes, `_`. */
const SEPARATORS = /[,\s\u00a0\u2009\u202f'\u2019_]/g
/** One factor: `-1.5e3`, `10^100`, `3.17 × 10^99` is two factors. Units after it are labels. */
const FACTOR = /^([+-]?)(\d+)(?:\.(\d+))?(?:(?:e|E)([+-]?\d+)|\^(\d+))?([a-zA-Zµ][\w./µ]*)?$/

function pow10(exponent: number): bigint {
  return 10n ** BigInt(exponent)
}

/** A factor as an exact fraction `num / den` (den a power of ten). */
function factor(text: string): { num: bigint; den: bigint } {
  const match = FACTOR.exec(text)
  if (match === null) throw new BigNumberError(`“${text}” isn’t a number`)
  const [, sign = '', whole = '', fraction = '', exponentText, powerText] = match
  if (powerText !== undefined) {
    if (fraction !== '') throw new BigNumberError('A power needs a whole base, like 10^100')
    const power = Number(powerText)
    if (power > MAX_DIGITS) throw new BigNumberError(`At most ${MAX_DIGITS} digits`)
    const value = BigInt(whole) ** BigInt(power)
    return { num: sign === '-' ? -value : value, den: 1n }
  }
  const exponent = exponentText === undefined ? 0 : Number(exponentText)
  if (Math.abs(exponent) > MAX_DIGITS) throw new BigNumberError(`At most ${MAX_DIGITS} digits`)
  const digits = BigInt(whole + fraction)
  const scale = exponent - fraction.length
  const num = scale >= 0 ? digits * pow10(scale) : digits
  const den = scale >= 0 ? 1n : pow10(-scale)
  return { num: sign === '-' ? -num : num, den }
}

/**
 * Parses what a user types for an arbitrary-size integer: grouped digits (`1,000,000`),
 * exponents (`1e100`, `3.17e99`), powers (`10^100`) and products of factors, each optionally
 * followed by a unit label (`10^100 years × 31,557,600 s`). The result must be a whole number of
 * at most 1000 digits; `signed: false` also rejects negatives.
 */
export function parseBigNumber(text: string, options: { signed?: boolean } = {}): bigint {
  const trimmed = text.trim()
  if (trimmed === '') throw new BigNumberError('Enter a number')
  let num = 1n
  let den = 1n
  // Factors are separated by ×, *, or a lone x between spaces ("3 x 10^9").
  for (const part of trimmed.split(/\s*(?:×|\*|\s[xX]\s)\s*/)) {
    // Inner spaces group digits ("31 557 600") or separate a unit ("5 years").
    const unitAt = part.search(/\s[a-zA-Zµ]/)
    const number = unitAt < 0 ? part : part.slice(0, unitAt)
    const found = factor(number.replace(SEPARATORS, ''))
    num *= found.num
    den *= found.den
  }
  if (num % den !== 0n) throw new BigNumberError('Must be a whole number')
  const value = num / den
  if (!options.signed && value < 0n) throw new BigNumberError('Must not be negative')
  const length = (value < 0n ? -value : value).toString().length
  if (length > MAX_DIGITS) throw new BigNumberError(`At most ${MAX_DIGITS} digits`)
  return value
}
