import { Link } from '@tanstack/react-router'
import { MapIcon } from 'lucide-react'

import type { EntityViewProps } from '@/core/modules'
import { useEntityPins } from '@/data'

/** Shown when the entity is pinned somewhere. */
export function usePinned({ vault, entityId }: EntityViewProps): boolean {
  return (useEntityPins(vault, entityId).data?.items.length ?? 0) > 0
}

/** "Show on map": the maps the entity is pinned on, each opening centered on its pin. */
export function PinnedPanel({ vault, entityId }: EntityViewProps) {
  const pins = useEntityPins(vault, entityId)
  const items = pins.data?.items ?? []
  return (
    <ul aria-label="On maps" className="flex flex-col gap-1 text-sm">
      {items.map(({ map, pin }) => (
        <li key={pin.id}>
          <Link
            className="flex items-center gap-2 hover:underline"
            to="/v/$vault/m/$module/$"
            params={{ vault, module: 'maps', _splat: `maps/${map.id}/pins/${pin.id}` }}
          >
            <MapIcon aria-hidden className="size-3.5" />
            Show on map {map.name}
          </Link>
        </li>
      ))}
    </ul>
  )
}
