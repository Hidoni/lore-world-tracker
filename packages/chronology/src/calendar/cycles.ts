/**
 * Parallel cycles: weeks, market weeks, Tzolkʼin-style combinations (chronology-engine.md §3.7,
 * §8). The Python twin is backend/src/lore/chronology/calendar/cycles.py.
 *
 * A cycle counts the units of its level that it doesn't exclude (`cycle_excluded` on the unit or
 * an ancestor, `cycleFilter`). Continuous cycles index units by their counted ordinal relative to
 * the anchor unit; reset cycles restart in every unit of the reset level. Excluded units have no
 * value.
 */
import { floorMod } from '../numbers'
import {
  type CompiledCalendar,
  type CompiledCycle,
  type CompiledRegime,
  DateError,
  activeRegime,
  defined,
} from './compiled'
import { REGULAR, countedPosition, cycleFilter } from './units'

export interface CycleValue {
  /** `0 ≤ index < length`. */
  readonly index: number
  /** The name at `index`, if the cycle has names. */
  readonly name: string | null
  /** Display number: `index + numberStart`. */
  readonly n: number
}

/** The value of `cycle` for the unit containing `t` in `regime` (`null`: excluded). */
export function regimeCycleValue(
  top: number,
  regime: CompiledRegime,
  cycle: CompiledCycle,
  t: bigint,
): CycleValue | null {
  const filter = cycleFilter(cycle.id)
  const [before, counted] = countedPosition(top, regime, t, cycle.level, filter)
  if (!counted) return null
  let first: bigint
  if (cycle.reset === null) {
    first = defined(cycle.anchorOrdinal) // set at compile time for continuous cycles
  } else {
    const [, , resetStart] = countedPosition(top, regime, t, cycle.reset, REGULAR)
    first = countedPosition(top, regime, resetStart, cycle.level, filter)[0]
  }
  const index = Number(floorMod(before - first + BigInt(cycle.anchorIndex), BigInt(cycle.length)))
  const name = cycle.names === null ? null : defined(cycle.names[index])
  return { index, name, n: index + cycle.numberStart }
}

/** Every cycle of `regime` at `t` (the `cycles` member of `toFields`). */
export function cycleValues(
  top: number,
  regime: CompiledRegime,
  t: bigint,
): Map<string, CycleValue | null> {
  return new Map(regime.cycles.map((cycle) => [cycle.id, regimeCycleValue(top, regime, cycle, t)]))
}

/** §8 `cycleValue`: the cycle's value at `t` in the regime active at `t`. */
export function cycleValue(
  calendar: CompiledCalendar,
  t: bigint,
  cycleId: string,
): CycleValue | null {
  const regime = activeRegime(calendar, t)
  const cycle = regime.cycles.find((c) => c.id === cycleId)
  if (cycle === undefined) {
    throw new DateError('unknown_cycle', `no cycle ${cycleId} in regime ${regime.id}`)
  }
  return regimeCycleValue(calendar.levels.length - 1, regime, cycle, t)
}
