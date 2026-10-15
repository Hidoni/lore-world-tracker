import { Link } from '@tanstack/react-router'
import { ChevronRightIcon, ExternalLinkIcon, MapIcon, TagIcon, XIcon } from 'lucide-react'
import { createElement, lazy, Suspense, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { iconFor, useKindRegistry, type KindRegistry } from '@/core/registry'
import { SpanDisplay, useEntityAsOf } from '@/core/time'
import { mediaFileUrl, useEntity, useMapDetail, type MapDetail, type MapPin } from '@/data'
import { cn } from '@/lib/utils'

import {
  LABEL_LAYER,
  layerOf,
  layersOf,
  pinsToShow,
  trail,
  type CursorMode,
  type ShownPin,
} from '../pins'
import type { CanvasMarker } from './map-canvas'

const MapCanvas = lazy(() => import('./map-canvas'))

export interface MapViewProps {
  vault: string
  mapId: string
  /** Where breadcrumbs and "drill into map" go. */
  onOpenMap: (mapId: string) => void
  /** A pin to select and center on. */
  focusPin?: string | null
  className?: string
}

/**
 * A map with its pins (docs/modules/maps.md, UI: view mode): breadcrumbs of the enclosing maps,
 * layer toggles by kind, and with a time cursor the pins there at that moment (the others hidden
 * or ghosted). Hovering a pin names it; a click opens a popover with "open page" and "drill into
 * map".
 */
export function MapView({ vault, mapId, onOpenMap, focusPin = null, className }: MapViewProps) {
  const detail = useMapDetail(vault, mapId)
  if (detail.isError) return <p className="text-sm text-destructive">This map can't be shown.</p>
  if (detail.data === undefined) return <p className="text-sm text-muted-foreground">Loading…</p>
  return (
    <LoadedMap
      key={mapId}
      vault={vault}
      detail={detail.data}
      onOpenMap={onOpenMap}
      focusPin={focusPin}
      className={className}
    />
  )
}

function pinIcon(pin: MapPin, registry: KindRegistry | undefined) {
  const name = pin.icon ?? pin.target?.icon ?? null
  if (name !== null) return iconFor(name)
  if (pin.target === null) return TagIcon
  return registry?.kind(pin.target.kind)?.icon ?? iconFor('circle')
}

function pinColor(pin: MapPin, registry: KindRegistry | undefined): string | null {
  return (
    pin.color ??
    pin.target?.color ??
    (pin.target === null ? null : (registry?.kind(pin.target.kind)?.color ?? null))
  )
}

function LoadedMap({
  vault,
  detail,
  onOpenMap,
  focusPin,
  className,
}: {
  vault: string
  detail: MapDetail
  onOpenMap: (mapId: string) => void
  focusPin: string | null
  className?: string | undefined
}) {
  const registry = useKindRegistry(vault)
  const asOf = useEntityAsOf(vault, detail.location_id)
  const [mode, setMode] = useState<CursorMode>('hide')
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set())
  const [selected, setSelected] = useState<string | null>(focusPin)
  const current = useMapDetail(vault, detail.id, asOf ?? {}, { enabled: asOf !== undefined })
  const timeline = useMapDetail(
    vault,
    detail.id,
    asOf === undefined ? {} : { timeline: asOf.timeline },
    { enabled: asOf !== undefined && mode === 'ghost' },
  )
  const shown: ShownPin[] | null = useMemo(() => {
    if (asOf === undefined) return pinsToShow(detail.pins, null, mode, hidden)
    const now = current.data?.pins
    if (now === undefined) return null
    return pinsToShow(mode === 'ghost' ? (timeline.data?.pins ?? now) : now, now, mode, hidden)
  }, [asOf, detail.pins, current.data, timeline.data, mode, hidden])
  const layers = layersOf([...detail.pins, ...(current.data?.pins ?? [])])
  const markers: CanvasMarker[] = useMemo(
    () =>
      (shown ?? []).map(({ pin, ghost }) => ({
        id: pin.id,
        label: pin.display_label,
        x: pin.x,
        y: pin.y,
        icon: pinIcon(pin, registry),
        color: pinColor(pin, registry),
        ghost,
      })),
    [shown, registry],
  )
  const chosen = shown?.find((item) => item.pin.id === selected) ?? null
  const crumbs = trail(detail)
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <nav aria-label="Map breadcrumbs">
          <ol className="flex flex-wrap items-center gap-1">
            {crumbs.map((crumb, index) => (
              <li key={crumb.mapId} className="flex items-center gap-1">
                {index > 0 && <ChevronRightIcon aria-hidden className="size-3.5" />}
                {index === crumbs.length - 1 ? (
                  <span aria-current="page" className="font-medium">
                    {crumb.name}
                  </span>
                ) : (
                  <button
                    type="button"
                    className="text-muted-foreground hover:underline"
                    onClick={() => {
                      onOpenMap(crumb.mapId)
                    }}
                  >
                    {crumb.name}
                  </button>
                )}
              </li>
            ))}
          </ol>
        </nav>
        {layers.length > 0 && (
          <fieldset className="flex flex-wrap items-center gap-3">
            <legend className="sr-only">Layers</legend>
            {layers.map((layer) => (
              <label key={layer} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={!hidden.has(layer)}
                  onChange={(event) => {
                    const next = new Set(hidden)
                    if (event.target.checked) next.delete(layer)
                    else next.add(layer)
                    setHidden(next)
                  }}
                />
                {layer === LABEL_LAYER ? 'Labels' : (registry?.kind(layer)?.plural ?? layer)}
              </label>
            ))}
          </fieldset>
        )}
        {asOf !== undefined && (
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={mode === 'ghost'}
              onChange={(event) => {
                setMode(event.target.checked ? 'ghost' : 'hide')
              }}
            />
            Ghost what isn't there
          </label>
        )}
      </div>
      <div className="relative min-h-64 flex-1 overflow-hidden rounded-md border">
        <Suspense fallback={<p className="p-4 text-sm text-muted-foreground">Loading map…</p>}>
          <MapCanvas
            image={mediaFileUrl(vault, detail.media_id)}
            width={detail.width}
            height={detail.height}
            markers={markers}
            selected={selected}
            focus={focusPin}
            onSelect={setSelected}
          />
        </Suspense>
        {chosen !== null && (
          <PinPopover
            vault={vault}
            location={detail.location_id}
            shown={chosen}
            layer={layerOf(chosen.pin)}
            registry={registry}
            onOpenMap={onOpenMap}
            onClose={() => {
              setSelected(null)
            }}
          />
        )}
      </div>
    </div>
  )
}

