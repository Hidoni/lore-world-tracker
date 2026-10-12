import { toPx, type Viewport } from '@lore/chronology/viewport'

import type { SeriesBand } from './use-timeline-window'

/** A band laid out against the lanes' anchor viewport. */
export interface BandShape {
  key: string
  band: SeriesBand
  x0: number
  x1: number
}

export function bandShapes(bands: readonly SeriesBand[], anchor: Viewport): BandShape[] {
  return bands.map((band) => ({
    key: `band:${band.row_id}`,
    band,
    x0: toPx(anchor, band.from),
    x1: toPx(anchor, band.to),
  }))
}

/**
 * A recurring series with too many occurrences in the window to list (recurrence.md §10): a
 * hatched band over the part of the window it covers, with its estimated count. Zoomed in until
 * the server lists them, its occurrences are drawn one by one instead.
 */
export function SeriesBandShape({
  shape,
  top,
  height,
  limit,
}: {
  shape: BandShape
  top: number
  height: number
  limit: { left: number; right: number }
}) {
  const { band, x0, x1 } = shape
  const left = Math.max(x0, limit.left)
  return (
    <div
      data-testid="series-band"
      title={`${band.name}: about ${band.estimated_count.toString()} occurrences`}
      className="absolute flex items-center overflow-hidden rounded-sm px-1 text-[11px] whitespace-nowrap text-foreground"
      style={{
        transform: `translate(${left}px, ${top}px)`,
        width: Math.max(4, Math.min(x1, limit.right) - left),
        height,
        background:
          'repeating-linear-gradient(135deg, color-mix(in oklab, var(--primary) 30%, transparent) 0 4px, transparent 4px 8px)',
      }}
    >
      {band.name} ×{band.estimated_count.toString()}
    </div>
  )
}
