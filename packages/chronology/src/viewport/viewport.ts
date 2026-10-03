/**
 * Timeline viewports (chronology-engine.md §12): which moments a timeline of `widthPx` pixels
 * shows. Moments stay `bigint`; the only floating-point values are pixels. A pixel position is
 * scaled to 1/1024 px (`round(x · 1024)`) before it meets a moment, and `toPx` converts a bigint
 * quotient to `number` as its last step.
 */
import { type BigRational, floorDiv } from '../numbers'

/** The moments `[start, start + span)` drawn across `widthPx` pixels. */
export interface Viewport {
  readonly start: bigint
  /** `> 0`, in base units. */
  readonly span: bigint
  readonly widthPx: number
}

/** The narrowest span (§12). */
export const MIN_SPAN = 10n
/** `toPx` clamps moments far off-screen to `±OFFSCREEN_PX`. */
export const OFFSCREEN_PX = 1e7
/** Sub-pixel resolution: pixels are scaled to 1/1024 px before meeting moments. */
const SUBPIXELS = 1024
const LIMIT = BigInt(OFFSCREEN_PX * SUBPIXELS)

/** Pixels in 1/1024 px. */
function scaled(px: number): bigint {
  if (!Number.isFinite(px)) throw new RangeError(`not a finite pixel value: ${px}`)
  return BigInt(Math.round(px * SUBPIXELS))
}

/** The viewport's width in 1/1024 px (`≥ 1`). */
function widthOf(v: Viewport): bigint {
  const width = scaled(v.widthPx)
  if (width <= 0n) throw new RangeError(`the viewport width must be positive: ${v.widthPx}`)
  return width
}

/** A viewport; `span` is raised to `MIN_SPAN`. */
export function viewport(start: bigint, span: bigint, widthPx: number): Viewport {
  const v = { start, span: span < MIN_SPAN ? MIN_SPAN : span, widthPx }
  widthOf(v)
  return v
}

/** The pixel position of `t` (0 at `start`), clamped to `±OFFSCREEN_PX` far off-screen. */
export function toPx(v: Viewport, t: bigint): number {
  const q = floorDiv((t - v.start) * widthOf(v), v.span)
  const clamped = q > LIMIT ? LIMIT : q < -LIMIT ? -LIMIT : q
  return Number(clamped) / SUBPIXELS
}

/** The moment at pixel `x`: the latest moment with `toPx ≤ x` (to 1/1024 px). */
export function fromPx(v: Viewport, x: number): bigint {
  return v.start + floorDiv(scaled(x) * v.span, widthOf(v))
}

/**
 * Zoom by `factor` (the new span is `span · factor`; below 1 zooms in) around pixel `x`: the
 * moment under `x` stays exactly under it. The span is kept at or above `MIN_SPAN`; `clamp`
 * applies the dimension's bounds.
 */
export function zoomAt(v: Viewport, x: number, factor: BigRational): Viewport {
  if (factor.num <= 0n || factor.den <= 0n) throw new RangeError('the zoom factor must be positive')
  const anchor = fromPx(v, x)
  let span = (v.span * factor.num) / factor.den
  if (span < MIN_SPAN) span = MIN_SPAN
  const start = anchor - floorDiv(scaled(x) * span, widthOf(v))
  return { ...v, start, span }
}

/** Move the viewport `dx` pixels later in time (content moves left); negative `dx` goes back. */
export function panBy(v: Viewport, dx: number): Viewport {
  return { ...v, start: v.start + floorDiv(scaled(dx) * v.span, widthOf(v)) }
}

/**
 * The viewport showing `[start, end]` centered, with `paddingPx` free on each side (ignored when
 * it leaves no room). An empty or short range gets `MIN_SPAN`.
 */
export function fit(v: Viewport, start: bigint, end: bigint, paddingPx = 0): Viewport {
  const width = widthOf(v)
  let padding = scaled(paddingPx)
  if (padding < 0n || width - 2n * padding <= 0n) padding = 0n
  const length = end > start ? end - start : 0n
  let span = -floorDiv(-length * width, width - 2n * padding) // ceiling
  if (span < MIN_SPAN) span = MIN_SPAN
  return { ...v, start: start + floorDiv(length - span, 2n), span }
}

/**
 * Keep the viewport within a dimension of duration `D`: the span within `[MIN_SPAN, D · 1.25]`
 * (keeping the center), and the view no further outside `[0, D]` than `marginOf(span, D)` on
 * either side, so the whole dimension fits with a margin and a zoomed-in view keeps at least half
 * its width inside the dimension.
 */
export function clamp(v: Viewport, D: bigint): Viewport {
  const most = (D * 5n) / 4n
  let span = v.span > most ? most : v.span
  if (span < MIN_SPAN) span = MIN_SPAN
  let start = v.start + floorDiv(v.span - span, 2n)
  const margin = marginOf(span, D)
  const low = -margin
  const high = D + margin - span
  if (start > high) start = high
  if (start < low) start = low
  return { ...v, start, span }
}

/** How far a view of `span` may extend outside `[0, D]` on either side: `min(D / 8, span / 2)`,
 * but at least half of what the span exceeds `D` by (so the widest view still fits). */
export function marginOf(span: bigint, D: bigint): bigint {
  const margin = D / 8n < span / 2n ? D / 8n : span / 2n
  const excess = (span - D + 1n) / 2n
  return excess > margin ? excess : margin
}
