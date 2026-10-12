import { toPx, type Viewport } from '@lore/chronology/viewport'
import { memo, useMemo, useState } from 'react'

import type { Lens } from '@/core/time'
import { cn } from '@/lib/utils'

import { itemGeometry, spanBackground, type ItemGeometry } from './geometry'
import { StickyLanes } from './lanes'
import { bandShapes, SeriesBandShape } from './series-bands'
import { itemKey, type SeriesBand, type WindowBucket, type WindowItem } from './use-timeline-window'

export const LANE_HEIGHT = 22
/** Items drawn at most (frontend.md §9.3: one element each, ≤ 1,500 nodes in all). */
export const MAX_DRAWN = 1400
/** Pixels laid out beyond each side of the viewport. */
const MARGIN_PX = 200

/** Bar colour per importance (1–5): stronger for more important events, light enough for labels. */
const COLORS: Record<number, string> = {
  1: 'color-mix(in oklab, var(--primary) 12%, transparent)',
  2: 'color-mix(in oklab, var(--primary) 18%, transparent)',
  3: 'color-mix(in oklab, var(--primary) 25%, transparent)',
  4: 'color-mix(in oklab, var(--primary) 33%, transparent)',
  5: 'color-mix(in oklab, var(--primary) 42%, transparent)',
}

/** The marker of a materialized occurrence with sub-events: a dot at its top-left corner. */
const SUB_EVENTS_MARKER =
  'after:absolute after:top-0 after:left-0 after:size-1.5 after:rounded-full after:bg-amber-500'

interface Drawn {
  key: string
  item: WindowItem
  geometry: ItemGeometry
}

/**
 * The viewport items are laid out in. Panning less than half a width only moves the lanes (one
 * transform); a zoom, a resize or a longer pan lays them out again.
 */
class Anchor {
  private v: Viewport | null = null

  for(v: Viewport): Viewport {
    const anchor = this.v
    const keep =
      anchor?.span === v.span &&
      anchor.widthPx === v.widthPx &&
      Math.abs(toPx(v, anchor.start)) <= v.widthPx / 2
    if (keep) return anchor
    this.v = v
    return v
  }
}

/** The items to draw around the anchor (with room to pan), the most important when over budget. */
function visible(items: readonly WindowItem[], anchor: Viewport, lenses: readonly Lens[]): Drawn[] {
  const margin = MARGIN_PX + anchor.widthPx / 2
  const drawn: Drawn[] = []
  for (const item of items) {
    const geometry = itemGeometry(item, anchor, lenses)
    if (geometry === null) continue
    if (geometry.x1 < -margin || geometry.x0 > anchor.widthPx + margin) continue
    drawn.push({ key: itemKey(item), item, geometry })
  }
  if (drawn.length > MAX_DRAWN) {
    drawn.sort((a, b) => b.item.importance - a.item.importance)
    drawn.length = MAX_DRAWN
  }
  return drawn
}

interface ItemProps {
  drawn: Drawn
  top: number
  selected: boolean
  limit: { left: number; right: number }
  onSelect: (key: string | null) => void
  onOpen: (item: WindowItem) => void
}

/** One item: a single element (spans: a bar with a gradient; instants: a diamond pseudo-element). */
const Item = memo(function Item({ drawn, top, selected, limit, onSelect, onOpen }: ItemProps) {
  const { key, item, geometry } = drawn
  const occurrence = item.occurrence_key !== null
  // A materialized occurrence with sub-events of its own (recurrence.md §10).
  const subEvents = occurrence && item.occurrence_state !== null && item.has_children
  const handlers = {
    'data-item': key,
    'data-kind': geometry.kind,
    'data-occurrence': occurrence ? item.occurrence_key : undefined,
    'data-sub-events': subEvents ? '' : undefined,
    title: subEvents ? `${item.name} (has sub-events)` : undefined,
    'aria-label': item.name,
    'aria-pressed': selected,
    onClick: (event: React.MouseEvent) => {
      event.stopPropagation()
      onSelect(key)
    },
    onDoubleClick: (event: React.MouseEvent) => {
      event.stopPropagation()
      onOpen(item)
    },
    // Pressing an item doesn't start a pan.
    onPointerDown: (event: React.PointerEvent) => {
      event.stopPropagation()
    },
  }
  if (geometry.kind === 'instant') {
    return (
      <button
        type="button"
        tabIndex={-1}
        {...handlers}
        className={cn(
          'absolute max-w-44 truncate pl-4 text-left text-[11px] whitespace-nowrap',
          // Occurrences of a series are ticks; other instants, diamonds.
          occurrence
            ? 'before:absolute before:inset-y-0 before:left-[7px] before:w-0.5 before:bg-primary'
            : 'before:absolute before:top-1/2 before:left-[3px] before:size-2.5 before:-translate-y-1/2 before:rotate-45 before:bg-primary',
          subEvents && SUB_EVENTS_MARKER,
          selected && 'rounded-sm ring-2 ring-ring',
          item.occurrence_state === 'cancelled' && 'line-through opacity-60',
        )}
        style={{
          transform: `translate(${geometry.x0 - 8}px, ${top}px)`,
          height: LANE_HEIGHT - 4,
        }}
      >
        {item.name}
      </button>
    )
  }
  const left = Math.max(geometry.x0, limit.left)
  const right = Math.min(geometry.x1, limit.right)
  const color = COLORS[item.importance] ?? COLORS[3] ?? 'var(--primary)'
  return (
    <button
      type="button"
      tabIndex={-1}
      {...handlers}
      className={cn(
        'absolute overflow-hidden rounded-sm px-1 text-left text-[11px] whitespace-nowrap text-foreground',
        subEvents && SUB_EVENTS_MARKER,
        selected && 'ring-2 ring-ring',
        item.occurrence_state === 'cancelled' && 'line-through opacity-60',
      )}
      style={{
        transform: `translate(${left}px, ${top}px)`,
        width: Math.max(2, right - left),
        height: LANE_HEIGHT - 4,
        background: spanBackground(
          {
            ...geometry,
            x0: left,
            x1: right,
            fadeIn: left > geometry.x0 ? 0 : geometry.fadeIn,
            fadeOut: right < geometry.x1 ? 0 : geometry.fadeOut,
          },
          color,
        ),
      }}
    >
      {item.name}
    </button>
  )
})

