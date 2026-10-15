import { Link, useNavigate } from '@tanstack/react-router'
import { Maximize2Icon } from 'lucide-react'
import { useState } from 'react'

import type { EntityViewProps } from '@/core/modules'
import { useMaps } from '@/data'

import { MapView } from '../views/map-view'

/** A location's maps (docs/modules/maps.md, UI): one at a time, a switcher when several. */
export function MapPanel({ vault, entityId }: EntityViewProps) {
  const maps = useMaps(vault, entityId)
  const navigate = useNavigate()
  const [chosen, setChosen] = useState<string | null>(null)
  if (maps.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  const items = maps.data?.items ?? []
  const shown = items.find((map) => map.id === chosen) ?? items[0]
  if (shown === undefined)
    return <p className="text-sm text-muted-foreground">No maps of this place.</p>
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-sm">
        {items.length > 1 && (
          <label className="flex items-center gap-2">
            Map
            <select
              className="h-8 rounded-md border bg-transparent px-2 text-sm"
              value={shown.id}
              onChange={(event) => {
                setChosen(event.target.value)
              }}
            >
              {items.map((map) => (
                <option key={map.id} value={map.id}>
                  {map.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <Link
          className="ml-auto flex items-center gap-1 text-muted-foreground hover:underline"
          to="/v/$vault/m/$module/$"
          params={{ vault, module: 'maps', _splat: `maps/${shown.id}` }}
        >
          <Maximize2Icon aria-hidden className="size-3.5" />
          Full screen
        </Link>
      </div>
      <MapView
        vault={vault}
        mapId={shown.id}
        className="h-96"
        onOpenMap={(map) => {
          if (items.some((item) => item.id === map)) setChosen(map)
          else
            void navigate({
              to: '/v/$vault/m/$module/$',
              params: { vault, module: 'maps', _splat: `maps/${map}` },
            })
        }}
      />
    </div>
  )
}
