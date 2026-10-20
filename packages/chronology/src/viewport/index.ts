/**
 * `@lore/chronology/viewport`: timeline viewport math, calendar ticks and tiles
 * (chronology-engine.md §12, frontend.md §9.2). TypeScript only; the only place where moments
 * become floating-point pixels.
 */
export { type LogTickOptions, logTicks } from './log-ticks'
export { type Tick, type TickOptions, type Ticks, ticks } from './ticks'
export { type TileBounds, type Tiles, tileBounds, tileFor } from './tiles'
export {
  MIN_DECADES,
  MIN_SPAN,
  OFFSCREEN_PX,
  type LogScale,
  type Viewport,
  centerOn,
  clamp,
  fit,
  fromPx,
  logViewport,
  marginOf,
  panBy,
  toLinear,
  toLogPx,
  toLogScale,
  toPx,
  viewport,
  zoomAt,
} from './viewport'
