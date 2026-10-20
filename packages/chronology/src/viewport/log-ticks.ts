/**
 * Ticks of a logarithmic axis (#153): a major tick at every power of ten of base units since the
 * axis's origin (thinned out when decades are narrow), minor ticks at 2–9 × 10^k when they are
 * wide enough.
 */
import { formatInteger } from '../numbers'

import type { Tick, Ticks } from './ticks'
import { fromPx, toPx, type Viewport } from './viewport'

export interface LogTickOptions {
  /** Smallest distance between ticks (default 64). */
  readonly minSpacingPx?: number
  /** Most ticks returned (default 100). */
  readonly maxTicks?: number
  /** The label of a tick `elapsed` base units after the origin (default: the number). */
  readonly label?: (elapsed: bigint) => string
}

export function logTicks(v: Viewport, options: LogTickOptions = {}): Ticks {
  const log = v.log
  if (log === undefined) throw new RangeError('logTicks needs a logarithmic viewport')
  const minSpacing = options.minSpacingPx ?? 64
  const maxTicks = options.maxTicks ?? 100
  const label =
    options.label ?? ((elapsed: bigint) => formatInteger(elapsed, { significantDigits: 2 }))
  const decadePx = v.widthPx / (log.hi - log.lo)
  const every = Math.max(1, Math.ceil(minSpacing / decadePx))
  // From the decade holding the left edge, so a view inside one decade still gets its minor ticks.
  const first = Math.floor(log.lo / every) * every
  const end = fromPx(v, v.widthPx)
  const major: Tick[] = []
  const minor: Tick[] = []
  const tick = (elapsed: bigint): Tick => ({
    t: log.origin + elapsed,
    label: label(elapsed),
    level: 'base',
    // No regular step: a drag snaps to base units.
    multiple: 1n,
  })
  if (log.lo === 0) major.push(tick(0n))
  for (let k = first; k <= log.hi && major.length + minor.length < maxTicks; k += every) {
    const power = 10n ** BigInt(k)
    if (log.origin + power >= v.start && log.origin + power <= end) major.push(tick(power))
    // Minor ticks inside the decade, where each is at least `minSpacing` from the previous one.
    if (every !== 1) continue
    let previous = toPx(v, log.origin + power)
    for (let m = 2n; m <= 9n && major.length + minor.length < maxTicks; m++) {
      const t = log.origin + m * power
      if (t > end) break
      const x = toPx(v, t)
      if (x < 0 || x - previous < minSpacing) continue
      minor.push(tick(m * power))
      previous = x
    }
  }
  return { major, minor }
}
