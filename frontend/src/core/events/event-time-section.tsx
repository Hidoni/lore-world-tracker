import type { EndSpec, TimePoint } from '@lore/chronology'
import { formatAbsolute } from '@lore/chronology'
import { Link } from '@tanstack/react-router'
import { PencilIcon } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  durationSign,
  formatDuration,
  formatDurationIn,
  relativeTo,
  formatIn,
  timeProblemMessage,
  useDisplayLens,
  type DimensionTime,
  type Lens,
  type Moment,
} from '@/core/time'
import { useEntity, useTimelines, type Entity } from '@/data'

import { EventDialog } from './event-dialog'
import { eventTime, IMPORTANCE, type EventTime } from './event-time'
import { OccurrenceRefLabel } from './recurrence/lazy'

const SLOT_VERBS: Record<string, [string, string]> = {
  // [the moment itself, after/before it]
  start: ['starts', 'start of'],
  end: ['ends', 'end of'],
  branch_point: ['branches off', 'branch point of'],
}

/** The record a relative anchor points at, linked when it is an entity the request sees. */
function Target({ vault, type, id }: { vault: string; type: string; id: string }) {
  const entity = useEntity(vault, id, {}, { enabled: type === 'event' || type === 'timeline' })
  if (entity.data === undefined) {
    return <span className="text-muted-foreground">{entity.isError ? 'a hidden record' : '…'}</span>
  }
  return (
    <Link
      to="/v/$vault/e/$entity"
      params={{ vault, entity: entity.data.id }}
      className="font-medium underline-offset-2 hover:underline"
    >
      {entity.data.name}
    </Link>
  )
}

/**
 * How a time point was given, in words (frontend.md §7): typed in a calendar, a fixed moment, or
 * "3 days after <Assassination> ends" with the target linked.
 */
export function AnchorText({
  vault,
  point,
  dimension,
  lenses,
}: {
  vault: string
  point: TimePoint
  dimension: DimensionTime
  lenses: readonly Lens[]
}) {
  const anchor = point.anchor
  const circa = point.approximate === true ? ' (circa)' : ''
  if (anchor.kind === 'absolute') {
    return (
      <span>
        A fixed moment, {formatAbsolute(BigInt(anchor.t), dimension.baseUnit)}
        {circa}.
      </span>
    )
  }
  if (anchor.kind === 'calendar') {
    const calendar = lenses.find((lens) => lens.id === anchor.calendar_id)
    return (
      <span>
        Typed in {calendar?.name ?? 'a calendar'}
        {circa}.
      </span>
    )
  }
  const { ref, offset } = anchor
  const [moment, of] = SLOT_VERBS[ref.slot] ?? [ref.slot, `${ref.slot} of`]
  const amount = formatDuration(offset, dimension, lenses)
  // An occurrence of a series is named the way its page is: "the 3rd occurrence of …" (#287).
  const occurrence =
    ref.occurrence == null ? null : (
      <>
        <OccurrenceRefLabel vault={vault} seriesId={ref.id} occurrenceKey={ref.occurrence} />{' '}
      </>
    )
  const target = <Target vault={vault} type={ref.type} id={ref.id} />
  if (amount === '') {
    return (
      <span>
        When {occurrence}
        {target} {moment}
        {circa}.
      </span>
    )
  }
  return (
    <span>
      {amount} {durationSign(offset) === 1 ? 'after' : 'before'} the {of} {occurrence}
      {target}
      {circa}.
    </span>
  )
}

/** The end spec in words (the end's own moment is shown beside it). */
function EndText({
  vault,
  end,
  dimension,
  lenses,
}: {
  vault: string
  end: EndSpec
  dimension: DimensionTime
  lenses: readonly Lens[]
}) {
  switch (end.kind) {
    case 'time_point':
      return (
        <AnchorText vault={vault} point={end.time_point} dimension={dimension} lenses={lenses} />
      )
    case 'duration':
      return <span>Lasts {formatDuration(end.duration, dimension, lenses)}.</span>
    case 'instant':
      return <span>An instant.</span>
    case 'end_of_time':
      return <span>Lasts until the end of time.</span>
    default:
      return <span>The end is unknown.</span>
  }
}

/** The moments to show for an event: its start, and its end at the precision it was given. */
export function eventMoments(time: EventTime): { start: Moment | null; end: Moment | null } {
  const point = time.start
  const start =
    time.startT === null || point === null
      ? null
      : { t: time.startT, precision: point.precision, approximate: point.approximate === true }
  if (time.endT === null || start === null || time.end?.kind === 'unknown') {
    return { start, end: null }
  }
  const endPoint = time.end?.kind === 'time_point' ? time.end.time_point : null
  return {
    start,
    end: {
      t: time.endT,
      precision: endPoint?.precision ?? start.precision,
      approximate: endPoint?.approximate === true || start.approximate,
    },
  }
}

interface TimelineNode {
  id: string
  name: string
  is_prime: boolean
  children: readonly TimelineNode[]
}

