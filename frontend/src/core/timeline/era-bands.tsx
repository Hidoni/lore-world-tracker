import type { CompiledCalendar } from '@lore/chronology'
import { toPx, type Viewport } from '@lore/chronology/viewport'

export const ERA_HEIGHT = 18

/** An era over the view: where it is drawn, and its colour. */
export interface EraShape {
  id: string
  name: string
  abbr: string
  x0: number
  x1: number
  color: string
}

/** Era colours: hues around the circle, light enough for labels in either theme. */
function eraColor(index: number): string {
  return `oklch(0.72 0.11 ${(index * 67 + 40) % 360} / 0.3)`
}

/**
 * The display calendar's eras overlapping the view (chronology-engine.md §3.8): era 0 runs from
 * −∞ and the last to +∞, so they are clipped to the view.
 */
export function eraShapes(calendar: CompiledCalendar | null, v: Viewport): EraShape[] {
  if (calendar === null) return []
  const end = v.start + v.span
  return calendar.eras.flatMap((era, index) => {
    const from = era.start === null || era.start < v.start ? v.start : era.start
    const to = era.end === null || era.end > end ? end : era.end
    if (from >= to) return []
    return [
      {
        id: era.id,
        name: era.name,
        abbr: era.abbr,
        x0: toPx(v, from),
        x1: toPx(v, to),
        color: eraColor(index),
      },
    ]
  })
}

/** The eras of the display calendar (frontend.md §9.1): a strip of named, coloured bands. */
export function EraBands({ v, calendar }: { v: Viewport; calendar: CompiledCalendar | null }) {
  const shapes = eraShapes(calendar, v)
  if (shapes.length === 0) return null
  return (
    <div
      role="group"
      aria-label="Eras"
      className="relative overflow-hidden select-none"
      style={{ width: v.widthPx, height: ERA_HEIGHT }}
    >
      {shapes.map((era) => (
        <div
          key={era.id}
          data-testid="era-band"
          title={`${era.name} (${era.abbr})`}
          className="absolute top-0 flex h-full items-center overflow-hidden border-x border-background px-1 text-[11px] whitespace-nowrap text-foreground"
          style={{
            transform: `translateX(${era.x0}px)`,
            width: Math.max(1, era.x1 - era.x0),
            background: era.color,
          }}
        >
          {era.name}
        </div>
      ))}
    </div>
  )
}