/**
 * The event lanes (frontend.md §9.3): each item one element, placed by sticky lane packing.
 * Spans are bars whose edges fade over their uncertainty (a CSS gradient); instants are
 * diamonds; series with too many occurrences are hatched bands with their count. Labels truncate
 * to the bar. Click selects, double-click opens. Items are laid out against an anchor viewport
 * and panning moves them together, so a pan doesn't re-render them; a zoom lays them out again
 * from a deferred view, scaling the old layout meanwhile.
 */
export function EventLanes({
  v,
  layoutV,
  lenses,
  items,
  bands,
  selected,
  onSelect,
  onOpen,
}: {
  /** The current view. */
  v: Viewport
  /** The view to lay items out for (deferred: it may lag `v` while zooming). */
  layoutV: Viewport
  lenses: readonly Lens[]
  items: readonly WindowItem[]
  bands: readonly SeriesBand[]
  selected: string | null
  onSelect: (key: string | null) => void
  onOpen: (item: WindowItem) => void
}) {
  const [anchors] = useState(() => new Anchor())
  const [lanes] = useState(() => new StickyLanes())
  const anchor = anchors.for(layoutV)
  const drawn = useMemo(() => visible(items, anchor, lenses), [items, anchor, lenses])
  const limit = useMemo(
    () => ({
      left: -MARGIN_PX - anchor.widthPx / 2,
      right: anchor.widthPx * 1.5 + MARGIN_PX,
    }),
    [anchor],
  )
  const shapes = useMemo(() => bandShapes(bands, anchor), [bands, anchor])
  const packing = useMemo(
    () =>
      lanes.pack([
        ...shapes.map(({ key, x0, x1 }) => ({ key, x0, x1 })),
        ...drawn.map(({ key, geometry }) => ({
          key,
          x0: geometry.kind === 'instant' ? geometry.x0 - 8 : geometry.x0,
          x1: geometry.kind === 'instant' ? geometry.x0 + 8 : geometry.x1,
        })),
      ]),
    [drawn, shapes, lanes],
  )
  const lane = (key: string) => packing.lanes.get(key) ?? 0
  const elements = useMemo(
    () =>
      drawn.map((each) => (
        <Item
          key={each.key}
          drawn={each}
          top={(packing.lanes.get(each.key) ?? 0) * LANE_HEIGHT + 4}
          selected={each.key === selected}
          limit={limit}
          onSelect={onSelect}
          onOpen={onOpen}
        />
      )),
    [drawn, packing, selected, limit, onSelect, onOpen],
  )
  // The laid-out items moved (and, while a zoom's layout catches up, scaled) to the current view.
  const shift = toPx(v, anchor.start)
  const scale = (toPx(v, anchor.start + anchor.span) - shift) / anchor.widthPx

  return (
    <div
      className="relative"
      style={{ height: Math.max(1, packing.count) * LANE_HEIGHT + 8, width: v.widthPx }}
    >
      <div
        data-testid="lanes-layer"
        className="absolute inset-y-0 left-0"
        style={{
          transform:
            Math.abs(scale - 1) < 1e-6
              ? `translateX(${shift}px)`
              : `translateX(${shift}px) scaleX(${scale})`,
          transformOrigin: '0 0',
          width: anchor.widthPx,
        }}
      >
        {shapes.map((shape) => (
          <SeriesBandShape
            key={shape.key}
            shape={shape}
            top={lane(shape.key) * LANE_HEIGHT + 4}
            height={LANE_HEIGHT - 4}
            limit={limit}
          />
        ))}
        {elements}
      </div>
    </div>
  )
}

/**
 * Where the server culled events (frontend.md §9.2): a strip of the window's buckets, shaded by the
 * culled events covering them (`active`), with a tick for those starting there (`starts`, "+N").
 */
export function DensityStrip({ v, buckets }: { v: Viewport; buckets: readonly WindowBucket[] }) {
  const most = Math.max(1, ...buckets.map((bucket) => bucket.active))
  return (
    <div
      role="img"
      aria-label="Culled events"
      className="relative h-3 overflow-hidden"
      style={{ width: v.widthPx }}
    >
      {buckets.map((bucket) => {
        const x0 = toPx(v, bucket.from)
        const x1 = toPx(v, bucket.to)
        if (x1 < 0 || x0 > v.widthPx) return null
        return (
          <div
            key={`${bucket.from}:${bucket.to}`}
            data-testid="density-bucket"
            title={bucket.starts > 0 ? `+${bucket.starts}` : undefined}
            className="absolute top-0 h-full bg-primary"
            style={{
              transform: `translateX(${x0}px)`,
              width: Math.max(1, x1 - x0),
              opacity: 0.1 + 0.6 * (bucket.active / most),
            }}
          />
        )
      })}
    </div>
  )
}