function findTimeline(nodes: readonly TimelineNode[], id: string): TimelineNode | null {
  for (const node of nodes) {
    if (node.id === id) return node
    const inner = findTimeline(node.children, id)
    if (inner !== null) return inner
  }
  return null
}

function TimelineBadge({
  vault,
  dimensionId,
  timelineId,
}: {
  vault: string
  dimensionId: string | null
  timelineId: string
}) {
  const timelines = useTimelines(vault, dimensionId)
  const node = findTimeline(timelines.data?.items ?? [], timelineId)
  if (node === null) return null
  return (
    <Badge variant={node.is_prime ? 'secondary' : 'default'}>
      {node.is_prime ? node.name : `Branch: ${node.name}`}
    </Badge>
  )
}

/**
 * The time section of an event page (frontend.md §7, R-EVT-6): start and end with how each was
 * given (anchors explained and linked), the duration, the dates in **every** calendar of the
 * dimension, the timeline (a badge for branches), importance and category, and Edit.
 */
export function EventTimeSection({
  vault,
  entity,
  editable,
}: {
  vault: string
  entity: Entity
  editable: boolean
}) {
  const time = eventTime(entity)
  const { dimension, lenses, lens } = useDisplayLens(vault, entity.dimension_id)
  const [editing, setEditing] = useState(false)
  const parent = useEntity(
    vault,
    entity.parent_id ?? '',
    {},
    { enabled: entity.parent_id !== null },
  )
  if (dimension === null || lens === null) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }
  const { start, end } = eventMoments(time)
  const shown = (moment: Moment | null, fallback: string) =>
    moment === null
      ? fallback
      : (formatIn(lens, moment, dimension, lenses) ?? formatAbsolute(moment.t, dimension.baseUnit))
  const unknownEnd = time.end?.kind === 'unknown'
  const duration =
    start === null || end === null ? null : formatDurationIn(lens, start, end.t, dimension, lenses)
  const measure = lens.calendar === null ? (lenses.find((c) => c.calendar !== null) ?? lens) : lens
  const ago =
    start === null || dimension.present === null
      ? null
      : relativeTo(measure, start.t, dimension.present, dimension)
  return (
    <div className="flex flex-col gap-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        {time.timelineId !== null && (
          <TimelineBadge
            vault={vault}
            dimensionId={entity.dimension_id}
            timelineId={time.timelineId}
          />
        )}
        <Badge variant="outline">
          Importance {time.importance} · {IMPORTANCE[time.importance] ?? ''}
        </Badge>
        {time.category !== null && <Badge variant="outline">{time.category}</Badge>}
        {time.recurring && <Badge variant="outline">Recurring</Badge>}
        <div className="flex-1" />
        {editable && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setEditing(true)
            }}
          >
            <PencilIcon aria-hidden /> Edit time
          </Button>
        )}
      </div>
      {time.status !== null && time.status !== 'ok' && (
        <p role="status" className="text-destructive">
          {timeProblemMessage(time.status, `This event’s time has a problem (${time.status}).`)}
        </p>
      )}
      <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-2">
        <dt className="text-muted-foreground">Start</dt>
        <dd className="flex flex-col">
          <span className="font-medium">
            {shown(start, 'Not set')}
            {ago !== null && (
              <span className="ml-1 font-normal text-muted-foreground">({ago})</span>
            )}
          </span>
          {time.start !== null && (
            <span className="text-xs text-muted-foreground">
              <AnchorText vault={vault} point={time.start} dimension={dimension} lenses={lenses} />
            </span>
          )}
        </dd>
        <dt className="text-muted-foreground">End</dt>
        <dd className="flex flex-col">
          <span className="font-medium">{unknownEnd ? 'Unknown' : shown(end, '—')}</span>
          {time.end !== null && (
            <span className="text-xs text-muted-foreground">
              <EndText vault={vault} end={time.end} dimension={dimension} lenses={lenses} />
            </span>
          )}
        </dd>
        <dt className="text-muted-foreground">Duration</dt>
        <dd>{unknownEnd ? 'Unknown' : (duration ?? '—')}</dd>
      </dl>
      <table aria-label="In every calendar" className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="py-1 pr-3 font-normal">Calendar</th>
            <th className="py-1 pr-3 font-normal">Start</th>
            <th className="py-1 font-normal">End</th>
          </tr>
        </thead>
        <tbody>
          {lenses.map((candidate) => (
            <tr key={candidate.id} className="border-t">
              <td className="py-1 pr-3">{candidate.name}</td>
              <td className="py-1 pr-3">
                {start === null ? '—' : (formatIn(candidate, start, dimension, lenses) ?? '—')}
              </td>
              <td className="py-1">
                {unknownEnd
                  ? '?'
                  : end === null
                    ? '—'
                    : (formatIn(candidate, end, dimension, lenses) ?? '—')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing && (
        <EventDialog
          mode="edit"
          vault={vault}
          entity={entity}
          parent={
            entity.parent_id !== null && parent.data?.kind === 'event'
              ? { id: parent.data.id, name: parent.data.name }
              : null
          }
          onClose={() => {
            setEditing(false)
          }}
        />
      )}
    </div>
  )
}
