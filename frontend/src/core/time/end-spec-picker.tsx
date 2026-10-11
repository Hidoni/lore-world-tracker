import type { Duration, EndSpec, SlotRef, TimePoint } from '@lore/chronology'
import { useEffect, useId, useState } from 'react'

import { useTimeResolution } from '@/data'

import type { DimensionTime, Lens } from './calendars'
import { DurationPicker } from './duration-picker'
import { wire, wireEnd } from './relative-tab'
import { SELECT_CLASS } from './select'
import { TimePointPicker } from './time-point-picker'
import { timeProblemMessage } from './time-problems'

type EndKind = EndSpec['kind']

const KINDS: { kind: EndKind; label: string }[] = [
  { kind: 'time_point', label: 'An end date' },
  { kind: 'duration', label: 'A duration' },
  { kind: 'instant', label: 'Instant (no duration)' },
  { kind: 'end_of_time', label: 'Until the end of time' },
  { kind: 'unknown', label: 'Unknown' },
]

interface Draft {
  kind: EndKind
  point: TimePoint | null
  duration: Duration | null
}

function draftOf(value: EndSpec | null): Draft {
  if (value === null) return { kind: 'time_point', point: null, duration: null }
  if (value.kind === 'time_point')
    return { kind: value.kind, point: value.time_point, duration: null }
  if (value.kind === 'duration') return { kind: value.kind, point: null, duration: value.duration }
  return { kind: value.kind, point: null, duration: null }
}

function endsBeforeStart(start: bigint | null, end: bigint | null): boolean {
  return start !== null && end !== null && end < start
}

function specOf(draft: Draft): EndSpec | null {
  switch (draft.kind) {
    case 'time_point':
      return draft.point === null ? null : { kind: 'time_point', time_point: draft.point }
    case 'duration':
      return draft.duration === null ? null : { kind: 'duration', duration: draft.duration }
    default:
      return { kind: draft.kind }
  }
}

/**
 * An event's end (time-model.md §5.5): an end date (a `TimePointPicker`), a duration from the
 * start, an instant, the end of time, or unknown. With a `start`, the server resolves both and an
 * end before the start is refused (`null` reported) with the reason shown.
 */
export function EndSpecPicker({
  vault,
  dimension,
  lenses,
  start,
  value,
  onChange,
  owner,
  label = 'End',
}: {
  vault: string
  dimension: DimensionTime
  lenses: readonly Lens[]
  /** The start it is checked against (`null`: not set yet, nothing to check). */
  start: TimePoint | null
  value: EndSpec | null
  onChange: (value: EndSpec | null) => void
  /** The end slot being edited (a relative end anchored to it would be a cycle). */
  owner?: SlotRef
  label?: string
}) {
  const [draft, setDraft] = useState(() => draftOf(value))
  const id = useId()
  const spec = specOf(draft)
  const checked = start !== null && spec !== null
  const resolution = useTimeResolution(
    vault,
    start !== null && spec !== null
      ? { dimension_id: dimension.id, items: [{ time_point: wire(start), end: wireEnd(spec) }] }
      : null,
  )
  const item = resolution.isPlaceholderData ? undefined : resolution.data?.items[0]
  const end = item?.end ?? null
  const problem = !checked
    ? null
    : end?.error
      ? timeProblemMessage(end.error.code, end.error.message)
      : item !== undefined && endsBeforeStart(item.start.t, end?.t ?? null)
        ? 'The end comes before the start.'
        : null
  // Without a start there's nothing to check; with one, wait for the server's answer.
  const accepted = spec !== null && (!checked || (end !== null && problem === null))
  const reported = JSON.stringify(accepted ? spec : null)
  useEffect(() => {
    onChange(accepted ? spec : null)
    // `reported` stands for the reported spec (a new object each render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reported])

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="text-sm font-medium">{label}</legend>
      <select
        id={`${id}-kind`}
        aria-label={`${label} kind`}
        className={SELECT_CLASS}
        value={draft.kind}
        onChange={(event) => {
          const kind = KINDS.find((entry) => entry.kind === event.target.value)?.kind ?? 'unknown'
          setDraft({ ...draft, kind })
        }}
      >
        {KINDS.map((entry) => (
          <option key={entry.kind} value={entry.kind}>
            {entry.label}
          </option>
        ))}
      </select>
      {draft.kind === 'time_point' && (
        <TimePointPicker
          vault={vault}
          dimension={dimension}
          lenses={lenses}
          value={draft.point}
          label={`${label} date`}
          {...(owner === undefined ? {} : { owner })}
          onChange={(point) => {
            setDraft((previous) => ({ ...previous, point }))
          }}
        />
      )}
      {draft.kind === 'duration' && (
        <DurationPicker
          dimension={dimension}
          lenses={lenses}
          value={draft.duration}
          label={`${label} after the start`}
          onChange={(duration) => {
            setDraft((previous) => ({ ...previous, duration }))
          }}
        />
      )}
      {problem !== null ? (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      ) : (
        end?.display &&
        end.t !== null && (
          <p className="text-sm text-muted-foreground" data-testid="end-resolution">
            Ends {end.display}
          </p>
        )
      )}
    </fieldset>
  )
}
