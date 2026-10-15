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
 * when crowded, a tooltip on hover, `onSelect` on click (a click on the map clears it). Loaded
 * lazily with the map views (frontend.md §12).
 */
export default function MapCanvas({
  image,
  width,
  height,
  markers,
  selected,
  focus = null,
  onSelect,
}: {
  image: string
  width: number
  height: number
  markers: readonly CanvasMarker[]
  selected: string | null
  /** A pin to center on once it is drawn. */
  focus?: string | null
  onSelect: (id: string | null) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.MarkerClusterGroup | null>(null)
  const focused = useRef<string | null>(null)
  // Leaflet markers take HTML: the icons render here, hidden, and markers copy their markup.
  const icons = useMemo(() => [...new Set(markers.map((marker) => marker.icon))], [markers])
  const glyphs = useRef<HTMLDivElement>(null)
  const select = useRef(onSelect)
  useEffect(() => {
    select.current = onSelect
  }, [onSelect])

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
    created.on('click', () => {
      select.current(null)
    })
    const clusters = L.markerClusterGroup({
      maxClusterRadius: CLUSTER_RADIUS,
      showCoverageOnHover: false,
    })
    clusters.addTo(created)
    map.current = created
    layer.current = clusters
    focused.current = null
    return () => {
      created.remove()
      map.current = null
      layer.current = null
    }
  }, [image, width, height])

  useEffect(() => {
    const clusters = layer.current
    if (clusters === null) return
    const rendered = glyphs.current?.children
    const glyphOf = (icon: CanvasMarker['icon']) => rendered?.[icons.indexOf(icon)]?.innerHTML ?? ''
    clusters.clearLayers()
    clusters.addLayers(
      markers.map((marker) =>
        L.marker(toLatLng(marker, height), {
          icon: markerIcon(marker, glyphOf(marker.icon), marker.id === selected),
          keyboard: true,
          title: marker.label,
          alt: marker.label,
          zIndexOffset: marker.ghost ? -1000 : 0,
        })
          .bindTooltip(marker.label, { direction: 'right' })
          .on('click', (event) => {
            L.DomEvent.stopPropagation(event)
            select.current(marker.id)
          }),
      ),
    )
    const target = markers.find((marker) => marker.id === focus)
    if (target !== undefined && focused.current !== target.id) {
      focused.current = target.id
      map.current?.setView(toLatLng(target, height), Math.max(map.current.getZoom(), 0))
    }
  }, [markers, icons, selected, focus, height, image, width])

  return (
    <>
      <div ref={container} className="size-full bg-muted" />
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
