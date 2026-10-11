import {
  type CompiledCalendar,
  DateError,
  formatAbsolute,
  formatMoment,
  fromFields,
  options as unitOptions,
  type SlotRef,
  type TimePoint,
} from '@lore/chronology'
import { useId, useState, type KeyboardEvent, type ReactNode } from 'react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { BigNumberInput } from './big-number-input'
import type { DimensionTime, Lens } from './calendars'
import { formatIn } from './format'
import { RelativeTab, relativeDraftOf, type RelativeDraft } from './relative-tab'
import { SELECT_CLASS } from './select'

/** Ranges up to this many units become a select; longer ones a number input. */
const MAX_LISTED = 1000

interface Draft {
  tab: 'date' | 'absolute' | 'relative'
  calendarId: string | null
  era: string | null
  regime: string | null
  precision: string | null
  /** Per level, as typed or picked: numbers as strings, named units as slot ids. */
  fields: Record<string, string>
  approximate: boolean
  absolute: bigint | null
  relative: RelativeDraft
  /** The relative tab's resolved point (reported by `RelativeTab`). */
  relativePoint: TimePoint | null
}

/** One level's input: a list of choices, or a free number. */
type LevelInput =
  | { kind: 'choices'; choices: { value: string; label: string }[] }
  | { kind: 'number'; first: bigint | null; last: bigint | null }

interface LevelView {
  id: string
  label: string
  input: LevelInput
  value: string | null
}

interface Resolved {
  levels: LevelView[]
  /** The time point when the draft is a valid date. */
  point: TimePoint | null
  t: bigint | null
  error: string | null
  /** The regimes to choose from when the date is ambiguous across a reform. */
  regimes: { id: string; name: string }[]
}

const DATE_ERRORS: Record<string, string> = {
  invalid_date: 'Not a valid date',
  reform_gap: 'This date was skipped by a calendar reform',
  reform_ambiguous: 'This date exists twice across a calendar reform: pick the calendar rules',
}

function dateProblem(error: unknown): string {
  if (error instanceof DateError) {
    const base = DATE_ERRORS[error.code] ?? 'Not a valid date'
    return error.code === 'invalid_date' && error.level !== null ? `${base} (${error.level})` : base
  }
  throw error
}

function levelLabel(calendar: CompiledCalendar, id: string): string {
  return calendar.definition.levels.find((level) => level.id === id)?.label ?? id
}

function regimeChoices(calendar: CompiledCalendar): { id: string; name: string }[] {
  return calendar.definition.regimes.map((regime) => ({ id: regime.id, name: regime.name }))
}

/** Levels top first. */
function coarseToFine(calendar: CompiledCalendar): string[] {
  return [...calendar.levels].reverse()
}

function inputOf(found: ReturnType<typeof unitOptions>): LevelInput {
  const choices: { value: string; label: string }[] = []
  for (const option of found) {
    if (option.kind === 'slot') {
      choices.push({
        value: option.slotId,
        label: `${option.name ?? option.slotId}${option.intercalary ? ' (intercalary)' : ''}`,
      })
      continue
    }
    if (option.first === null || option.last === null || option.last - option.first >= MAX_LISTED) {
      return { kind: 'number', first: option.first, last: option.last }
    }
    for (let n = option.first; n <= option.last; n++) {
      choices.push({ value: n.toString(), label: n.toString() })
    }
  }
  return { kind: 'choices', choices }
}

/**
 * Works out the levels to show (coarse to fine, down to the precision), each one's valid
 * choices given its parents (`options()`, so an odd year offers its own months), and the time
 * point when the whole date is valid. A picked unit that its parents no longer allow falls back
 * to the first valid one.
 */
