import { formatAbsolute } from '@lore/chronology'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

import { formatIn, formatSpanIn, relativeToPresent, type Moment } from './format'
import { useDisplayLens } from './time-context'

/**
 * A moment of a dimension in the display calendar (frontend.md §8): at its precision (or the
 * nearest level the calendar has), with circa when approximate. The tooltip lists it in every
 * calendar of the dimension, the absolute value and how far it is from the present.
 */
export function MomentDisplay({
  vault,
  dimension,
  moment,
}: {
  vault: string
  /** The moment's dimension. */
  dimension: string
  moment: Moment
}) {
  const { dimension: time, lenses, lens } = useDisplayLens(vault, dimension)
  if (time === null || lens === null) return <span className="text-muted-foreground">…</span>
  const shown = formatIn(lens, moment, time, lenses) ?? formatAbsolute(moment.t, time.baseUnit)
  const relative = relativeToPresent(
    lens.calendar === null ? (lenses[0] ?? lens) : lens,
    moment.t,
    time.present,
  )
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="cursor-default rounded-sm text-left underline decoration-dotted underline-offset-4 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {shown}
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-sm">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          {lenses.map((candidate) => (
            <div key={candidate.id} className="contents">
              <dt className="opacity-70">{candidate.name}</dt>
              <dd>{formatIn(candidate, moment, time, lenses) ?? '—'}</dd>
            </div>
          ))}
        </dl>
        {relative !== null && <p className="mt-1 opacity-70">{relative}</p>}
      </TooltipContent>
    </Tooltip>
  )
}

/** A span in the display calendar (`formatSpan`: shared coarse parts collapse; open end `?`). */
export function SpanDisplay({
  vault,
  dimension,
  start,
  end,
}: {
  vault: string
  dimension: string
  start: Moment | null
  end: Moment | null
}) {
  const { dimension: time, lenses, lens } = useDisplayLens(vault, dimension)
  if (time === null || lens === null) return <span className="text-muted-foreground">…</span>
  return <span>{formatSpanIn(lens, start, end, time, lenses) ?? '—'}</span>
}
