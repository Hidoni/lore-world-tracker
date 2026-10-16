import 'leaflet/dist/leaflet.css'
import 'leaflet.markercluster/dist/MarkerCluster.css'
import 'leaflet.markercluster/dist/MarkerCluster.Default.css'

import L from 'leaflet'
import 'leaflet.markercluster'
import { useEffect, useMemo, useRef, type ComponentType } from 'react'

import { toLatLng } from '../pins'

export interface CanvasMarker {
  id: string
  label: string
  /** Image pixels from the top left. */
  x: number
  y: number
  icon: ComponentType<{ className?: string; 'aria-hidden'?: boolean }>
  color: string | null
  ghost: boolean
}

/** What a dragged entity carries (the child-location tray): its id. */
export const ENTITY_DRAG_TYPE = 'application/x-lore-entity'

/** An image pixel, from the top left. */
export interface Point {
  x: number
  y: number
}

/** Pins this close together (screen pixels) cluster. */
const CLUSTER_RADIUS = 40

function markerIcon(marker: CanvasMarker, glyph: string, selected: boolean): L.DivIcon {
  const ring = selected ? ' ring-2 ring-ring' : ''
  const ghost = marker.ghost ? ' opacity-40 grayscale' : ''
  const style = marker.color === null ? '' : ` style="color:${marker.color}"`
  return L.divIcon({
    className: '',
    html: `<span class="flex size-6 items-center justify-center rounded-full border bg-background shadow-sm${ring}${ghost}"${style}>${glyph}</span>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    tooltipAnchor: [12, 0],
  })
}

/**
 * A map image drawn with Leaflet (docs/modules/maps.md, UI): `CRS.Simple` with the image as an
 * overlay over its own pixel bounds, pins as kind-icon markers (faded when ghosts) that cluster
 * when crowded, a tooltip on hover, `onSelect` on click (a click on the map clears it). Editing
 * (no clustering then): a click on the map places (`onPlace`), pins drag (`onMove`), and entities
 * dragged in (`ENTITY_DRAG_TYPE`) drop (`onDropEntity`). Loaded lazily with the map views
 * (frontend.md §12).
 */
export default function MapCanvas({
  image,
  width,
  height,
  markers,
  selected,
  focus = null,
  onSelect,
  editing = false,
  onPlace,
  onMove,
  onDropEntity,
}: {
  image: string
  width: number
  height: number
  markers: readonly CanvasMarker[]
  selected: string | null
  /** A pin to center on once it is drawn. */
  focus?: string | null
  onSelect: (id: string | null) => void
  editing?: boolean
  onPlace?: (point: Point) => void
  onMove?: (id: string, point: Point) => void
  onDropEntity?: (entity: string, point: Point) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)
  const focused = useRef<string | null>(null)
  // Leaflet markers take HTML: the icons render here, hidden, and markers copy their markup.
  const icons = useMemo(() => [...new Set(markers.map((marker) => marker.icon))], [markers])
  const glyphs = useRef<HTMLDivElement>(null)
  const handlers = useRef({ onSelect, onPlace, onMove, onDropEntity, editing })
  useEffect(() => {
    handlers.current = { onSelect, onPlace, onMove, onDropEntity, editing }
  }, [onSelect, onPlace, onMove, onDropEntity, editing])
  /** An image pixel of a map position, kept on the image. */
  const pointOf = (latlng: L.LatLng): Point => ({
    x: Math.round(Math.min(Math.max(latlng.lng, 0), width) * 10) / 10,
    y: Math.round(Math.min(Math.max(height - latlng.lat, 0), height) * 10) / 10,
  })

  useEffect(() => {
    const element = container.current
    if (element === null) return
    const bounds: L.LatLngBoundsExpression = [
      [0, 0],
      [height, width],
    ]
    const created = L.map(element, {
      crs: L.CRS.Simple,
      minZoom: -6,
      maxZoom: 4,
      zoomSnap: 0.25,
      attributionControl: false,
      maxBounds: L.latLngBounds(bounds).pad(0.5),
    })
    L.imageOverlay(image, bounds).addTo(created)
    created.fitBounds(bounds)
    created.on('click', (event: L.LeafletMouseEvent) => {
      // A marker's click reaches the map too: it selects, it doesn't clear or place.
      const target = event.originalEvent.target
      if (target instanceof Element && target.closest('.leaflet-marker-icon') !== null) return
      const { editing: placing, onPlace: place, onSelect: select } = handlers.current
      if (placing && place) place(pointOf(event.latlng))
      else select(null)
    })
    // Leaflet focuses the map on every press (keyboard navigation) and only restores the
    // window's scroll: a scrolling pane around the map would jump, and the press's target with it.
    const box = created.getContainer()
    const focus = box.focus.bind(box)
    box.focus = (options?: FocusOptions) => {
      focus({ ...options, preventScroll: true })
    }
    map.current = created
    focused.current = null
    return () => {
      created.remove()
      map.current = null
      layer.current = null
    }
    // pointOf reads width and height, which are deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [image, width, height])

  // Clusters when viewing; single markers when editing (so that each one drags).
  useEffect(() => {
    const created = map.current
    if (created === null) return
    const group = editing
      ? L.layerGroup()
      : L.markerClusterGroup({ maxClusterRadius: CLUSTER_RADIUS, showCoverageOnHover: false })
    group.addTo(created)
    layer.current = group
    return () => {
      group.remove()
      if (layer.current === group) layer.current = null
    }
  }, [editing, image, width, height])

  useEffect(() => {
    const group = layer.current
    if (group === null) return
    const rendered = glyphs.current?.children
    const glyphOf = (icon: CanvasMarker['icon']) => rendered?.[icons.indexOf(icon)]?.innerHTML ?? ''
    group.clearLayers()
    const drawn = markers.map((marker) =>
      L.marker(toLatLng(marker, height), {
        icon: markerIcon(marker, glyphOf(marker.icon), marker.id === selected),
        keyboard: true,
        title: marker.label,
        alt: marker.label,
        draggable: editing,
        // Focus comes with the mouse press: panning then would move the pin from under the
        // pointer before the release, and the click would land on the map.
        autoPanOnFocus: false,
        zIndexOffset: marker.ghost ? -1000 : 0,
      })
        .bindTooltip(marker.label, { direction: 'right' })
        .on('add', (event) => {
          // Nor may the page scroll to the focused pin (a pin near the bottom of the view).
          const element = (event.target as L.Marker).getElement()
          if (element === undefined) return
          L.DomEvent.on(element, 'mousedown', (down) => {
            down.preventDefault()
            element.focus({ preventScroll: true })
          })
        })
        .on('click', (event) => {
          L.DomEvent.stopPropagation(event)
          handlers.current.onSelect(marker.id)
        })
        .on('dragend', (event) => {
          const moved = event.target as L.Marker
          handlers.current.onMove?.(marker.id, pointOf(moved.getLatLng()))
        }),
    )
    if (group instanceof L.MarkerClusterGroup) group.addLayers(drawn)
    else for (const marker of drawn) group.addLayer(marker)
    const target = markers.find((marker) => marker.id === focus)
    if (target !== undefined && focused.current !== target.id) {
      focused.current = target.id
      map.current?.setView(toLatLng(target, height), Math.max(map.current.getZoom(), 0))
    }
    // pointOf reads width and height, which are deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markers, icons, selected, focus, height, image, width, editing])

  return (
    <>
      <div
        ref={container}
        className="size-full bg-muted"
        onDragOver={(event) => {
          if (editing && event.dataTransfer.types.includes(ENTITY_DRAG_TYPE)) event.preventDefault()
        }}
        onDrop={(event) => {
          const entity = event.dataTransfer.getData(ENTITY_DRAG_TYPE)
          const created = map.current
          if (!editing || entity === '' || created === null || container.current === null) return
          event.preventDefault()
          const rect = container.current.getBoundingClientRect()
          const at = created.containerPointToLatLng(
            L.point(event.clientX - rect.left, event.clientY - rect.top),
          )
          handlers.current.onDropEntity?.(entity, pointOf(at))
        }}
      />
      <div ref={glyphs} hidden>
        {icons.map((Icon, index) => (
          <span key={index}>
            <Icon className="size-3.5" aria-hidden />
          </span>
        ))}
      </div>
    </>
  )
}
