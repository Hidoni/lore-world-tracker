import {
  type CompiledCalendar,
  DateError,
  formatDate,
  formatInteger,
  options,
  type TimePoint,
  type ValidationError,
} from '@lore/chronology'
import { useState } from 'react'

import { Input } from '@/components/ui/input'

import { BigNumberInput } from '../big-number-input'
import type { DimensionTime, Lens } from '../calendars'
import { TimePointPicker } from '../time-point-picker'
import { errorMessage } from './model'

/** Focuses the field bound to `path` (or the nearest one above it). */
function focusPath(path: string) {
  for (let at = path; at !== ''; at = at.slice(0, at.lastIndexOf('/'))) {
    const field = document.querySelector<HTMLElement>(`[data-path="${CSS.escape(at)}"]`)
    if (field !== null) {
      field.focus()
      return
    }
  }
}

/** The engine's problems with the definition, each focusing its field. */
export function ErrorList({ errors }: { errors: readonly ValidationError[] }) {
  if (errors.length === 0) {
    return <p className="text-sm text-muted-foreground">The calendar compiles.</p>
  }
  return (
    <ul aria-label="Problems" className="flex flex-col gap-1 text-sm">
      {errors.map((error) => (
        <li key={`${error.path}:${error.code}`}>
          <button
            type="button"
            className="text-left text-destructive underline-offset-2 hover:underline"
            onClick={() => {
              focusPath(error.path)
            }}
          >
            {errorMessage(error)}
          </button>{' '}
          <code className="text-xs text-muted-foreground">{error.path || '/'}</code>
        </li>
      ))}
    </ul>
  )
}

interface Unit {
  key: string
  label: string
  days: string
}

/** The units of a year (the level below the top) and how many children each has. */
function yearUnits(calendar: CompiledCalendar, year: string): Unit[] | string {
  const order = [...calendar.levels].reverse()
  const [top, first, second] = order
  if (top === undefined || first === undefined) return []
  try {
    const children = options(calendar, { [top]: year }, first)
    return children.flatMap((option): Unit[] => {
      if (option.kind === 'range') {
        if (option.first === null || option.last === null) return []
        const units: Unit[] = []
        for (let n = option.first; n <= option.last && units.length < 400; n++) {
          units.push({ key: n.toString(), label: n.toString(), days: '' })
        }
        return units
      }
      const value = option.slotId
      let days = ''
      if (second !== undefined) {
        const inner = options(calendar, { [top]: year, [first]: value }, second)
        const count = inner.reduce(
          (sum, item) =>
            sum +
            (item.kind === 'slot'
              ? 1n
              : item.first === null || item.last === null
                ? 0n
                : item.last - item.first + 1n),
          0n,
        )
        days = formatInteger(count)
      }
      const name = option.name ?? option.slotId
      return [{ key: value, label: option.intercalary ? `${name} (intercalary)` : name, days }]
    })
  } catch (error) {
    if (error instanceof DateError) return error.message
    throw error
  }
}

/** A year of the calendar: its units (months) and their lengths, for any year. */
export function YearGrid({ calendar }: { calendar: CompiledCalendar }) {
  const [year, setYear] = useState('1')
  const order = [...calendar.levels].reverse()
  const [topLevel, childLevel, grandchild] = order
  const label = (id: string | undefined) =>
    calendar.definition.levels.find((level) => level.id === id)?.plural ?? id ?? ''
  const units = /^-?\d+$/.test(year) ? yearUnits(calendar, year) : 'Enter a year number.'
  return (
    <section aria-label="Year" className="flex flex-col gap-2">
      <label className="flex items-center gap-2 text-sm">
        {calendar.definition.levels.find((level) => level.id === topLevel)?.label ?? 'Year'}
        <Input
          aria-label="Preview year"
          className="h-8 w-28"
          value={year}
          onChange={(event) => {
            setYear(event.target.value.trim())
          }}
        />
      </label>
      {typeof units === 'string' ? (
        <p className="text-sm text-destructive">{units}</p>
      ) : (
        <table className="text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="pr-3 font-normal">{label(childLevel)}</th>
              {grandchild !== undefined && <th className="font-normal">{label(grandchild)}</th>}
            </tr>
          </thead>
          <tbody>
            {units.map((unit) => (
              <tr key={unit.key}>
                <td className="pr-3">{unit.label}</td>
                {grandchild !== undefined && <td>{unit.days}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

/** Date ⇄ moment through the draft calendar (the TS engine, as it stands). */
export function Converter({
  calendar,
  dimension,
}: {
  calendar: CompiledCalendar
  dimension: DimensionTime
}) {
  const lens: Lens = { id: 'draft', name: 'This calendar', calendar }
  const [point, setPoint] = useState<TimePoint | null>(null)
  const [moment, setMoment] = useState<bigint | null>(null)
  const finest = calendar.levels[0] ?? 'base'
  let date: string | null = null
  if (moment !== null) {
    try {
      date = formatDate(calendar, moment, finest)
    } catch (error) {
      if (!(error instanceof DateError)) throw error
      date = error.message
    }
  }
  return (
    <section aria-label="Converter" className="flex flex-col gap-3">
      <TimePointPicker
        dimension={dimension}
        lenses={[lens]}
        value={null}
        label="Date → moment"
        onChange={setPoint}
      />
      {point === null && <p className="text-xs text-muted-foreground">Pick a valid date.</p>}
      <div className="flex flex-col gap-1">
        <span className="text-sm font-medium">Moment → date</span>
        <BigNumberInput aria-label="Moment" value={moment} min={0n} onChange={setMoment} />
        {date !== null && (
          <p className="text-sm" data-testid="converted-date">
            {date}
          </p>
        )}
      </div>
    </section>
  )
}
