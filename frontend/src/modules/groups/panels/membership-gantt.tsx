import { floorDiv } from '@lore/chronology'
import { toPx, viewport, type Viewport } from '@lore/chronology/viewport'
import { Link } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'

import { axisTicks, TimeAxis } from '@/core/timeline'
import { formatIn, useDisplayLens, type DimensionTime, type Lens } from '@/core/time'
import type { Membership } from '@/data'
import { cn } from '@/lib/utils'

const NAME_WIDTH = 160
const ROW_HEIGHT = 28

export interface Bar {
  id: string
  /** Pixels from the chart's left edge. */
  x1: number
  x2: number
  /** No start (end): the bar runs off the left (right) edge. */
  openStart: boolean
  openEnd: boolean
}

/**
 * The bars of memberships across `widthPx` pixels: the viewport covers every known bound (with a
 * margin) and open bounds run to the edges. `null` viewport: no membership has a bound, so every
 * bar spans the whole width.
 */
export function ganttBars(
  items: readonly Membership[],
  widthPx: number,
): { v: Viewport | null; bars: Bar[] } {
  const bounds = items.flatMap((item) =>
    [item.from_t, item.to_t].filter((t): t is bigint => t !== null),
  )
  let v: Viewport | null = null
  if (bounds.length > 0) {
    const lo = bounds.reduce((a, b) => (b < a ? b : a))
    const hi = bounds.reduce((a, b) => (b > a ? b : a))
    const margin = floorDiv(hi - lo, 20n) + 1n
    v = viewport(lo - margin, hi - lo + 2n * margin, widthPx)
  }
  const at = (t: bigint) => (v === null ? 0 : Math.min(Math.max(toPx(v, t), 0), widthPx))
  return {
    v,
    bars: items.map((item) => ({
      id: item.item.link.id,
      x1: item.from_t === null ? 0 : at(item.from_t),
      x2: item.to_t === null ? widthPx : at(item.to_t),
      openStart: item.from_t === null,
      openEnd: item.to_t === null,
    })),
  }
}

function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const element = ref.current
    if (element === null) return
    const measure = () => {
      if (element.clientWidth > 0) setWidth(element.clientWidth)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => {
      observer.disconnect()
    }
  }, [])
  return { ref, width }
}

function bound(
  t: bigint | null,
  lens: Lens | null,
  time: DimensionTime | null,
  lenses: readonly Lens[],
): string | null {
  if (t === null || lens === null || time === null) return null
  return formatIn(lens, { t, precision: 'base' }, time, lenses) ?? t.toString()
}

/**
 * The membership history as a Gantt chart: a bar per membership from the start to the end of its
 * validity, on the display calendar's time axis (`@lore/chronology` viewport and ticks). Open
 * bounds run off the edge.
 */
export function MembershipGantt({
  vault,
  dimensionId,
  items,
}: {
  vault: string
  dimensionId: string | null
  items: readonly Membership[]
}) {
  const { dimension: time, lens, lenses } = useDisplayLens(vault, dimensionId)
  const { ref, width } = useWidth(480)
  const chartWidth = Math.max(width - NAME_WIDTH, 120)
  const { v, bars } = ganttBars(items, chartWidth)
  const found = v !== null && lens !== null && time !== null
  return (
    <div ref={ref} className="flex flex-col gap-1">
      {v === null ? (
        <p className="text-sm text-muted-foreground">
          No membership has dates yet: each bar spans all time.
        </p>
      ) : (
        found && (
          <div style={{ marginLeft: NAME_WIDTH }}>
            <TimeAxis v={v} found={axisTicks(lens.calendar, v, time.baseUnit)} />
          </div>
        )
      )}
      <ul aria-label="Membership history" className="flex flex-col">
        {items.map((item, index) => {
          const bar = bars[index]
          if (bar === undefined) return null
          const from = bound(item.from_t, lens, time, lenses)
          const to = bound(item.to_t, lens, time, lenses)
          const span = `${from ?? 'always'} – ${to ?? 'ongoing'}`
          return (
            <li
              key={bar.id}
              data-testid="gantt-row"
              className="flex items-center"
              style={{ height: ROW_HEIGHT }}
            >
              <Link
                to="/v/$vault/e/$entity"
                params={{ vault, entity: item.item.other.id }}
                className="truncate pr-2 text-sm text-primary underline-offset-2 hover:underline"
                style={{ width: NAME_WIDTH }}
              >
                {item.item.other.name}
              </Link>
              <svg width={chartWidth} height={ROW_HEIGHT} aria-hidden className="shrink-0">
                <rect
                  data-testid="gantt-bar"
                  data-open-start={bar.openStart}
                  data-open-end={bar.openEnd}
                  x={bar.x1}
                  y={6}
                  width={Math.max(bar.x2 - bar.x1, 2)}
                  height={ROW_HEIGHT - 12}
                  rx={3}
                  className={cn(
                    'fill-primary/60',
                    (bar.openStart || bar.openEnd) && 'fill-primary/30',
                  )}
                />
              </svg>
              <span className="sr-only">{span}</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
