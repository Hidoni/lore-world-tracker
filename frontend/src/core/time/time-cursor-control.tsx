import { add, formatMoment, type TimePoint } from '@lore/chronology'
import { ChevronLeftIcon, ChevronRightIcon, ClockIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useEntity } from '@/data'

import type { DimensionTime, Lens } from './calendars'
import { formatIn } from './format'
import { pointMoment } from './point-moment'
import { useTimeContext, type TimeContext } from './time-context'
import { TimePointPicker } from './time-point-picker'

const BASE_STEP = 'base'

/** The levels a lens can step by (coarse first), or the base unit for the Absolute calendar. */
function stepLevels(lens: Lens | null): { id: string; label: string }[] {
  const calendar = lens?.calendar ?? null
  if (calendar === null) return [{ id: BASE_STEP, label: 'Base unit' }]
  const labels = new Map(calendar.definition.levels.map((level) => [level.id, level.label]))
  return [...calendar.levels].reverse().map((id) => ({ id, label: labels.get(id) ?? id }))
}

/**
 * `t` moved one unit of `level` of the lens (base units for Absolute), kept inside the
 * dimension (`null` when the calendar can't step there).
 */
export function stepMoment(
  lens: Lens | null,
  dimension: DimensionTime,
  t: bigint,
  level: string,
  sign: 1 | -1,
): bigint | null {
  let next: bigint
  try {
    next =
      lens?.calendar == null || level === BASE_STEP
        ? t + BigInt(sign)
        : add(lens.calendar, t, {
            kind: 'calendar',
            calendar_id: lens.id,
            amounts: { [level]: '1' },
            sign,
          })
  } catch {
    return null
  }
  if (next < 0n) return 0n
  return next > dimension.duration ? dimension.duration : next
}

/** What the cursor shows: Present, All time, or the moment in the display calendar. */
export function cursorLabel(context: TimeContext): string {
  if (context.cursor === 'all') return 'All time'
  if (context.cursor === 'present') return 'Present'
  if (context.dimension === null || context.lens === null) return formatMoment(context.cursor)
  const moment = { t: context.cursor, precision: 'base' }
  const shown = formatIn(context.lens, moment, context.dimension, context.lenses)
  return shown ?? formatMoment(context.cursor)
}

/**
 * The top bar's time cursor (frontend.md §3, §8; time-model.md §10.6): Present, All time, a
 * picked moment, and steps of one unit of a display-calendar level. Every choice goes to the URL
 * (`at`) and is remembered per vault and dimension.
 */
export function TimeCursorControl({ vault }: { vault: string }) {
  const context = useTimeContext(vault)
  const [open, setOpen] = useState(false)
  const [point, setPoint] = useState<TimePoint | null>(null)
  const levels = stepLevels(context.lens)
  const [chosenLevel, setLevel] = useState<string | null>(null)
  const level = levels.find((item) => item.id === chosenLevel) ?? levels[0]
  const dimension = context.dimension
  if (dimension === null) return null
  const label = cursorLabel(context)

  const step = (sign: 1 | -1): void => {
    if (context.moment === null || level === undefined) return
    const next = stepMoment(context.lens, dimension, context.moment, level.id, sign)
    if (next !== null) context.setCursor(next)
  }
  const go = (value: TimePoint | null): void => {
    const t = value === null ? null : pointMoment(value, context.lenses)
    if (t === null) return
    context.setCursor(t)
    setOpen(false)
  }
  const stepping = context.moment !== null && level !== undefined

  return (
    <div className="flex items-center" role="group" aria-label="Time cursor">
      {stepping && (
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label={`One ${level.label.toLowerCase()} earlier`}
          onClick={() => {
            step(-1)
          }}
        >
          <ChevronLeftIcon />
        </Button>
      )}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="sm" aria-label={`Time cursor: ${label}`}>
            <ClockIcon aria-hidden />
            <span className="max-w-48 truncate">{label}</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[26rem] space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant={context.cursor === 'present' ? 'default' : 'outline'}
              disabled={dimension.present === null}
              title={dimension.present === null ? 'The dimension has no present moment' : undefined}
              onClick={() => {
                context.setCursor('present')
                setOpen(false)
              }}
            >
              Present
            </Button>
            <Button
              size="sm"
              variant={context.cursor === 'all' ? 'default' : 'outline'}
              onClick={() => {
                context.setCursor('all')
                setOpen(false)
              }}
            >
              All time
            </Button>
          </div>
          {levels.length > 1 && (
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Step by</span>
              <select
                className="rounded-md border bg-background px-2 py-1"
                value={level?.id}
                onChange={(event) => {
                  setLevel(event.target.value)
                }}
              >
                {levels.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <TimePointPicker
            dimension={dimension}
            lenses={context.lenses}
            value={point}
            onChange={setPoint}
            onConfirm={go}
            displayLens={context.lens}
            label="Moment"
          />
          <div className="flex justify-end">
            <Button
              size="sm"
              disabled={point === null || pointMoment(point, context.lenses) === null}
              onClick={() => {
                go(point)
              }}
            >
              Go to this moment
            </Button>
          </div>
        </PopoverContent>
      </Popover>
      {stepping && (
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label={`One ${level.label.toLowerCase()} later`}
          onClick={() => {
            step(1)
          }}
        >
          <ChevronRightIcon />
        </Button>
      )}
    </div>
  )
}

/**
 * The time cursor as API parameters (`timeline`, `at`): `undefined` for all time (or without a
 * present moment to stand for "present"), so reads show everything.
 */
export function useAsOf(vault: string): { timeline: string; at: string } | undefined {
  const context = useTimeContext(vault)
  if (context.moment === null || context.timelineId === null) return undefined
  return { timeline: context.timelineId, at: formatMoment(context.moment) }
}

/**
 * The time cursor for an entity's reads (its state, links, module panels): `undefined` in
 * all-time mode, and for entities of another dimension than the context's (the cursor's moment
 * belongs to the current dimension).
 */
export function useEntityAsOf(
  vault: string,
  entityId: string,
): { timeline: string; at: string } | undefined {
  const asOf = useAsOf(vault)
  const context = useTimeContext(vault)
  const entity = useEntity(vault, entityId, {}, { enabled: asOf !== undefined })
  if (asOf === undefined || entity.data === undefined) return undefined
  const dimension = entity.data.dimension_id
  return dimension === null || dimension === context.dimensionId ? asOf : undefined
}
