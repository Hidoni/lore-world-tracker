/** Sort key digits in binary (SQLite) order: the backend's `SortKey` alphabet. */
const DIGITS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
const BASE = DIGITS.length

const digit = (key: string, index: number): number =>
  index < key.length ? DIGITS.indexOf(key.charAt(index)) : 0

/** A key between `low` and `high` (as base-62 fractions; `''` is 0, `null` is 1). */
function midpoint(low: string, high: string | null): string {
  for (let index = 0; ; index += 1) {
    const a = digit(low, index)
    const b = high === null ? BASE : digit(high, index)
    if (a === b) continue
    const prefix = low.slice(0, index).padEnd(index, '0')
    if (b - a > 1) return prefix + DIGITS.charAt((a + b) >> 1)
    // Neighbouring digits: keep `low`'s and go between the rest of it and the top.
    return prefix + DIGITS.charAt(a) + midpoint(low.slice(index + 1), null)
  }
}

/**
 * A sort key ordering between `before` and `after` (`null`: no neighbour on that side), for
 * moving an item (galleries order by `sort_key`, compared as text).
 */
export function keyBetween(before: string | null, after: string | null): string {
  if (before !== null && after !== null && before >= after) {
    throw new Error(`keyBetween: ${before} is not before ${after}`)
  }
  return midpoint(before ?? '', after)
}

/** The key for moving the item at `from` to `to` in `keys` (sorted). */
export function keyForMove(keys: readonly string[], from: number, to: number): string {
  const rest = keys.filter((_, index) => index !== from)
  return keyBetween(rest[to - 1] ?? null, rest[to] ?? null)
}
