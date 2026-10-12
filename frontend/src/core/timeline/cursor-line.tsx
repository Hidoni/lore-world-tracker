import { floorDiv, unitBounds, type CompiledCalendar } from '@lore/chronology'
import { fromPx, toPx, type Viewport } from '@lore/chronology/viewport'
import { useState, type KeyboardEvent, type PointerEvent } from 'react'

import { cn } from '@/lib/utils'

import { capture, release } from './pointer'

/**
 * Snapping to the axis' minor tick unit: a calendar level's units (`unitBounds`), or multiples of
 * a step of base units.
 */
export class TickSnap {
  constructor(
    private readonly calendar: CompiledCalendar | null,
    private readonly level: string,
    private readonly step: bigint,
    private readonly D: bigint,
  ) {}

  private bounds(t: bigint): { start: bigint; end: bigint } | null {
    if (this.calendar === null || this.level === 'base') return null
    try {
      return unitBounds(this.calendar, t, this.level)
    } catch {
      return null
    }
  }

  private clamp(t: bigint): bigint {
    return t < 0n ? 0n : t > this.D ? this.D : t
  }

  /** The unit boundary nearest `t`. */
  snap(t: bigint): bigint {
    const bounds = this.bounds(t)
    if (bounds !== null) {
      return this.clamp(t - bounds.start <= bounds.end - t ? bounds.start : bounds.end)
    }
    const step = this.step > 0n ? this.step : 1n
    return this.clamp(floorDiv(t + step / 2n, step) * step)
  }

  /** The unit boundary after (`+1`) or before (`−1`) `t`. */
  next(t: bigint, direction: 1 | -1): bigint {
    const bounds = this.bounds(direction === 1 ? t : t - 1n)
    if (bounds !== null) return this.clamp(direction === 1 ? bounds.end : bounds.start)
    const step = this.step > 0n ? this.step : 1n
    const snapped = floorDiv(t, step) * step
    return this.clamp(direction === 1 ? snapped + step : snapped === t ? t - step : snapped)
  }
}

/**
 * The time cursor on the timeline (frontend.md §9.1, time-model.md §10.6): a line at the as-of
 * moment with a handle that drags it (snapping to the axis' minor unit) or moves it with ←/→,
 * setting the cursor when let go; and a marker at the dimension's present.
 */
export function CursorLine({
  v,
  moment,
  present,
  snap,
  format,
  onChange,
}: {
  v: Viewport
  /** The cursor's moment (`null`: all time). */
  moment: bigint | null
  present: bigint | null
  snap: TickSnap
  format: (t: bigint) => string
  onChange: (t: bigint) => void
}) {
  const [dragged, setDragged] = useState<bigint | null>(null)
  const at = dragged ?? moment
  const shown = (t: bigint | null): t is bigint =>
    t !== null && t >= v.start && t <= v.start + v.span

  const follow = (event: PointerEvent<HTMLElement>) => {
    const box = event.currentTarget.closest('[data-cursor-layer]')?.getBoundingClientRect()
    if (box === undefined) return
    setDragged(snap.snap(fromPx(v, event.clientX - box.left)))
  }
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (at === null) return
    const direction = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : null
    if (direction === null) return
    event.preventDefault()
    // The timeline's own keys pan: these move the cursor.
    event.stopPropagation()
    onChange(snap.next(at, direction))
  }

  return (
    <div data-cursor-layer className="pointer-events-none absolute inset-0 overflow-hidden">
      {shown(present) && (
        <div
          data-testid="present-marker"
          title={`Present: ${format(present)}`}
          className="absolute inset-y-0 w-0 border-l border-dashed border-amber-500"
          style={{ transform: `translateX(${toPx(v, present)}px)` }}
        >
          <span className="absolute bottom-0 left-1 text-[10px] text-amber-600">Now</span>
        </div>
      )}
      {shown(at) && (
        <div
          data-testid="cursor-line"
          data-t={at.toString()}
          className="absolute inset-y-0 w-0 border-l-2 border-sky-500"
          style={{ transform: `translateX(${toPx(v, at) - 1}px)` }}
        >
          <span
            role="slider"
            aria-label="Time cursor"
            aria-valuetext={format(at)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round((toPx(v, at) / Math.max(1, v.widthPx)) * 100)}
            tabIndex={0}
            title={format(at)}
            className={cn(
              'pointer-events-auto absolute top-0 -left-[7px] size-3 cursor-ew-resize rounded-full bg-sky-500 outline-none',
              'focus-visible:ring-2 focus-visible:ring-ring',
              dragged !== null && 'ring-2 ring-sky-300',
            )}
            onKeyDown={onKeyDown}
            onPointerDown={(event) => {
              // Dragging the cursor doesn't pan.
              event.stopPropagation()
              capture(event.currentTarget, event.pointerId)
              setDragged(at)
            }}
            onPointerMove={(event) => {
              if (dragged !== null) follow(event)
            }}
            onPointerUp={(event) => {
              release(event.currentTarget, event.pointerId)
              if (dragged !== null && dragged !== moment) onChange(dragged)
              setDragged(null)
            }}
          />
        </div>
      )}
    </div>
  )
}
