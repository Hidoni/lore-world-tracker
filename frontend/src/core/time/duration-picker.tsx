import type { Duration } from '@lore/chronology'
import { useId, useState } from 'react'

import { BigNumberInput } from './big-number-input'
import type { DimensionTime, Lens } from './calendars'
import { SELECT_CLASS } from './select'

type Sign = 1 | -1

interface Draft {
  /** `base`, or a calendar id. */
  mode: string
  sign: Sign
  units: bigint | null
  amounts: Record<string, bigint | null>
}

function draftOf(value: Duration | null): Draft {
  if (value === null) return { mode: 'base', sign: 1, units: null, amounts: {} }
  if (value.kind === 'base') {
    const units = BigInt(value.units)
    return {
      mode: 'base',
      sign: units < 0n ? -1 : 1,
      units: units < 0n ? -units : units,
      amounts: {},
    }
  }
  const amounts: Record<string, bigint | null> = {}
  for (const [level, amount] of Object.entries(value.amounts)) {
    if (amount !== undefined) amounts[level] = BigInt(amount)
  }
  return { mode: value.calendar_id, sign: value.sign, units: null, amounts }
}

/** The duration a draft stands for (`null`: nothing entered yet, or invalid). */
function durationOf(draft: Draft): Duration | null {
  if (draft.mode === 'base') {
    if (draft.units === null) return null
    return { kind: 'base', units: (BigInt(draft.sign) * draft.units).toString() }
  }
  const amounts = Object.fromEntries(
    Object.entries(draft.amounts).flatMap(([level, amount]) =>
      amount === null || amount === 0n ? [] : [[level, amount.toString()]],
    ),
  )
  if (Object.keys(amounts).length === 0) return null
  return { kind: 'calendar', calendar_id: draft.mode, amounts, sign: draft.sign }
}

/**
 * A duration (frontend.md §8, time-model.md §8): base units, or amounts per level of one of the
 * dimension's calendars ("3 months 2 days"), with a sign. Reports `null` until something is
 * entered.
 */
export function DurationPicker({
  dimension,
  lenses,
  value,
  onChange,
  label = 'Duration',
}: {
  dimension: DimensionTime
  lenses: readonly Lens[]
  value: Duration | null
  onChange: (value: Duration | null) => void
  label?: string
}) {
  const [draft, setDraft] = useState(() => draftOf(value))
  const id = useId()
  const calendars = lenses.filter((lens) => lens.calendar !== null)
  const lens = calendars.find((candidate) => candidate.id === draft.mode)
  const update = (patch: Partial<Draft>) => {
    const next = { ...draft, ...patch }
    setDraft(next)
    onChange(durationOf(next))
  }
  // Coarse to fine, like a date.
  const levels = [...(lens?.calendar?.definition.levels ?? [])].reverse()

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-sm font-medium">{label}</legend>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={`${label} sign`}
          className={SELECT_CLASS}
          value={String(draft.sign)}
          onChange={(event) => {
            update({ sign: event.target.value === '-1' ? -1 : 1 })
          }}
        >
          <option value="1">+ later</option>
          <option value="-1">− earlier</option>
        </select>
        <select
          id={`${id}-mode`}
          aria-label={`${label} unit`}
          className={SELECT_CLASS}
          value={draft.mode}
          onChange={(event) => {
            update({ mode: event.target.value, amounts: {} })
          }}
        >
          <option value="base">{dimension.baseUnit.plural}</option>
          {calendars.map((calendar) => (
            <option key={calendar.id} value={calendar.id}>
              {calendar.name} units
            </option>
          ))}
        </select>
      </div>
      {draft.mode === 'base' || lens === undefined ? (
        <BigNumberInput
          aria-label={`${label} in ${dimension.baseUnit.plural}`}
          value={draft.units}
          onChange={(units) => {
            update({ units })
          }}
        />
      ) : (
        <div className="grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-1">
          {levels.map((level) => (
            <label key={level.id} className="contents">
              <span className="pt-2 text-sm text-muted-foreground">{level.plural}</span>
              <BigNumberInput
                aria-label={`${label}: ${level.plural}`}
                placeholder="0"
                value={draft.amounts[level.id] ?? null}
                onChange={(amount) => {
                  update({ amounts: { ...draft.amounts, [level.id]: amount } })
                }}
              />
            </label>
          ))}
        </div>
      )}
    </fieldset>
  )
}