function resolve(draft: Draft, calendar: CompiledCalendar | null): Resolved {
  const empty: Resolved = { levels: [], point: null, t: null, error: null, regimes: [] }
  if (calendar === null || draft.calendarId === null) return empty
  const order = coarseToFine(calendar)
  const precision = draft.precision ?? order.at(-1) ?? null
  if (precision === null) return empty
  const shown = order.slice(0, order.indexOf(precision) + 1)
  const era = draft.era === null ? null : (calendar.eras.find((e) => e.id === draft.era) ?? null)
  const levels: LevelView[] = []
  /** Parents for `options()`: the top level as an astronomical year. */
  const astronomical: Record<string, string> = {}
  const fields: Record<string, string> = {}
  let error: string | null = null
  for (const [index, id] of shown.entries()) {
    const label = levelLabel(calendar, id)
    if (index === 0) {
      const typed = draft.fields[id] ?? null
      levels.push({ id, label, input: { kind: 'number', first: null, last: null }, value: typed })
      if (typed === null) break
      fields[id] = typed
      astronomical[id] = era === null ? typed : era.year(BigInt(typed)).toString()
      continue
    }
    let found
    try {
      found = unitOptions(calendar, astronomical, id, { regime: draft.regime })
    } catch (problem) {
      error = dateProblem(problem)
      break
    }
    const input = inputOf(found)
    let value = draft.fields[id] ?? null
    if (input.kind === 'choices') {
      if (value === null || !input.choices.some((choice) => choice.value === value)) {
        value = input.choices[0]?.value ?? null
      }
    }
    levels.push({ id, label, input, value })
    if (value === null) break
    fields[id] = value
    astronomical[id] = value
  }
  const complete = levels.length === shown.length && levels.every((level) => level.value !== null)
  const regimes =
    error === DATE_ERRORS.reform_ambiguous || draft.regime !== null ? regimeChoices(calendar) : []
  if (!complete || error !== null) return { levels, point: null, t: null, error, regimes }
  try {
    const t = fromFields(calendar, fields, precision, {
      era: draft.era,
      regime: draft.regime,
      overflow: 'reject',
    })
    const point: TimePoint = {
      anchor: {
        kind: 'calendar',
        calendar_id: draft.calendarId,
        fields,
        ...(draft.era === null ? {} : { era: draft.era }),
        ...(draft.regime === null ? {} : { regime: draft.regime }),
      },
      precision,
      approximate: draft.approximate,
    }
    return { levels, point, t, error: null, regimes }
  } catch (problem) {
    const message = dateProblem(problem)
    const choices = message === DATE_ERRORS.reform_ambiguous ? regimeChoices(calendar) : regimes
    return { levels, point: null, t: null, error: message, regimes: choices }
  }
}

function draftOf(value: TimePoint | null, lenses: readonly Lens[], fallback: string | null): Draft {
  const firstCalendar =
    lenses.find((lens) => lens.id === fallback && lens.calendar !== null) ??
    lenses.find((lens) => lens.calendar !== null)
  const base: Draft = {
    tab: 'date',
    calendarId: firstCalendar?.id ?? null,
    era: null,
    regime: null,
    precision: null,
    fields: {},
    approximate: value?.approximate === true,
    absolute: null,
    relative: relativeDraftOf(value),
    relativePoint: value?.anchor.kind === 'relative' ? value : null,
  }
  if (value === null) return firstCalendar === undefined ? { ...base, tab: 'absolute' } : base
  const anchor = value.anchor
  if (anchor.kind === 'absolute') return { ...base, tab: 'absolute', absolute: BigInt(anchor.t) }
  if (anchor.kind === 'relative') return { ...base, tab: 'relative' }
  const fields: Record<string, string> = {}
  for (const [level, field] of Object.entries(anchor.fields)) {
    if (field !== undefined) fields[level] = field
  }
  return {
    ...base,
    calendarId: anchor.calendar_id,
    era: anchor.era ?? null,
    regime: anchor.regime ?? null,
    precision: value.precision === 'base' ? null : value.precision,
    fields,
  }
}

function Row({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor: string
  children: ReactNode
}) {
  return (
    <>
      <label htmlFor={htmlFor} className="pt-2 text-sm text-muted-foreground">
        {label}
      </label>
      <div className="min-w-0">{children}</div>
    </>
  )
}

/**
 * The time point picker (frontend.md §8): **Date** (a calendar of the dimension, then its levels
 * from the top down to the precision, each offering what its parents allow, with era and circa)
 * and **Absolute** (base units within the dimension). Reports a time point only when it is a
 * valid date (`null` otherwise); calendar fields keep named units as slot ids. The preview shows
 * the moment and the date in the display calendar. With `vault` (authors), **Relative** anchors
 * a moment to another record's slot (`RelativeTab`).
 */
