import type { MapDetail, MapPin, MapRegion } from '@/data'

/** Pins with no target form their own layer. */
export const LABEL_LAYER = 'label'

/** How the time cursor treats pins that aren't there: leave them out, or show them faded. */
export type CursorMode = 'hide' | 'ghost'

export interface ShownPin {
  pin: MapPin
  /** Faded: not there at the cursor (ghost mode), or only possibly there. */
  ghost: boolean
}

/** The layer a pin belongs to: its target's kind, or `label`. */
export function layerOf(pin: MapPin): string {
  return pin.target?.kind ?? LABEL_LAYER
}

/** The layers of a map's pins, sorted (labels last). */
export function layersOf(pins: readonly MapPin[]): string[] {
  const layers = [...new Set(pins.map(layerOf))]
  return layers.sort((a, b) =>
    a === LABEL_LAYER ? 1 : b === LABEL_LAYER ? -1 : a.localeCompare(b),
  )
}

/**
 * The pins to draw. `all` are the map's pins of the timeline at any time; `current` the ones
 * there at the cursor (`null` without one). Hiding drops the others; ghosting keeps them faded.
 * Pins that are only possibly there are faded either way. Hidden layers are left out.
 */
export function pinsToShow(
  all: readonly MapPin[],
  current: readonly MapPin[] | null,
  mode: CursorMode,
  hiddenLayers: ReadonlySet<string> = new Set(),
): ShownPin[] {
  const visible = (pin: MapPin) => !hiddenLayers.has(layerOf(pin))
  if (current === null) return all.filter(visible).map((pin) => ({ pin, ghost: false }))
  const there = new Map(current.map((pin) => [pin.id, pin]))
  const base = mode === 'hide' ? current : all
  return base.filter(visible).map((pin) => {
    const now = there.get(pin.id)
    return { pin: now ?? pin, ghost: now === undefined || now.shown === 'possible' }
  })
}

/** The layer of every region (they toggle together; not a kind id). */
export const REGION_LAYER = '#regions'

export interface ShownRegion {
  region: MapRegion
  /** Faded: not there at the cursor (ghost mode), or only possibly there. */
  ghost: boolean
}

/** The regions to draw: like `pinsToShow`, with all regions in one layer. */
export function regionsToShow(
  all: readonly MapRegion[],
  current: readonly MapRegion[] | null,
  mode: CursorMode,
  hiddenLayers: ReadonlySet<string> = new Set(),
): ShownRegion[] {
  if (hiddenLayers.has(REGION_LAYER)) return []
  if (current === null) return all.map((region) => ({ region, ghost: false }))
  const there = new Map(current.map((region) => [region.id, region]))
  const base = mode === 'hide' ? current : all
  return base.map((region) => {
    const now = there.get(region.id)
    return {
      region: now ?? region,
      ghost: now === undefined || now.shown === 'possible',
    }
  })
}

/**
 * A region's fill: its own color, else its first controller's (at the cursor, or ever without
 * one), else its target's; `null` for the default.
 */
export function regionColor(region: MapRegion): string | null {
  return region.color ?? region.controllers[0]?.color ?? region.target?.color ?? null
}

/** Leaflet's simple CRS has y going up: image pixel `(x, y)` from the top left. */
export function toLatLng(pin: Pick<MapPin, 'x' | 'y'>, height: number): [number, number] {
  return [height - pin.y, pin.x]
}

/** The trail from the outermost map to this one. */
export function trail(detail: MapDetail): { mapId: string; name: string }[] {
  return [
    ...detail.breadcrumbs.map((crumb) => ({ mapId: crumb.map_id, name: crumb.name })),
    { mapId: detail.id, name: detail.name },
  ]
}
