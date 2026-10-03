/**
 * `@lore/chronology/viewport`: timeline viewport math, calendar ticks and tiles
 * (chronology-engine.md §12, frontend.md §9.2). TypeScript only; the only place where moments
 * become floating-point pixels.
 */
export { type Tick, type TickOptions, type Ticks, ticks } from './ticks'
export { type TileBounds, type Tiles, tileBounds, tileFor } from './tiles'
export {
  MIN_SPAN,
  OFFSCREEN_PX,
  type Viewport,
  clamp,
  fit,
  fromPx,
  marginOf,
  panBy,
  toPx,
  viewport,
  zoomAt,
} from './viewport'
