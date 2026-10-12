import {
  add,
  BASE,
  formatAbsolute,
  unitBounds,
  type SlotRef,
  type TimePoint,
} from '@lore/chronology'
import { Link } from '@tanstack/react-router'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useEntity, type Entity } from '@/data'

import type { Lens } from './calendars'
import { formatIn, relativeToPresent } from './format'
import { pointMoment } from './point-moment'
import { useTimeContext } from './time-context'

/** The words a slot is described with ("when <the war> starts"). */
const SLOT_WORDS: Record<string, string> = { start: 'starts', end: 'ends' }

/** An event's moment for a slot (`start`, `end`), as its entity carries it (`bigint`). */
function slotMoment(entity: Entity | undefined, slot: string): bigint | null {
  if (entity?.kind !== 'event') return null
  const ext = entity.ext as Record<string, unknown>
  const value = slot === 'start' ? ext.start_t : slot === 'end' ? ext.end_t : null
  return typeof value === 'bigint' ? value : null
}

/** A relative anchor's offset added to `t` (calendar durations in their calendar). */
function offsetFrom(t: bigint, point: TimePoint, lenses: readonly Lens[]): bigint | null {
  if (point.anchor.kind !== 'relative') return t
  const offset = point.anchor.offset
  if (offset.kind === 'base') return t + BigInt(offset.units)
  const calendar = lenses.find((lens) => lens.id === offset.calendar_id)?.calendar ?? null
  if (calendar === null) return null
  try {
    return add(calendar, t, offset)
  } catch {
    return null
  }
}

/** The range "Show on timeline" opens: the moment's unit at its precision, with room around. */
function timelineRange(lens: Lens, t: bigint, precision: string): { from: bigint; to: bigint } {
  let lo = t
  let hi = t + 1n
  if (lens.calendar !== null && precision !== BASE && lens.calendar.levelIndex(precision) >= 0) {
    try {
      const bounds = unitBounds(lens.calendar, t, precision)
      lo = bounds.start
      hi = bounds.end
    } catch {
      // The moment itself.
    }
  }
  const pad = (hi - lo) * 2n + 10n
  return { from: lo - pad, to: hi + pad }
}

/**
 * An inline date of rich text (`timeRef`, frontend.md §6) shown in the **reader's** display
 * calendar: a time point (absolute and calendar dates resolve here; relative ones through the
 * event they name), or a slot of a record (`when the war starts`). Clicking it lists it in every
 * calendar of the dimension, how far it is from the present, and links to the timeline there.
 * A reference readers may not see shows as "a date".
 */
export function TimeRefView({
  vault,
  timePoint,
  slotRef,
  hidden = false,
}: {
  vault: string
  timePoint: TimePoint | null
  slotRef: SlotRef | null
  /** The reader may not see what it is relative to. */
  hidden?: boolean
}) {
  const context = useTimeContext(vault)
  const { dimension, lens, lenses } = context
  const target = slotRef ?? (timePoint?.anchor.kind === 'relative' ? timePoint.anchor.ref : null)
  const targetEntity = useEntity(
    vault,
    target?.id ?? '',
    {},
    {
      enabled: target !== null && target.type === 'event' && !hidden,
    },
  )
  const direct = timePoint === null ? null : pointMoment(timePoint, lenses)
  const fromTarget =
    target === null || target.occurrence != null ? null : slotMoment(targetEntity.data, target.slot)
  const t =
    direct ??
    (fromTarget === null
      ? null
      : timePoint === null
        ? fromTarget
        : offsetFrom(fromTarget, timePoint, lenses))
  const precision = timePoint?.precision ?? BASE
  const approximate = timePoint?.approximate ?? false

  const plain = (text: string) => (
    <span data-time-ref="" className="time-ref text-muted-foreground">
      {text}
    </span>
  )
  if (hidden) return plain('a date')
  if (t === null || dimension === null || lens === null) {
    if (target !== null && targetEntity.data !== undefined) {
      return plain(`when ${targetEntity.data.name} ${SLOT_WORDS[target.slot] ?? target.slot}`)
    }
    return plain(dimension === null ? '…' : 'a date')
  }
  const moment = { t, precision, approximate }
  const shown = formatIn(lens, moment, dimension, lenses) ?? formatAbsolute(t, dimension.baseUnit)
  const relative = relativeToPresent(
    lens.calendar === null ? (lenses[0] ?? lens) : lens,
    t,
    dimension.present,
  )
  const range = timelineRange(lens, t, precision)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-time-ref={t.toString()}
          className="time-ref cursor-pointer rounded-sm underline decoration-dotted underline-offset-4 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {shown}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-auto max-w-sm text-sm" aria-label={`The date ${shown}`}>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          {lenses.map((candidate) => (
            <div key={candidate.id} className="contents">
              <dt className="text-muted-foreground">{candidate.name}</dt>
              <dd>{formatIn(candidate, moment, dimension, lenses) ?? '—'}</dd>
            </div>
          ))}
        </dl>
        {target !== null && targetEntity.data !== undefined && (
          <p className="mt-1 text-xs text-muted-foreground">Relative to {targetEntity.data.name}</p>
        )}
        {relative !== null && <p className="mt-1 text-xs text-muted-foreground">{relative}</p>}
        <Link
          to="/v/$vault/d/$dimension/timeline"
          params={{ vault, dimension: dimension.id }}
          search={{ from: range.from.toString(), to: range.to.toString() }}
          className="mt-2 inline-block text-primary underline-offset-2 hover:underline"
        >
          Show on timeline
        </Link>
      </PopoverContent>
    </Popover>
  )
}