export function TimePointPicker({
  dimension,
  lenses,
  value,
  onChange,
  onConfirm,
  displayLens,
  vault,
  owner,
  label = 'Time',
}: {
  dimension: DimensionTime
  /** The dimension's display calendars (`lenses()`); Absolute is the last one. */
  lenses: readonly Lens[]
  value: TimePoint | null
  onChange: (value: TimePoint | null) => void
  /** Enter on a valid value. */
  onConfirm?: (value: TimePoint) => void
  /** Where the preview shows the date (default: the picked calendar). */
  displayLens?: Lens | null
  /** Enables the Relative tab (authors: it searches targets and resolves on the server). */
  vault?: string
  /** The slot this time point belongs to (a relative anchor to it would be a cycle). */
  owner?: SlotRef
  label?: string
}) {
  const relativeAllowed = vault !== undefined
  const [draft, setDraft] = useState(() => draftOf(value, lenses, dimension.defaultCalendarId))
  const id = useId()
  const calendars = lenses.filter((lens) => lens.calendar !== null)
  const lens = calendars.find((candidate) => candidate.id === draft.calendarId) ?? null
  const calendar = lens?.calendar ?? null
  const resolved = resolve(draft, calendar)
  const absoluteOk = draft.absolute !== null && draft.absolute <= dimension.duration
  const current: TimePoint | null =
    draft.tab === 'relative'
      ? draft.relativePoint
      : draft.tab === 'date'
        ? resolved.point
        : absoluteOk && draft.absolute !== null
          ? {
              anchor: { kind: 'absolute', t: formatMoment(draft.absolute) },
              precision: 'base',
              approximate: draft.approximate,
            }
          : null
  const t =
    draft.tab === 'relative'
      ? null
      : draft.tab === 'date'
        ? resolved.t
        : absoluteOk
          ? draft.absolute
          : null

  const update = (patch: Partial<Draft>) => {
    const next = { ...draft, ...patch }
    setDraft(next)
    if (next.tab === 'relative') {
      onChange(
        next.relativePoint === null
          ? null
          : { ...next.relativePoint, approximate: next.approximate },
      )
    } else if (next.tab === 'date') {
      const nextLens = calendars.find((candidate) => candidate.id === next.calendarId) ?? null
      onChange(resolve(next, nextLens?.calendar ?? null).point)
    } else {
      onChange(
        next.absolute !== null && next.absolute <= dimension.duration
          ? {
              anchor: { kind: 'absolute', t: formatMoment(next.absolute) },
              precision: 'base',
              approximate: next.approximate,
            }
          : null,
      )
    }
  }
  const setField = (level: string, field: string | null) => {
    const others = Object.entries(draft.fields).filter(([key]) => key !== level)
    update({ fields: Object.fromEntries(field === null ? others : [...others, [level, field]]) })
  }
  const confirm = () => {
    if (current !== null) onConfirm?.(current)
  }
  /** Enter on a select confirms (inputs confirm through `BigNumberInput`). */
  const confirmOnEnter = (event: KeyboardEvent<HTMLSelectElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      confirm()
    }
  }
  const preview = (() => {
    if (t === null) return null
    const shown = displayLens ?? lens ?? lenses.at(-1) ?? null
    const moment =
      current === null ? null : { t, precision: current.precision, approximate: draft.approximate }
    const date =
      shown === null || moment === null ? null : formatIn(shown, moment, dimension, lenses)
    return [date, formatAbsolute(t, dimension.baseUnit)].filter(Boolean).join(' · ')
  })()
  const order = calendar === null ? [] : coarseToFine(calendar)

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="text-sm font-medium">{label}</legend>
      <Tabs
        value={draft.tab}
        onValueChange={(tab) => {
          update({ tab: tab === 'absolute' || tab === 'relative' ? tab : 'date' })
        }}
      >
        <TabsList>
          <TabsTrigger value="date" disabled={calendars.length === 0}>
            Date
          </TabsTrigger>
          {relativeAllowed && <TabsTrigger value="relative">Relative</TabsTrigger>}
          <TabsTrigger value="absolute">Absolute</TabsTrigger>
        </TabsList>
        <TabsContent value="date">
          <div className="grid grid-cols-[8rem_1fr] items-start gap-x-3 gap-y-2">
            <Row label="Calendar" htmlFor={`${id}-calendar`}>
              <select
                id={`${id}-calendar`}
                className={SELECT_CLASS}
                onKeyDown={confirmOnEnter}
                value={draft.calendarId ?? ''}
                onChange={(event) => {
                  update({
                    calendarId: event.target.value,
                    era: null,
                    regime: null,
                    precision: null,
                    fields: {},
                  })
                }}
              >
                {calendars.map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.name}
                  </option>
                ))}
              </select>
            </Row>
            {calendar !== null && calendar.eras.length > 0 && (
              <Row label="Era" htmlFor={`${id}-era`}>
                <select
                  id={`${id}-era`}
                  className={SELECT_CLASS}
                  onKeyDown={confirmOnEnter}
                  value={draft.era ?? ''}
                  onChange={(event) => {
                    update({ era: event.target.value === '' ? null : event.target.value })
                  }}
                >
                  <option value="">None (astronomical years)</option>
                  {calendar.eras.map((era) => (
                    <option key={era.id} value={era.id}>
                      {era.name}
                      {era.abbr ? ` (${era.abbr})` : ''}
                    </option>
                  ))}
                </select>
              </Row>
            )}
            {calendar !== null && (
              <Row label="Precision" htmlFor={`${id}-precision`}>
                <select
                  id={`${id}-precision`}
                  className={SELECT_CLASS}
                  onKeyDown={confirmOnEnter}
                  value={draft.precision ?? order.at(-1) ?? ''}
                  onChange={(event) => {
                    update({ precision: event.target.value })
                  }}
                >
                  {order.map((level) => (
                    <option key={level} value={level}>
                      {levelLabel(calendar, level)}
                    </option>
                  ))}
                </select>
              </Row>
            )}
            {resolved.levels.map((level, index) => (
              <Row key={level.id} label={level.label} htmlFor={`${id}-${level.id}`}>
                {level.input.kind === 'choices' ? (
                  <select
                    id={`${id}-${level.id}`}
                    className={SELECT_CLASS}
                    onKeyDown={confirmOnEnter}
                    value={level.value ?? ''}
                    onChange={(event) => {
                      setField(level.id, event.target.value)
                    }}
                  >
                    {level.input.choices.map((choice) => (
                      <option key={choice.value} value={choice.value}>
                        {choice.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <BigNumberInput
                    id={`${id}-${level.id}`}
                    signed={index === 0 && draft.era === null}
                    value={level.value === null ? null : BigInt(level.value)}
                    {...(level.input.first === null ? {} : { min: level.input.first })}
                    {...(level.input.last === null ? {} : { max: level.input.last })}
                    onChange={(number) => {
                      setField(level.id, number === null ? null : number.toString())
                    }}
                    onConfirm={confirm}
                  />
                )}
              </Row>
            ))}
            {resolved.regimes.length > 0 && (
              <Row label="Calendar rules" htmlFor={`${id}-regime`}>
                <select
                  id={`${id}-regime`}
                  className={SELECT_CLASS}
                  onKeyDown={confirmOnEnter}
                  value={draft.regime ?? ''}
                  onChange={(event) => {
                    update({ regime: event.target.value === '' ? null : event.target.value })
                  }}
                >
                  <option value="">Automatic</option>
                  {resolved.regimes.map((regime) => (
                    <option key={regime.id} value={regime.id}>
                      {regime.name}
                    </option>
                  ))}
                </select>
              </Row>
            )}
          </div>
          {resolved.error !== null && (
            <p role="alert" className="mt-2 text-sm text-destructive">
              {resolved.error}
            </p>
          )}
        </TabsContent>
        {vault !== undefined && (
          <TabsContent value="relative">
            <RelativeTab
              vault={vault}
              dimension={dimension}
              lenses={lenses}
              draft={draft.relative}
              approximate={draft.approximate}
              owner={owner}
              onDraft={(relative) => {
                setDraft((previous) => ({ ...previous, relative }))
              }}
              onPoint={(relativePoint) => {
                setDraft((previous) => ({ ...previous, relativePoint }))
                if (draft.tab === 'relative') onChange(relativePoint)
              }}
            />
          </TabsContent>
        )}
        <TabsContent value="absolute">
          <div className="grid grid-cols-[8rem_1fr] items-start gap-x-3 gap-y-2">
            <Row label={`Moment (${dimension.baseUnit.plural})`} htmlFor={`${id}-absolute`}>
              <BigNumberInput
                id={`${id}-absolute`}
                value={draft.absolute}
                max={dimension.duration}
                boundsMessage={`After the end of time (${formatAbsolute(dimension.duration, dimension.baseUnit)})`}
                onChange={(absolute) => {
                  update({ absolute })
                }}
                onConfirm={confirm}
              />
            </Row>
          </div>
        </TabsContent>
      </Tabs>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={draft.approximate}
          onChange={(event) => {
            update({ approximate: event.target.checked })
          }}
        />
        Circa (approximate)
      </label>
      <p aria-live="polite" className="text-sm text-muted-foreground" data-testid="time-preview">
        {preview ?? ' '}
      </p>
    </fieldset>
  )
}
