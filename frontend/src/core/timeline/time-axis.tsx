import type { BaseUnit, CompiledCalendar } from '@lore/chronology'
import { ticks, toPx, type Ticks, type Viewport } from '@lore/chronology/viewport'

import { absoluteTicks } from './absolute-ticks'

export const AXIS_HEIGHT = 44

/** The ticks of the display calendar (Absolute: base units) for the viewport. */
export function axisTicks(
  calendar: CompiledCalendar | null,
  v: Viewport,
  baseUnit: BaseUnit,
): Ticks {
  if (calendar === null) return absoluteTicks(v, baseUnit)
  try {
    return ticks(calendar, v)
  } catch {
    // A view far outside the calendar's range: fall back to base units.
    return absoluteTicks(v, baseUnit)
  }
}

/**
 * The time axis (frontend.md §9.1): major ticks (labelled with the calendar's format at their
 * level) above the line, minor ticks with short labels below, from `@lore/chronology` `ticks()`
 * (regime-aware) or base units for the Absolute calendar.
 */
export function TimeAxis({ v, found }: { v: Viewport; found: Ticks }) {
  return (
    <svg
      role="img"
      aria-label="Time axis"
      width={v.widthPx}
      height={AXIS_HEIGHT}
      className="block text-muted-foreground select-none"
    >
      <line x1={0} x2={v.widthPx} y1={20} y2={20} className="stroke-border" />
      {found.major.map((tick) => {
        const x = toPx(v, tick.t)
        return (
          <g key={`M${tick.t}`} data-testid="major-tick" data-t={tick.t.toString()}>
            <line x1={x} x2={x} y1={4} y2={28} className="stroke-foreground/60" />
            <text x={x + 3} y={14} className="fill-foreground text-[11px] font-medium">
              {tick.label}
            </text>
          </g>
        )
      })}
      {found.minor.map((tick) => {
        const x = toPx(v, tick.t)
        return (
          <g key={`m${tick.t}`} data-testid="minor-tick" data-t={tick.t.toString()}>
            <line x1={x} x2={x} y1={20} y2={28} className="stroke-foreground/30" />
            <text x={x + 2} y={40} className="fill-muted-foreground text-[10px]">
              {tick.label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
