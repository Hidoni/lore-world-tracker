import { formatInteger, type BaseUnit } from '@lore/chronology'
import type { Tick, Ticks, Viewport } from '@lore/chronology/viewport'

/** Digits of `|n|` (`1` for 0). */
function digits(n: bigint): number {
  return (n < 0n ? -n : n).toString().length
}

/** `t` with enough significant digits to tell apart moments `step` apart. */
function label(t: bigint, step: bigint, unit: BaseUnit): string {
  const significant = Math.max(1, digits(t) - digits(step) + 2)
  return `${formatInteger(t, { significantDigits: significant })} ${unit.abbr}`
}

/**
 * Ticks for the Absolute calendar (raw base units, time-model.md §3): every `1, 2, 5 × 10^k` base
 * units, the smallest step at least `minSpacingPx` apart, with major ticks at the next power of
 * ten (1, 2, 5 → 10). Like `ticks()` for calendars: sorted, no minor tick on a major one, at most
 * `maxTicks`.
 */
export function absoluteTicks(
  v: Viewport,
  unit: BaseUnit,
  options: { minSpacingPx?: number; maxTicks?: number } = {},
): Ticks {
  const minSpacing = options.minSpacingPx ?? 64
  const maxTicks = options.maxTicks ?? 100
  // The smallest step whose pixel spacing is at least `minSpacing`: span · minSpacing / width.
  const needed =
    (v.span * BigInt(Math.ceil(minSpacing * 1024))) / BigInt(Math.round(v.widthPx * 1024))
  let step = 1n
  let power = 1n
  for (;;) {
    const candidate = [1n, 2n, 5n].map((m) => m * power).find((value) => value >= needed)
    if (candidate !== undefined) {
      step = candidate
      break
    }
    power *= 10n
  }
  const majorStep = power * 10n
  const end = v.start + v.span
  // The first multiple of `step` at or after the start (bigint division truncates toward 0).
  const first = v.start <= 0n ? -(-v.start / step) * step : ((v.start + step - 1n) / step) * step
  const major: Tick[] = []
  const minor: Tick[] = []
  for (let t = first; t < end && major.length + minor.length < maxTicks; t += step) {
    const isMajor = t % majorStep === 0n
    const tick: Tick = {
      t,
      label: label(t, isMajor ? majorStep : step, unit),
      level: 'base',
      multiple: isMajor ? majorStep : step,
    }
    ;(isMajor ? major : minor).push(tick)
  }
  return { major, minor }
}
