import { fit, fromPx, toPx, viewport, type Viewport } from '@lore/chronology/viewport'
import { useRef } from 'react'

import { capture, release } from './pointer'

const HEIGHT = 28

/**
 * The whole dimension in a strip (frontend.md §9.1) with the viewport as a rectangle: dragging
 * the rectangle (or anywhere on the strip) moves the view, keeping its span. As a slider, ←/→ move
 * the view by its own span and Home/End go to the dimension's ends.
 */
export function Minimap({
  D,
  v,
  onCenter,
}: {
  D: bigint
  v: Viewport
  /** Center the view on this moment. */
  onCenter: (t: bigint) => void
}) {
  const whole = fit(viewport(0n, D > 0n ? D : 1n, v.widthPx), 0n, D)
  const dragging = useRef(false)
  const left = Math.max(0, toPx(whole, v.start))
  const right = Math.min(v.widthPx, toPx(whole, v.start + v.span))
  const at = (event: React.PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    onCenter(fromPx(whole, event.clientX - box.left))
  }
  return (
    <svg
      role="slider"
      aria-label="Minimap"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round((left / Math.max(1, v.widthPx)) * 100)}
      aria-valuetext={`${String(Math.round((left / Math.max(1, v.widthPx)) * 100))}% of the dimension`}
      tabIndex={0}
      width={v.widthPx}
      height={HEIGHT}
      className="block cursor-grab rounded-sm bg-muted/50 select-none focus-visible:outline-2 focus-visible:outline-ring active:cursor-grabbing"
      onKeyDown={(event) => {
        const center = v.start + v.span / 2n
        const moves: Record<string, bigint> = {
          ArrowLeft: center - v.span,
          ArrowRight: center + v.span,
          Home: v.span / 2n,
          End: D - v.span / 2n,
        }
        const to = moves[event.key]
        if (to === undefined) return
        event.preventDefault()
        onCenter(to < 0n ? 0n : to > D ? D : to)
      }}
      onPointerDown={(event) => {
        dragging.current = true
        capture(event.currentTarget, event.pointerId)
        at(event)
      }}
      onPointerMove={(event) => {
        if (dragging.current) at(event)
      }}
      onPointerUp={(event) => {
        dragging.current = false
        release(event.currentTarget, event.pointerId)
      }}
    >
      <line
        x1={toPx(whole, 0n)}
        x2={toPx(whole, D)}
        y1={HEIGHT / 2}
        y2={HEIGHT / 2}
        className="stroke-muted-foreground/40"
      />
      <rect
        data-testid="minimap-viewport"
        x={left}
        y={2}
        width={Math.max(2, right - left)}
        height={HEIGHT - 4}
        rx={3}
        className="fill-primary/15 stroke-primary"
      />
    </svg>
  )
}
