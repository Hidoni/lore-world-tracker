/**
 * Eras: display-level year numbering (chronology-engine.md §3.8, §8). The Python twin is
 * backend/src/lore/chronology/calendar/eras.py.
 *
 * Eras partition time by their resolved starts. `forward` eras count from the year containing
 * their start (`era_year = Y − Y(start) + first`); `backward` eras count down towards the next era
 * (`era_year = Y_end − Y + first − 1`). Without eras, years are astronomical.
 */
import {
  type CompiledCalendar,
  type CompiledEra,
  DateError,
  activeRegime,
  bisectRight,
  defined,
} from './compiled'

export interface EraValue {
  readonly id: string
  /** The era-relative year. */
  readonly year: bigint
  readonly abbr: string
  readonly name: string
}

/** The era containing `t` (`null` for a calendar without eras). */
export function eraAt(calendar: CompiledCalendar, t: bigint): CompiledEra | null {
  if (calendar.eras.length === 0) return null
  const starts = calendar.eras.slice(1).map((era) => defined(era.start)) // all set
  return defined(calendar.eras[bisectRight(starts, t)])
}

/** §8 `eraOf`: the era of `t` and the era-relative number of `t`'s year. */
export function eraOf(calendar: CompiledCalendar, t: bigint): EraValue | null {
  const era = eraAt(calendar, t)
  if (era === null) return null
  const year = activeRegime(calendar, t).yearOf(t)
  return { id: era.id, year: era.eraYear(year), abbr: era.abbr, name: era.name }
}

/** The era with this id; `invalid_date` (on the top level) for an unknown era. */
export function findEra(calendar: CompiledCalendar, eraId: string): CompiledEra {
  const era = calendar.eras.find((e) => e.id === eraId)
  if (era === undefined) {
    throw new DateError('invalid_date', `unknown era ${eraId}`, defined(calendar.levels.at(-1)))
  }
  return era
}

/** The §5.6 JSON shape of an era value. */
export function eraValueToJson(value: EraValue): Record<string, string> {
  return { id: value.id, year: value.year.toString(), abbr: value.abbr, name: value.name }
}
