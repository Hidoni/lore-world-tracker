import { Link } from '@tanstack/react-router'
import {
  ChevronRightIcon,
  ExternalLinkIcon,
  MapIcon,
  PencilIcon,
  PentagonIcon,
  TagIcon,
  XIcon,
} from 'lucide-react'
import { toast } from 'sonner'
import { createElement, lazy, Suspense, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { iconFor, useKindRegistry, type KindRegistry } from '@/core/registry'
import { SpanDisplay, useEntityAsOf } from '@/core/time'
import {
  mediaFileUrl,
  mediaTileUrl,
  useCreatePin,
  useCreateRegion,
  useEntity,
  useMapDetail,
  useMutations,
  useUpdatePin,
  useUpdateRegion,
  type MapDetail,
  type MapPin,
  type MapRegion,
} from '@/data'
import { cn } from '@/lib/utils'

import {
  LABEL_LAYER,
  layerOf,
  layersOf,
  pinsToShow,
  REGION_LAYER,
  regionColor,
  regionsToShow,
  trail,
  type CursorMode,
  type ShownPin,
  type ShownRegion,
} from '../pins'
import { AddPinDialog, type PinChoice } from '../edit/add-pin-dialog'
import { ChildTray } from '../edit/child-tray'
import { PinEditor } from '../edit/pin-editor'
import { RegionEditor } from '../edit/region-editor'
import type { CanvasMarker, CanvasRegion, CanvasTiles, Point } from './map-canvas'

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
 * A map with its pins and regions (docs/modules/maps.md, UI: view mode): breadcrumbs of the
 * enclosing maps, layer toggles by kind, and with a time cursor the pins and regions there at that
 * moment (the others hidden or ghosted). Hovering a pin names it; a click opens a popover with
 * "open page" and "drill into map" (for a region, who controls it).
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

/**
 * What the canvas draws: the image whole, or (#162) a large one's tiles over its 1280 px
 * thumbnail (a static export has no tiles: the image whole there).
 */
function canvasImage(
  vault: string,
  detail: MapDetail,
): { image: string; tiles: CanvasTiles | null } {
  const url = detail.tile_levels === null ? null : mediaTileUrl(vault, detail.media_id)
  if (url === null || detail.tile_levels === null) {
    return { image: mediaFileUrl(vault, detail.media_id), tiles: null }
  }
  return {
    image: mediaFileUrl(vault, detail.media_id, '1280'),
    tiles: { url, levels: detail.tile_levels },
  }
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
  // A new object each render: memos depend on whether there is a cursor (so markers stay put).
  const cursor = asOf !== undefined
  const [mode, setMode] = useState<CursorMode>('hide')
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set())
  const [selected, setSelected] = useState<string | null>(focusPin)
  const editable = useMutations() !== null
  const [editing, setEditing] = useState(false)
  const [asList, setAsList] = useState(false)
  const [placing, setPlacing] = useState<Point | null>(null)
  // A region being drawn: its corners, and the region it replaces the outline of (redrawing).
  const [drawing, setDrawing] = useState<Point[] | null>(null)
  const [redrawing, setRedrawing] = useState<MapRegion | null>(null)
  const [outlined, setOutlined] = useState<Point[] | null>(null)
  const place = useEntity(vault, detail.location_id)
  const dimensionId = place.data?.dimension_id ?? null
  const dimension = useEntity(vault, dimensionId ?? '', {}, { enabled: dimensionId !== null })
  const prime = (dimension.data?.ext as { prime_timeline_id?: string } | null | undefined)
    ?.prime_timeline_id
  const editTimeline = asOf?.timeline ?? prime ?? null
  const current = useMapDetail(vault, detail.id, asOf ?? {}, { enabled: asOf !== undefined })
  const timeline = useMapDetail(
    vault,
    detail.id,
    asOf === undefined ? {} : { timeline: asOf.timeline },
    { enabled: asOf !== undefined && mode === 'ghost' },
  )
  const shown: ShownPin[] | null = useMemo(() => {
    // Editing: every pin of the map, whenever it stands.
    if (!cursor || editing) return pinsToShow(detail.pins, null, mode, hidden)
    const now = current.data?.pins
    if (now === undefined) return null
    return pinsToShow(mode === 'ghost' ? (timeline.data?.pins ?? now) : now, now, mode, hidden)
  }, [cursor, editing, detail.pins, current.data, timeline.data, mode, hidden])
  const shownRegions: ShownRegion[] | null = useMemo(() => {
    if (!cursor || editing) return regionsToShow(detail.regions, null, mode, hidden)
    const now = current.data?.regions
    if (now === undefined) return null
    return regionsToShow(
      mode === 'ghost' ? (timeline.data?.regions ?? now) : now,
      now,
      mode,
      hidden,
    )
  }, [cursor, editing, detail.regions, current.data, timeline.data, mode, hidden])
  const createRegion = useCreateRegion(vault, detail.id)
  const updateRegion = useUpdateRegion(vault)
  const regionFailed = (error: Error) => {
    toast.error(`The region wasn't saved: ${error.message}`)
  }
  const pointsOf = (points: readonly Point[]) => points.map(({ x, y }) => [x, y])
  const finishDrawing = () => {
    if (drawing === null || drawing.length < 3) return
    if (redrawing !== null) {
      reshape(redrawing, drawing)
      setSelected(redrawing.id)
    } else setOutlined(drawing)
    setDrawing(null)
    setRedrawing(null)
  }
  const reshape = (region: MapRegion, points: readonly Point[]) => {
    updateRegion.mutate(
      { region: region.id, body: { revision: region.revision, points: pointsOf(points) } },
      { onError: regionFailed },
    )
  }
  const addRegion = (choice: PinChoice, points: readonly Point[]) => {
    const body = 'target' in choice ? { target_entity_id: choice.target } : { label: choice.label }
    createRegion.mutate(
      { ...body, points: pointsOf(points) },
      {
        onSuccess: (result) => {
          setSelected(result.region.id)
        },
        onError: regionFailed,
      },
    )
  }
  const createPin = useCreatePin(vault, detail.id)
  const updatePin = useUpdatePin(vault)
  const failed = (error: Error) => {
    toast.error(`The pin wasn't saved: ${error.message}`)
  }
  const addPin = (choice: PinChoice, at: Point) => {
    const body = 'target' in choice ? { target_entity_id: choice.target } : { label: choice.label }
    createPin.mutate(
      { ...body, x: at.x, y: at.y },
      {
        onSuccess: (result) => {
          setSelected(result.pin.id)
        },
        onError: failed,
      },
    )
  }
  const movePin = (id: string, at: Point) => {
    const pin = detail.pins.find((candidate) => candidate.id === id)
    if (pin === undefined) return
    updatePin.mutate(
      { pin: id, body: { revision: pin.revision, x: at.x, y: at.y } },
      { onError: failed },
    )
  }
  const layers = layersOf([...detail.pins, ...(current.data?.pins ?? [])])
  if (detail.regions.length > 0 || (current.data?.regions.length ?? 0) > 0)
    layers.splice(0, 0, REGION_LAYER)
  const regions: CanvasRegion[] = useMemo(
    () =>
      (shownRegions ?? []).map(({ region, ghost }) => ({
        id: region.id,
        label: region.display_label,
        points: region.points,
        color: regionColor(region),
        ghost,
      })),
    [shownRegions],
  )
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
  const chosenRegion = shownRegions?.find((item) => item.region.id === selected) ?? null
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
                {layer === LABEL_LAYER
                  ? 'Labels'
                  : layer === REGION_LAYER
                    ? 'Regions'
                    : (registry?.kind(layer)?.plural ?? layer)}
              </label>
            ))}
          </fieldset>
        )}
        {editable && (
          <Button
            size="sm"
            variant={editing ? 'default' : 'outline'}
            aria-pressed={editing}
            className="ml-auto"
            onClick={() => {
              setEditing(!editing)
              setSelected(null)
              setDrawing(null)
              setRedrawing(null)
            }}
          >
            <PencilIcon aria-hidden />
            {editing ? 'Done editing' : 'Edit map'}
          </Button>
        )}
        {editing && drawing === null && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setSelected(null)
              setDrawing([])
            }}
          >
            <PentagonIcon aria-hidden />
            Draw region
          </Button>
        )}
        {editing && drawing !== null && (
          <>
            <Button size="sm" disabled={drawing.length < 3} onClick={finishDrawing}>
              Finish region
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                if (redrawing !== null) setSelected(redrawing.id)
                setDrawing(null)
                setRedrawing(null)
              }}
            >
              Cancel
            </Button>
          </>
        )}
        {!editing && (
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={asList}
              onChange={(event) => {
                setAsList(event.target.checked)
              }}
            />
            As a list
          </label>
        )}
        {asOf !== undefined && !editing && (
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
      {editing && (
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {drawing === null
            ? 'Click the map to add a pin, drag pins to move them, click a pin or a region to edit it (a region’s corners drag).'
            : `Click the map to add corners (${String(drawing.length)} so far), then finish the region.`}
        </p>
      )}
      {asList && !editing ? (
        <>
          <PinList vault={vault} shown={shown} registry={registry} onOpenMap={onOpenMap} />
          {shownRegions !== null && shownRegions.length > 0 && (
            <RegionList vault={vault} shown={shownRegions} />
          )}
        </>
      ) : (
        <div className="flex min-h-64 flex-1 gap-3">
          <div className="relative flex-1 overflow-hidden rounded-md border">
            <Suspense fallback={<p className="p-4 text-sm text-muted-foreground">Loading map…</p>}>
              <MapCanvas
                {...canvasImage(vault, detail)}
                width={detail.width}
                height={detail.height}
                markers={markers}
                regions={regions}
                selected={selected}
                focus={focusPin}
                onSelect={setSelected}
                editing={editing}
                onPlace={setPlacing}
                onMove={movePin}
                onDropEntity={(entity, at) => {
                  addPin({ target: entity }, at)
                }}
                drawing={drawing}
                onDraw={(at) => {
                  setDrawing((corners) => (corners === null ? null : [...corners, at]))
                }}
                onReshape={(id, points) => {
                  const region = detail.regions.find((candidate) => candidate.id === id)
                  if (region !== undefined) reshape(region, points)
                }}
              />
            </Suspense>
            {editing && chosen !== null && (
              <PinEditor
                key={`${chosen.pin.id}:${String(chosen.pin.revision)}`}
                vault={vault}
                pin={chosen.pin}
                dimension={dimensionId}
                timeline={editTimeline}
                onClose={() => {
                  setSelected(null)
                }}
              />
            )}
            {editing && drawing === null && chosenRegion !== null && (
              <RegionEditor
                key={`${chosenRegion.region.id}:${String(chosenRegion.region.revision)}`}
                vault={vault}
                region={chosenRegion.region}
                location={detail.location_id}
                dimension={dimensionId}
                timeline={editTimeline}
                onRedraw={() => {
                  setRedrawing(chosenRegion.region)
                  setSelected(null)
                  setDrawing([])
                }}
                onClose={() => {
                  setSelected(null)
                }}
              />
            )}
            {!editing && chosenRegion !== null && (
              <RegionPopover
                vault={vault}
                location={detail.location_id}
                shown={chosenRegion}
                onClose={() => {
                  setSelected(null)
                }}
              />
            )}
            {!editing && chosen !== null && (
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
          {editing && (
            <aside className="w-56 shrink-0">
              <ChildTray
                vault={vault}
                location={detail.location_id}
                pins={detail.pins}
                onPlace={(entity) => {
                  addPin({ target: entity }, { x: detail.width / 2, y: detail.height / 2 })
                }}
              />
            </aside>
          )}
        </div>
      )}
      {outlined !== null && (
        <AddPinDialog
          vault={vault}
          location={detail.location_id}
          noun="region"
          onAdd={(choice) => {
            addRegion(choice, outlined)
            setOutlined(null)
          }}
          onClose={() => {
            setOutlined(null)
          }}
        />
      )}
      {placing !== null && (
        <AddPinDialog
          vault={vault}
          location={detail.location_id}
          onAdd={(choice) => {
            addPin(choice, placing)
            setPlacing(null)
          }}
          onClose={() => {
            setPlacing(null)
          }}
        />
      )}
    </div>
  )
}

/**
 * The map as a list (frontend.md §9.6): the pins shown (the same layers and time cursor), by label,
 * each with its kind, whether it is there at the cursor, its page and the map it drills into.
 */
function PinList({
  vault,
  shown,
  registry,
  onOpenMap,
}: {
  vault: string
  shown: ShownPin[] | null
  registry: KindRegistry | undefined
  onOpenMap: (mapId: string) => void
}) {
  if (shown === null) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (shown.length === 0) return <p className="text-sm text-muted-foreground">No pins shown.</p>
  const sorted = [...shown].sort((a, b) => a.pin.display_label.localeCompare(b.pin.display_label))
  return (
    <ul aria-label="Pins" className="flex flex-col divide-y rounded-md border text-sm">
      {sorted.map(({ pin, ghost }) => {
        const layer = layerOf(pin)
        return (
          <li key={pin.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
            {createElement(pinIcon(pin, registry), {
              'aria-hidden': true,
              className: 'size-4 shrink-0',
            })}
            {pin.target !== null ? (
              <Link
                to="/v/$vault/e/$entity"
                params={{ vault, entity: pin.target.id }}
                className="font-medium underline-offset-2 hover:underline"
              >
                {pin.display_label}
              </Link>
            ) : (
              <span className="font-medium">{pin.display_label}</span>
            )}
            <span className="text-xs text-muted-foreground">
              {layer === LABEL_LAYER ? 'Label' : (registry?.kind(layer)?.label ?? layer)}
            </span>
            {ghost && (
              <span className="text-xs text-muted-foreground">
                {pin.shown === 'possible' ? 'possibly there' : 'not there at the cursor'}
              </span>
            )}
            {pin.drill_map_id !== null && (
              <Button
                size="sm"
                variant="outline"
                className="ml-auto"
                onClick={() => {
                  if (pin.drill_map_id !== null) onOpenMap(pin.drill_map_id)
                }}
              >
                <MapIcon aria-hidden />
                Drill into map
              </Button>
            )}
          </li>
        )
      })}
    </ul>
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
            startPoint={pin.valid_from}
            endPoint={pin.valid_to}
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

/** Who controls a region's place, as links. */
function Controllers({ vault, region }: { vault: string; region: MapRegion }) {
  if (region.controllers.length === 0) return null
  return (
    <p className="text-xs">
      Controlled by{' '}
      {region.controllers.map((controller, index) => (
        <span key={controller.id}>
          {index > 0 && ', '}
          <Link
            to="/v/$vault/e/$entity"
            params={{ vault, entity: controller.id }}
            className="font-medium underline-offset-2 hover:underline"
          >
            {controller.name}
          </Link>
        </span>
      ))}
    </p>
  )
}

/** The regions shown, in the list view: by label, with who controls each. */
function RegionList({ vault, shown }: { vault: string; shown: ShownRegion[] }) {
  const sorted = [...shown].sort((a, b) =>
    a.region.display_label.localeCompare(b.region.display_label),
  )
  return (
    <ul aria-label="Regions" className="flex flex-col divide-y rounded-md border text-sm">
      {sorted.map(({ region, ghost }) => (
        <li key={region.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
          <PentagonIcon
            aria-hidden
            className="size-4 shrink-0"
            style={{ color: regionColor(region) ?? undefined }}
          />
          {region.target !== null ? (
            <Link
              to="/v/$vault/e/$entity"
              params={{ vault, entity: region.target.id }}
              className="font-medium underline-offset-2 hover:underline"
            >
              {region.display_label}
            </Link>
          ) : (
            <span className="font-medium">{region.display_label}</span>
          )}
          <span className="text-xs text-muted-foreground">Region</span>
          {ghost && (
            <span className="text-xs text-muted-foreground">
              {region.shown === 'possible' ? 'possibly there' : 'not there at the cursor'}
            </span>
          )}
          <Controllers vault={vault} region={region} />
        </li>
      ))}
    </ul>
  )
}

function RegionPopover({
  vault,
  location,
  shown: { region, ghost },
  onClose,
}: {
  vault: string
  location: string
  shown: ShownRegion
  onClose: () => void
}) {
  const place = useEntity(vault, location)
  const dimension = place.data?.dimension_id ?? null
  const bounded = region.valid_from_t !== null || region.valid_to_t !== null
  return (
    <section
      role="dialog"
      aria-label={region.display_label}
      className="absolute top-2 right-2 z-[1000] flex w-72 flex-col gap-2 rounded-md border bg-popover p-3 text-sm text-popover-foreground shadow-md"
    >
      <header className="flex items-start gap-2">
        <PentagonIcon
          aria-hidden
          className="mt-0.5 size-4 shrink-0"
          style={{ color: regionColor(region) ?? undefined }}
        />
        <h3 className="flex-1 font-medium">{region.display_label}</h3>
        <button type="button" aria-label="Close" onClick={onClose}>
          <XIcon aria-hidden className="size-4" />
        </button>
      </header>
      {ghost && (
        <p className="text-xs text-muted-foreground">
          {region.shown === 'possible'
            ? 'Possibly there at the cursor.'
            : 'Not there at the cursor.'}
        </p>
      )}
      <Controllers vault={vault} region={region} />
      {bounded && dimension !== null && (
        <p className="text-xs">
          <SpanDisplay
            vault={vault}
            dimension={dimension}
            start={
              region.valid_from_t === null
                ? null
                : { t: region.valid_from_t, precision: region.valid_from?.precision ?? 'base' }
            }
            end={
              region.valid_to_t === null
                ? null
                : { t: region.valid_to_t, precision: region.valid_to?.precision ?? 'base' }
            }
            startPoint={region.valid_from}
            endPoint={region.valid_to}
          />
        </p>
      )}
      {region.target !== null && (
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <Link to="/v/$vault/e/$entity" params={{ vault, entity: region.target.id }}>
              <ExternalLinkIcon aria-hidden />
              Open page
            </Link>
          </Button>
        </div>
      )}
    </section>
  )
}
