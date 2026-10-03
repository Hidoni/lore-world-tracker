/**
 * Overlays: astronomical cycles shown alongside dates (chronology-engine.md §3.9, §8). The Python
 * twin is backend/src/lore/chronology/calendar/overlays.py.
 *
 * An overlay never affects the date structure. Its phase at `t` is the exact rational
 * `frac((t − epoch) / period)` in `[0, 1)`; the phase name is the last phase whose `from` is at
 * most that value. Everything is exact (`BigRational`), whatever the magnitudes.
 */
import {
  type BigRational,
  formatRational,
  parseRational,
  rationalAdd,
  rationalCompare,
  rationalDiv,
  rationalFloor,
  rationalFrac,
  rationalFromInt,
  rationalMul,
  rationalSub,
} from '../numbers'
import type { Overlay } from '../schema.gen'
import { type CompiledCalendar, DateError, defined } from './compiled'

export interface OverlayValue {
  /** `0 ≤ phase < 1`. */
  readonly phase: BigRational
  readonly name: string
}

/** The §5.6 JSON shape of an overlay value. */
export function overlayValueToJson(value: OverlayValue): Record<string, unknown> {
  return { phase: formatRational(value.phase), name: value.name }
}

/** The overlay with its resolved epoch; `unknown_overlay` if the calendar has none. */
function overlayOf(calendar: CompiledCalendar, overlayId: string): readonly [Overlay, bigint] {
  const overlays = calendar.definition.overlays ?? []
  const index = overlays.findIndex((overlay) => overlay.id === overlayId)
  if (index < 0) throw new DateError('unknown_overlay', `no overlay ${overlayId}`)
  return [defined(overlays[index]), defined(calendar.overlayEpochs[index])]
}

function periodOf(overlay: Overlay): BigRational {
  return parseRational(overlay.period.num, overlay.period.den)
}

function value(overlay: Overlay, epoch: bigint, t: bigint): OverlayValue {
  const phase = rationalFrac(rationalDiv(rationalFromInt(t - epoch), periodOf(overlay)))
  const named = overlay.phases.findLast(
    (p) => rationalCompare(parseRational(p.from.num, p.from.den), phase) <= 0,
  )
  return { phase, name: defined(named).name }
}

/** §8 `overlayPhase`: the overlay's exact phase at `t` and its name. */
export function overlayPhase(
  calendar: CompiledCalendar,
  t: bigint,
  overlayId: string,
): OverlayValue {
  const [overlay, epoch] = overlayOf(calendar, overlayId)
  return value(overlay, epoch, t)
}

/** Every overlay's value at `t` (the `overlays` member of `toFields`). */
export function overlayValues(calendar: CompiledCalendar, t: bigint): Map<string, OverlayValue> {
  return new Map(
    (calendar.definition.overlays ?? []).map((overlay, i) => [
      overlay.id,
      value(overlay, defined(calendar.overlayEpochs[i]), t),
    ]),
  )
}

function ceil(a: BigRational): bigint {
  return -rationalFloor({ num: -a.num, den: a.den })
}

/**
 * §8 `nextPhaseAt`: the first moment `≥ t` at which the overlay reaches `phase`.
 *
 * The overlay is at `phase` at the exact instants `x(n) = epoch + (n + phase)·period`; the result
 * is `ceil(x(n))` for the smallest `n` with `ceil(x(n)) ≥ t` (the moment itself when `x(n)` is an
 * integer, else the first moment after it). `phase` must lie in `[0, 1)` (`invalid_date`
 * otherwise).
 */
export function nextPhaseAt(
  calendar: CompiledCalendar,
  t: bigint,
  overlayId: string,
  phase: BigRational,
): bigint {
  const [overlay, epoch] = overlayOf(calendar, overlayId)
  if (phase.num < 0n || phase.num >= phase.den) {
    throw new DateError('invalid_date', 'a phase lies in [0, 1)')
  }
  const period = periodOf(overlay)
  // ceil(x(n)) ≥ t  ⇔  x(n) > t − 1  ⇔  n > (t − 1 − epoch) / period − phase
  const turns = rationalDiv(rationalFromInt(t - 1n - epoch), period)
  const n = rationalFloor(rationalSub(turns, phase)) + 1n
  const instant = rationalAdd(
    rationalFromInt(epoch),
    rationalMul(rationalAdd(rationalFromInt(n), phase), period),
  )
  return ceil(instant)
}
