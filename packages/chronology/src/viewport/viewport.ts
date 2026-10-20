/**
 * Timeline viewports (chronology-engine.md §12): which moments a timeline of `widthPx` pixels
 * shows. Moments stay `bigint`; the only floating-point values are pixels. A pixel position is
 * scaled to 1/1024 px (`round(x · 1024)`) before it meets a moment, and `toPx` converts a bigint
 * quotient to `number` as its last step.
 */
import { type BigRational, floorDiv } from '../numbers'

/**
 * A logarithmic axis (#153): pixel `x` shows the moment `origin + 10^e − 1`, with `e` going
 * linearly from `lo` at the left edge to `hi` at the right (decades of base units since
 * `origin`). The exponents are the axis's only floating-point state, next to pixels.
 */
export interface LogScale {
  readonly origin: bigint
  readonly lo: number
  readonly hi: number
}

/**
 * The moments `[start, start + span)` drawn across `widthPx` pixels. With `log`, the axis is
 * logarithmic and `start`/`span` are the range it covers (what reads of a window ask for).
 */
export interface Viewport {
  readonly start: bigint
  /** `> 0`, in base units. */
  readonly span: bigint
  readonly widthPx: number
  readonly log?: LogScale
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

/** The narrowest logarithmic view, in decades. */
export const MIN_DECADES = 0.01

/** `floor(10^e)` for `e ≥ 0`: exact below 10^15, then 16 significant digits. */
function pow10(e: number): bigint {
  if (e <= 0) return 1n
  if (e < 15) return BigInt(Math.floor(10 ** e))
  const k = Math.floor(e)
  const mantissa = 10 ** (e - k)
  return BigInt(Math.round(mantissa * 1e15)) * 10n ** BigInt(k - 15)
}

/** Decades since the origin: `log10(t − origin + 1)`, 0 for moments before it. */
function decades(log: LogScale, t: bigint): number {
  const elapsed = t - log.origin
  return log10((elapsed < 0n ? 0n : elapsed) + 1n)
}

/** The moment at decade `e` of a logarithmic axis. */
function atDecade(log: LogScale, e: number): bigint {
  return log.origin + pow10(e) - 1n
}

/**
 * A logarithmic viewport over decades `[lo, hi]` since `origin` (`lo ≥ 0`, at least
 * `MIN_DECADES` wide); `start`/`span` are the moments it covers.
 */
export function logViewport(origin: bigint, lo: number, hi: number, widthPx: number): Viewport {
  const low = Math.max(0, lo)
  const high = Math.max(hi - lo + low, low + MIN_DECADES)
  const log = { origin, lo: low, hi: high }
  const start = atDecade(log, low)
  const end = atDecade(log, high)
  const v = { start, span: end - start < MIN_SPAN ? MIN_SPAN : end - start, widthPx, log }
  widthOf(v)
  return v
}

/** The same range on a logarithmic axis counted from `origin` (the range's start moves to it
 * when it lies before). */
export function toLogScale(v: Viewport, origin = 0n): Viewport {
  if (v.log !== undefined) return v
  const scale = { origin, lo: 0, hi: 0 }
  return logViewport(origin, decades(scale, v.start), decades(scale, v.start + v.span), v.widthPx)
}

/** The same range on a linear axis. */
export function toLinear(v: Viewport): Viewport {
  return v.log === undefined ? v : viewport(v.start, v.span, v.widthPx)
}

function clampPx(px: number): number {
  const scaledPx = Math.round(px * SUBPIXELS)
  const limit = OFFSCREEN_PX * SUBPIXELS
  return (scaledPx > limit ? limit : scaledPx < -limit ? -limit : scaledPx) / SUBPIXELS
}

/** The pixel position of `t` (0 at `start`), clamped to `±OFFSCREEN_PX` far off-screen. */
export function toPx(v: Viewport, t: bigint): number {
  if (v.log !== undefined) {
    const { lo, hi } = v.log
    return clampPx(((decades(v.log, t) - lo) / (hi - lo)) * v.widthPx)
  }
  const q = floorDiv((t - v.start) * widthOf(v), v.span)
  const clamped = q > LIMIT ? LIMIT : q < -LIMIT ? -LIMIT : q
  return Number(clamped) / SUBPIXELS
}

/** `log10(n)` of a non-negative bigint, to double precision (its digits, not its value). */
function log10(n: bigint): number {
  const digits = n.toString()
  const head = digits.slice(0, 17)
  return digits.length - head.length + Math.log10(Number(head))
}

/**
 * The pixel position of `t` on a logarithmic axis over `[start, end]` (`widthPx` wide): moments
 * are offset by one, so 0 sits at the left of an axis starting at 0. Charts of moments spanning
 * many orders of magnitude (a correspondence's mapping) use it; timelines stay linear.
 */
export function toLogPx(start: bigint, end: bigint, widthPx: number, t: bigint): number {
  if (start < 0n || end <= start) throw new RangeError('a log axis needs 0 ≤ start < end')
  const clamped = t < start ? start : t > end ? end : t
  const lo = log10(start + 1n)
  return ((log10(clamped + 1n) - lo) / (log10(end + 1n) - lo)) * widthPx
}

/** The moment at pixel `x`: the latest moment with `toPx ≤ x` (to 1/1024 px). */
export function fromPx(v: Viewport, x: number): bigint {
  if (v.log !== undefined) {
    const { lo, hi } = v.log
    return atDecade(v.log, lo + (Number(scaled(x)) / Number(widthOf(v))) * (hi - lo))
  }
  return v.start + floorDiv(scaled(x) * v.span, widthOf(v))
}

/**
 * Zoom by `factor` (the new span is `span · factor`; below 1 zooms in) around pixel `x`: the
 * moment under `x` stays exactly under it. The span is kept at or above `MIN_SPAN`; `clamp`
 * applies the dimension's bounds.
 */
export function zoomAt(v: Viewport, x: number, factor: BigRational): Viewport {
  if (factor.num <= 0n || factor.den <= 0n) throw new RangeError('the zoom factor must be positive')
  if (v.log !== undefined) {
    // Decades scale like a span: the decade under `x` stays under it.
    const { origin, lo, hi } = v.log
    const share = Number(scaled(x)) / Number(widthOf(v))
    const under = lo + share * (hi - lo)
    const range = Math.max((hi - lo) * (Number(factor.num) / Number(factor.den)), MIN_DECADES)
    const low = under - share * range
    return logViewport(origin, low, low + range, v.widthPx)
  }
  const anchor = fromPx(v, x)
  let span = (v.span * factor.num) / factor.den
  if (span < MIN_SPAN) span = MIN_SPAN
  const start = anchor - floorDiv(scaled(x) * span, widthOf(v))
  return { ...v, start, span }
}

/** Move the viewport `dx` pixels later in time (content moves left); negative `dx` goes back. */
export function panBy(v: Viewport, dx: number): Viewport {
  if (v.log !== undefined) {
    const { origin, lo, hi } = v.log
    const shift = (Number(scaled(dx)) / Number(widthOf(v))) * (hi - lo)
    const low = Math.max(0, lo + shift)
    return logViewport(origin, low, low + hi - lo, v.widthPx)
  }
  return { ...v, start: v.start + floorDiv(scaled(dx) * v.span, widthOf(v)) }
}

/**
 * The viewport showing `[start, end]` centered, with `paddingPx` free on each side (ignored when
 * it leaves no room). An empty or short range gets `MIN_SPAN`.
 */
export function fit(v: Viewport, start: bigint, end: bigint, paddingPx = 0): Viewport {
  if (v.log !== undefined) {
    const low = decades(v.log, start)
    const high = Math.max(decades(v.log, end), low + MIN_DECADES)
    const share = paddingPx > 0 && 2 * paddingPx < v.widthPx ? paddingPx / v.widthPx : 0
    const range = (high - low) / (1 - 2 * share)
    return logViewport(v.log.origin, low - share * range, low - share * range + range, v.widthPx)
  }
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
  if (v.log !== undefined) {
    // Decades from 0 to the end of the dimension, with a 5% margin past it.
    const { origin, lo, hi } = v.log
    const top = decades(v.log, D > origin ? D : origin + 1n)
    const most = Math.max(top * 1.05, MIN_DECADES)
    const range = Math.min(hi - lo, most)
    const low = Math.min(Math.max(0, lo), Math.max(0, most - range))
    return logViewport(origin, low, low + range, v.widthPx)
  }
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

/** The view centered on `t`, keeping its span (or, on a log axis, its decades). */
export function centerOn(v: Viewport, t: bigint): Viewport {
  if (v.log !== undefined) {
    const { origin, lo, hi } = v.log
    const middle = decades(v.log, t)
    return logViewport(origin, middle - (hi - lo) / 2, middle + (hi - lo) / 2, v.widthPx)
  }
  return { ...v, start: t - v.span / 2n }
}
