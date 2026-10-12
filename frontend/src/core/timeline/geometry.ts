import { BASE, unitBounds } from '@lore/chronology'
import { toPx, type Viewport } from '@lore/chronology/viewport'

import type { Lens } from '@/core/time'

/** What the geometry reads of a window item (moments as `bigint`). */
export interface TimedItem {
  start_t: bigint | null
  end_t: bigint | null
  start_precision: string
  start_approximate: boolean
  end_kind: string
  end_precision: string | null
  end_approximate: boolean
}

/** A drawn item: an instant (a diamond at `x0`) or a span from `x0` to `x1`. */
export interface ItemGeometry {
  kind: 'instant' | 'span'
  x0: number
  x1: number
  /** Pixels at the start fading in (the start's uncertainty, softened for circa). */
  fadeIn: number
  /** Pixels at the end fading out (the end's uncertainty, circa, or an open end). */
  fadeOut: number
  /** The end is unknown: the bar fades out after the start. */
  openEnd: boolean
}

/** Pixels a circa edge is softened by, at least. */
export const CIRCA_PX = 6
/** How far an unknown end fades out after the start. */
export const OPEN_END_PX = 72
/** Instants whose uncertainty is wider than this are drawn as a fuzzy span. */
const WIDE_INSTANT_PX = 8

/**
 * The moments a moment at `precision` may be (time-model.md §2.1): the unit of that level holding
 * `t` in the first calendar that has the level, else the moment itself.
 */
export function extentOf(
  t: bigint,
  precision: string,
  lenses: readonly Lens[],
): { lo: bigint; hi: bigint } {
  if (precision === BASE) return { lo: t, hi: t }
  // Extents don't change with the view: zooming lays the same items out again (frontend.md §12).
  const key = `${precision}:${t}`
  const cache = extents.get(lenses)
  const known = cache?.get(key)
  if (known !== undefined) return known
  const found = computeExtent(t, precision, lenses)
  if (cache === undefined) extents.set(lenses, new Map([[key, found]]))
  else {
    if (cache.size > 50_000) cache.clear()
    cache.set(key, found)
  }
  return found
}

/** Extents per set of lenses (a new set of calendars starts afresh). */
const extents = new WeakMap<readonly Lens[], Map<string, { lo: bigint; hi: bigint }>>()

function computeExtent(
  t: bigint,
  precision: string,
  lenses: readonly Lens[],
): { lo: bigint; hi: bigint } {
  for (const lens of lenses) {
    const calendar = lens.calendar
    if (calendar === null || calendar.levelIndex(precision) < 0) continue
    try {
      const bounds = unitBounds(calendar, t, precision)
      return { lo: bounds.start, hi: bounds.end }
    } catch {
      break
    }
  }
  return { lo: t, hi: t }
}

/**
 * Where an item goes on the timeline (frontend.md §9.3): spans are bars whose edges fade over the
 * uncertainty of their start and end (their precision's unit), softened further for circa; an
 * unknown end fades out after the start; instants are diamonds unless their own uncertainty is
 * wide, then a fuzzy span. `null` without a start.
 */
export function itemGeometry(
  item: TimedItem,
  v: Viewport,
  lenses: readonly Lens[],
): ItemGeometry | null {
  if (item.start_t === null) return null
  const start = extentOf(item.start_t, item.start_precision, lenses)
  const px = (t: bigint) => toPx(v, t)
  const startWidth = start.hi - start.lo
  const soften = (fade: number, circa: boolean) => (circa ? Math.max(fade, CIRCA_PX) : fade)

  const instant =
    item.end_kind === 'instant' ||
    (item.end_t !== null && item.end_t === item.start_t && item.end_kind !== 'unknown')
  if (instant) {
    const width = px(start.hi) - px(start.lo)
    if (width <= WIDE_INSTANT_PX) {
      return {
        kind: 'instant',
        x0: px(item.start_t),
        x1: px(item.start_t),
        fadeIn: 0,
        fadeOut: 0,
        openEnd: false,
      }
    }
    // A coarse instant: somewhere in its unit.
    return {
      kind: 'span',
      x0: px(start.lo),
      x1: px(start.hi),
      fadeIn: width / 2,
      fadeOut: width / 2,
      openEnd: false,
    }
  }
  if (item.end_kind === 'unknown' || item.end_t === null) {
    const x0 = px(start.lo)
    return {
      kind: 'span',
      x0,
      x1: px(start.hi) + OPEN_END_PX,
      fadeIn: soften(px(start.hi) - x0, item.start_approximate),
      fadeOut: OPEN_END_PX,
      openEnd: true,
    }
  }
  // The end's uncertainty: its own precision for an end date, the start's carried over otherwise.
  const end =
    item.end_kind === 'time_point' && item.end_precision !== null
      ? extentOf(item.end_t, item.end_precision, lenses)
      : { lo: item.end_t, hi: item.end_t + startWidth }
  let x0 = px(start.lo)
  const x1 = px(end.hi > end.lo ? end.hi : end.lo)
  let fadeIn = soften(px(start.hi) - x0, item.start_approximate)
  let fadeOut = soften(x1 - px(end.lo), item.end_approximate || item.start_approximate)
  if (item.start_approximate && fadeIn > px(start.hi) - x0) x0 -= fadeIn - (px(start.hi) - x0)
  const width = x1 - x0
  if (fadeIn + fadeOut > width && width > 0) {
    // Edges wider than the bar: share it.
    const scale = width / (fadeIn + fadeOut)
    fadeIn *= scale
    fadeOut *= scale
  }
  return { kind: 'span', x0, x1, fadeIn, fadeOut, openEnd: false }
}

/** The CSS background of a span: transparent edges fading into `color` (one element per item). */
export function spanBackground(geometry: ItemGeometry, color: string): string {
  // Fades under half a pixel don't show: a plain colour is cheaper to style and paint.
  if (geometry.fadeIn < 0.5 && geometry.fadeOut < 0.5) return color
  const width = Math.max(1, geometry.x1 - geometry.x0)
  const a = Math.min(100, (geometry.fadeIn / width) * 100)
  const b = Math.max(a, 100 - (geometry.fadeOut / width) * 100)
  return `linear-gradient(to right, transparent 0%, ${color} ${a.toFixed(2)}%, ${color} ${b.toFixed(2)}%, transparent 100%)`
}
