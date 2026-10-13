import type { IconName } from '@/core/registry'
import type { Kind } from '@/core/registry'

export const LOCATION = 'location'
export const TYPE_FIELD = 'location_type'
export const EVENT_SITE = 'locations.event_site'
export const RESIDES_IN = 'locations.resides_in'
export const CONNECTED_TO = 'locations.connected_to'

/** An icon per location type (docs/modules/locations.md). */
export const TYPE_ICONS: Readonly<Record<string, IconName>> = {
  universe: 'sparkles',
  galaxy: 'orbit',
  star_system: 'sun',
  star: 'star',
  planet: 'globe',
  moon: 'moon',
  plane: 'layers',
  continent: 'map',
  ocean: 'waves',
  region: 'map',
  country: 'flag',
  province: 'flag',
  city: 'building-2',
  town: 'home',
  village: 'home',
  district: 'map-pin',
  building: 'castle',
  room: 'door-open',
  landmark: 'landmark',
  natural_feature: 'mountain',
  other: 'map-pin',
}

/** The label of a location type option (the key when the registry doesn't know it). */
export function typeLabel(kind: Kind | undefined, type: string | null): string | null {
  if (type === null) return null
  const field = kind?.fields.find((candidate) => candidate.key === TYPE_FIELD)
  return field?.options.find((option) => option.key === type)?.label ?? type
}

/** Option keys in the order the field lists them (for grouping by type). */
export function typeOrder(kind: Kind | undefined): string[] {
  return kind?.fields.find((field) => field.key === TYPE_FIELD)?.options.map((o) => o.key) ?? []
}
