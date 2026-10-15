import { Link, useNavigate, useParams } from '@tanstack/react-router'

import { useMapDetail } from '@/data'

import { MapView } from './map-view'

/** The full-screen map page (`/m/maps/maps/$map`; `…/pins/$pin` selects and centers a pin). */
export default function MapPage() {
  const params = useParams({ strict: false })
  const vault = params.vault ?? ''
  const { map: mapId = '', pin } = params as { map?: string; pin?: string }
  const navigate = useNavigate()
  const detail = useMapDetail(vault, mapId)
  return (
    <div className="flex h-full flex-col gap-2 p-4">
      <header className="flex items-baseline gap-3">
        <h1 className="text-xl font-semibold">{detail.data?.name ?? 'Map'}</h1>
        {detail.data !== undefined && (
          <Link
            className="text-sm text-muted-foreground hover:underline"
            to="/v/$vault/e/$entity"
            params={{ vault, entity: detail.data.location_id }}
          >
            Open the location
          </Link>
        )}
      </header>
      <MapView
        vault={vault}
        mapId={mapId}
        focusPin={pin ?? null}
        className="min-h-0 flex-1"
        onOpenMap={(map) => {
          void navigate({
            to: '/v/$vault/m/$module/$',
            params: { vault, module: 'maps', _splat: `maps/${map}` },
          })
        }}
      />
    </div>
  )
}
