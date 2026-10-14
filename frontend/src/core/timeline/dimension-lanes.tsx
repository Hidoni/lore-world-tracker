import { toPx, viewport, type Viewport } from '@lore/chronology/viewport'
import { ChevronDownIcon, GlobeIcon, XIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { mapper, useDisplayLens, type CorrespondenceGraph } from '@/core/time'

import { EventLanes } from './event-lanes'
import type { Named } from './filters-panel'
import { GroupHeader, type LaneProps } from './lane-groups'
import { axisTicks } from './time-axis'
import { useTimelineWindow, type SeriesBand, type WindowItem } from './use-timeline-window'

/** Where the lane samples the view to find what the other dimension shows of it. */
const SAMPLES = 64n
export const DIMENSION_TICKS_HEIGHT = 26

/**
 * The moments of the other dimension a view of this one corresponds to (`null`: none): the
 * smallest and largest mapped moment over the view's ends and evenly spaced samples (a mapping
 * that is undefined at an end can still cover part of the view).
 */
export function mappedRange(
  v: Viewport,
  toOther: (t: bigint) => bigint | null,
): readonly [bigint, bigint] | null {
  let lo: bigint | null = null
  let hi: bigint | null = null
  for (let i = 0n; i <= SAMPLES; i++) {
    const t = toOther(v.start + (v.span * i) / SAMPLES)
    if (t === null) continue
    if (lo === null || t < lo) lo = t
    if (hi === null || t > hi) hi = t
  }
  return lo === null || hi === null ? null : [lo, hi > lo ? hi : lo + 1n]
}

/**
 * Items of the other dimension placed on this axis (warped): each start and end mapped back
 * through the correspondences; items whose start has no corresponding moment are left out, and
 * an end without one becomes the start (an instant).
 */
export function mapItems(
  items: readonly WindowItem[],
  toHere: (t: bigint) => bigint | null,
): WindowItem[] {
  return items.flatMap((item) => {
    const start = item.start_t === null ? null : toHere(item.start_t)
    if (start === null) return []
    const mappedEnd = item.end_t === null ? null : toHere(item.end_t)
    const end = mappedEnd === null || mappedEnd < start ? start : mappedEnd
    return [{ ...item, start_t: start, end_t: end }]
  })
}

function mapBands(bands: readonly SeriesBand[], toHere: (t: bigint) => bigint | null) {
  return bands.flatMap((band) => {
    const from = toHere(band.from)
    const to = toHere(band.to)
    return from === null || to === null || to < from ? [] : [{ ...band, from, to }]
  })
}

/**
 * The timeline's "Add dimension lane" control (frontend.md §9.5): the dimensions reachable from
 * this one through correspondences, each shown as a lane of its own when checked. Hidden when
 * there are none.
 */
export function DimensionLaneMenu({
  options,
  value,
  onChange,
}: {
  options: readonly Named[]
  value: readonly string[]
  onChange: (next: string[]) => void
}) {
  if (options.length === 0) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant={value.length > 0 ? 'secondary' : 'outline'}
          size="sm"
          aria-label={value.length > 0 ? `Dimension lanes: ${value.length}` : 'Add dimension lane'}
        >
          <GlobeIcon aria-hidden /> Dimensions
          {value.length > 0 && <span className="text-xs">({value.length})</span>}
          <ChevronDownIcon aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Add dimension lane</DropdownMenuLabel>
        {options.map((option) => (
          <DropdownMenuCheckboxItem
            key={option.id}
            checked={value.includes(option.id)}
            onSelect={(event) => {
              event.preventDefault()
            }}
            onCheckedChange={(checked) => {
              onChange(checked ? [...value, option.id] : value.filter((each) => each !== option.id))
            }}
          >
            {option.name}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** The other dimension's calendar ticks, placed where they correspond on this axis. */
function DimensionTicks({
  v,
  ticks,
}: {
  v: Viewport
  ticks: readonly { key: string; x: number; label: string; major: boolean }[]
}) {
  return (
    <svg
      width={v.widthPx}
      height={DIMENSION_TICKS_HEIGHT}
      className="block text-muted-foreground select-none"
      data-testid="dimension-ticks"
      aria-hidden
    >
      <line x1={0} x2={v.widthPx} y1={4} y2={4} className="stroke-border" />
      {ticks.map((tick) => (
        <g key={tick.key} data-testid="dimension-tick">
          <line
            x1={tick.x}
            x2={tick.x}
            y1={0}
            y2={tick.major ? 12 : 8}
            className={tick.major ? 'stroke-foreground/50' : 'stroke-foreground/25'}
          />
          {tick.label !== '' && (
            <text
              x={tick.x + 2}
              y={20}
              className={`text-[10px] ${tick.major ? 'fill-foreground' : 'fill-muted-foreground'}`}
            >
              {tick.label}
            </text>
          )}
        </g>
      ))}
    </svg>
  )
}

/**
 * A dimension lane (frontend.md §9.5): another dimension's events (its prime timeline) mapped
 * onto this axis through the correspondences, warped where time flows at different rates, with a
 * row of that dimension's calendar ticks where they correspond. Read-only; opening an event still
 * works.
 */
export function DimensionLaneGroup({
  vault,
  graph,
  dimensionId,
  other,
  lane,
  onRemove,
}: {
  vault: string
  graph: CorrespondenceGraph
  /** This timeline's dimension. */
  dimensionId: string
  other: Named
  lane: LaneProps
  onRemove: () => void
}) {
  const { v } = lane
  const { dimension, lens } = useDisplayLens(vault, other.id)
  const toOther = mapper(graph, dimensionId, other.id)
  const toHere = mapper(graph, other.id, dimensionId)
  const range = toOther === null ? null : mappedRange(v, toOther)
  const otherV = range === null ? v : viewport(range[0], range[1] - range[0], v.widthPx)
  const timeline = range === null ? null : (dimension?.primeTimelineId ?? null)
  const { window: data, loading } = useTimelineWindow(
    vault,
    timeline,
    otherV,
    dimension?.duration ?? 1n,
  )
  const items = toHere === null ? [] : mapItems(data.items, toHere)
  const bands = toHere === null ? [] : mapBands(data.bands, toHere)
  const ticks = (() => {
    if (range === null || toHere === null || dimension === null || lens === null) return []
    const found = axisTicks(lens.calendar, otherV, dimension.baseUnit)
    return [
      ...found.major.map((tick) => ({ tick, major: true })),
      ...found.minor.map((tick) => ({ tick, major: false })),
    ].flatMap(({ tick, major }) => {
      const t = toHere(tick.t)
      if (t === null) return []
      const x = toPx(v, t)
      return x < 0 || x > v.widthPx
        ? []
        : [{ key: `${major ? 'M' : 'm'}${tick.t}`, x, label: major ? tick.label : '', major }]
    })
  })()
  const readOnly: LaneProps = {
    ...lane,
    drag: null,
    locked: null,
    onPress: undefined,
    onMenu: undefined,
    onDropEntity: undefined,
    highlight: null,
  }
  return (
    <section aria-label={`Dimension: ${other.name}`} data-testid="dimension-lane">
      <GroupHeader
        label={`${other.name} (mapped)`}
        actions={
          <button
            type="button"
            aria-label={`Remove the ${other.name} lane`}
            className="rounded p-0.5 hover:text-foreground"
            onClick={onRemove}
          >
            <XIcon aria-hidden className="size-3" />
          </button>
        }
      />
      <DimensionTicks v={v} ticks={ticks} />
      {range === null ? (
        <p className="px-2 py-1 text-xs text-muted-foreground">
          Nothing in {other.name} corresponds to this stretch of time.
        </p>
      ) : items.length === 0 && bands.length === 0 ? (
        <p className="px-2 py-1 text-xs text-muted-foreground">
          {loading ? 'Loading…' : 'No events here.'}
        </p>
      ) : (
        <EventLanes {...readOnly} items={items} bands={bands} />
      )}
    </section>
  )
}