function PinPopover({
  vault,
  location,
  shown: { pin, ghost },
  layer,
  registry,
  onOpenMap,
  onClose,
}: {
  vault: string
  location: string
  shown: ShownPin
  layer: string
  registry: KindRegistry | undefined
  onOpenMap: (mapId: string) => void
  onClose: () => void
}) {
  const target = useEntity(vault, pin.target?.id ?? '', {}, { enabled: pin.target !== null })
  const place = useEntity(vault, location)
  const dimension = place.data?.dimension_id ?? null
  const bounded = pin.valid_from_t !== null || pin.valid_to_t !== null
  return (
    <section
      role="dialog"
      aria-label={pin.display_label}
      className="absolute top-2 right-2 z-[1000] flex w-72 flex-col gap-2 rounded-md border bg-popover p-3 text-sm text-popover-foreground shadow-md"
    >
      <header className="flex items-start gap-2">
        {createElement(pinIcon(pin, registry), {
          'aria-hidden': true,
          className: 'mt-0.5 size-4 shrink-0',
        })}
        <h3 className="flex-1 font-medium">{pin.display_label}</h3>
        <button type="button" aria-label="Close" onClick={onClose}>
          <XIcon aria-hidden className="size-4" />
        </button>
      </header>
      {layer !== LABEL_LAYER && (
        <p className="text-xs text-muted-foreground">{registry?.kind(layer)?.label ?? layer}</p>
      )}
      {ghost && (
        <p className="text-xs text-muted-foreground">
          {pin.shown === 'possible' ? 'Possibly there at the cursor.' : 'Not there at the cursor.'}
        </p>
      )}
      {target.data !== undefined && target.data.summary !== '' && <p>{target.data.summary}</p>}
      {bounded && dimension !== null && (
        <p className="text-xs">
          <SpanDisplay
            vault={vault}
            dimension={dimension}
            start={
              pin.valid_from_t === null
                ? null
                : { t: pin.valid_from_t, precision: pin.valid_from?.precision ?? 'base' }
            }
            end={
              pin.valid_to_t === null
                ? null
                : { t: pin.valid_to_t, precision: pin.valid_to?.precision ?? 'base' }
            }
          />
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {pin.target !== null && (
          <Button asChild size="sm" variant="outline">
            <Link to="/v/$vault/e/$entity" params={{ vault, entity: pin.target.id }}>
              <ExternalLinkIcon aria-hidden />
              Open page
            </Link>
          </Button>
        )}
        {pin.drill_map_id !== null && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (pin.drill_map_id !== null) onOpenMap(pin.drill_map_id)
            }}
          >
            <MapIcon aria-hidden />
            Drill into map
          </Button>
        )}
      </div>
    </section>
  )
}
