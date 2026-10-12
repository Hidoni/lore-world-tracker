import { DateError, fromFields, unitBounds, type TimePoint } from '@lore/chronology'
import { toPx, type Viewport } from '@lore/chronology/viewport'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { LocateIcon, MaximizeIcon, ZoomInIcon, ZoomOutIcon } from 'lucide-react'
import {
  startTransition,
  useCallback,
  useDeferredValue,
  useMemo,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  formatIn,
  TimePointPicker,
  useTimeContext,
  type DimensionTime,
  type Lens,
} from '@/core/time'
import { useMaterializeOccurrence } from '@/data'

import { DensityStrip, EventLanes } from './event-lanes'
import { Minimap } from './minimap'
import { PerfOverlay, perfEnabled } from './perf-overlay'
import { capture, release } from './pointer'
import { isComputedOccurrence, SelectionPreview } from './selection-preview'
import { axisTicks, TimeAxis } from './time-axis'
import { itemKey, useTimelineWindow, type WindowItem } from './use-timeline-window'
import { useViewport, zoomFactor, type ViewportControls } from './use-viewport'

const LANES_HEIGHT = 320
const DEFAULT_WIDTH = 960
const MODIFIER_KEY = 'lore.timeline.zoomModifier'

/** How long a zoom pauses before the lanes lay out again. */
const ZOOM_SETTLE_MS = 120

/**
 * The viewport the lanes are laid out for: the current one, except during a zoom, when the last
 * layout stays (scaled) until the zoom pauses or the scale passes ×4 or ¼.
 */
class LayoutView {
  private settled: Viewport | null = null

  for(v: Viewport): Viewport {
    const settled = this.settled
    if (settled?.widthPx !== v.widthPx || settled.span === v.span) {
      this.settled = v
      return v
    }
    const scale = (toPx(v, settled.start + settled.span) - toPx(v, settled.start)) / settled.widthPx
    if (scale > 4 || scale < 0.25) {
      this.settled = v
      return v
    }
    return settled
  }

  settle(v: Viewport): void {
    this.settled = v
  }
}

/** The items the lanes show: held while a zoom is under way (its layout is held too). */
class HeldItems {
  private items: readonly WindowItem[] = []

  for(items: readonly WindowItem[], zooming: boolean): readonly WindowItem[] {
    if (!zooming || this.items.length === 0) this.items = items
    return this.items
  }
}

/** When the wheel zooms: always, or with Ctrl/⌘ held (the wheel then pans). */
export type ZoomModifier = 'none' | 'ctrl'

function readModifier(): ZoomModifier {
  try {
    return localStorage.getItem(MODIFIER_KEY) === 'ctrl' ? 'ctrl' : 'none'
  } catch {
    return 'none'
  }
}

/** The moment range a time point stands for: the unit at its precision (or the moment). */
export function pointRange(
  point: TimePoint,
  lenses: readonly Lens[],
): { start: bigint; end: bigint } | null {
  const anchor = point.anchor
  if (anchor.kind === 'absolute') {
    const t = BigInt(anchor.t)
    return { start: t, end: t }
  }
  if (anchor.kind !== 'calendar') return null
  const calendar = lenses.find((lens) => lens.id === anchor.calendar_id)?.calendar ?? null
  if (calendar === null) return null
  try {
    const t = fromFields(calendar, anchor.fields, point.precision)
    if (point.precision === 'base' || calendar.levelIndex(point.precision) < 0) {
      return { start: t, end: t }
    }
    const bounds = unitBounds(calendar, t, point.precision)
    return { start: bounds.start, end: bounds.end }
  } catch (error) {
    if (error instanceof DateError) return null
    throw error
  }
}

function GoToDialog({
  dimension,
  lenses,
  onGo,
  onClose,
}: {
  dimension: DimensionTime
  lenses: readonly Lens[]
  onGo: (start: bigint, end: bigint) => void
  onClose: () => void
}) {
  const [point, setPoint] = useState<TimePoint | null>(null)
  const range = point === null ? null : pointRange(point, lenses)
  const go = () => {
    if (range === null) return
    onGo(range.start, range.end)
    onClose()
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Go to a date</DialogTitle>
          <DialogDescription>
            The timeline shows the unit you pick (a year, a day…).
          </DialogDescription>
        </DialogHeader>
        <TimePointPicker
          dimension={dimension}
          lenses={lenses}
          value={null}
          label="Date"
          onChange={setPoint}
          onConfirm={() => {
            go()
          }}
        />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={range === null} onClick={go}>
            Go
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** The container's width, followed with a `ResizeObserver` (a default where there is none). */
function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(DEFAULT_WIDTH)
  useLayoutEffect(() => {
    const element = ref.current
    if (element === null) return
    const measure = () => {
      const measured = Math.floor(element.clientWidth)
      if (measured > 0) setWidth(measured)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => {
      observer.disconnect()
    }
  }, [])
  return [ref, width]
}

function RangeLabel({
  v,
  lens,
  dimension,
  lenses,
  level,
  major,
}: {
  v: Viewport
  lens: Lens
  dimension: DimensionTime
  lenses: readonly Lens[]
  level: string
  /** The axis' first major label: exact where the display format rounds (huge years). */
  major: string | null
}) {
  const at = (t: bigint) =>
    formatIn(lens, { t, precision: level }, dimension, lenses) ?? t.toString()
  const start = at(v.start)
  const end = at(v.start + v.span)
  return (
    <p aria-live="polite" className="text-sm text-muted-foreground" data-testid="timeline-range">
      {start === end ? (major ?? start) : `${start} – ${end}`}
    </p>
  )
}

/**
 * The timeline view of a dimension (`/v/$vault/d/$dimension/timeline`, frontend.md §9): an exact
 * viewport from the whole dimension down to a few base units (`@lore/chronology/viewport`), kept
 * in the URL (`from`, `to`), with the time axis in the display calendar, a minimap, and wheel,
 * drag, keyboard (+/−, Home, ←/→, G) and toolbar controls; the timeline's events in lanes (#81),
 * tile by tile, with the density of what the server culled; ↑/↓ select items, Enter opens.
 */
export function TimelineView({ vault, dimensionId }: { vault: string; dimensionId: string }) {
  const context = useTimeContext(vault)
  const dimension = context.dimensionId === dimensionId ? context.dimension : null
  if (dimension === null || context.lens === null) {
    return (
      <div className="flex flex-col gap-3 p-6">
        <h1 className="text-2xl font-semibold">Timeline</h1>
        <p className="text-sm text-muted-foreground">Loading the dimension…</p>
      </div>
    )
  }
  return (
    <Timeline
      vault={vault}
      timelineId={context.timelineId}
      dimension={dimension}
      lens={context.lens}
      lenses={context.lenses}
    />
  )
}

function Timeline({
  vault,
  timelineId,
  dimension,
  lens,
  lenses,
}: {
  vault: string
  timelineId: string | null
  dimension: DimensionTime
  lens: Lens
  lenses: readonly Lens[]
}) {
  const [ref, width] = useWidth()
  const controls: ViewportControls = useViewport(dimension.duration, width)
  const v = controls.viewport
  const search: { perf?: unknown } = useSearch({ strict: false })
  const renders = useRef(0)
  useEffect(() => {
    renders.current += 1
  })
  const readRenders = useCallback(() => renders.current, [])
  const [modifier, setModifier] = useState<ZoomModifier>(readModifier)
  const [goTo, setGoTo] = useState(false)
  const drag = useRef<{ x: number; moved: number } | null>(null)
  const lanes = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const materialize = useMaterializeOccurrence(vault)
  const { window: data, loading } = useTimelineWindow(vault, timelineId, v, dimension.duration)
  const [selected, setSelected] = useState<string | null>(null)
  // While a zoom goes on, the lanes keep their layout (scaled to the view) and lay out again once
  // it pauses or the scale passes ×4 or ¼: zooming stays smooth with many items.
  const [layouts] = useState(() => new LayoutView())
  const layoutV = layouts.for(v)
  const [, settle] = useState(0)
  useEffect(() => {
    if (layoutV === v) return
    const timer = setTimeout(() => {
      layouts.settle(v)
      // Laying out again is a transition: React renders it in slices between frames.
      startTransition(() => {
        settle((n) => n + 1)
      })
    }, ZOOM_SETTLE_MS)
    return () => {
      clearTimeout(timer)
    }
  }, [v, layoutV, layouts])
  // New tiles' items wait for the zoom to settle too, then lay out at transition priority.
  const [held] = useState(() => new HeldItems())
  const laneItems = useDeferredValue(held.for(data.items, layoutV !== v))
  const byStart = useMemo(
    () =>
      [...data.items].sort((a, b) =>
        (a.start_t ?? 0n) < (b.start_t ?? 0n) ? -1 : (a.start_t ?? 0n) > (b.start_t ?? 0n) ? 1 : 0,
      ),
    [data.items],
  )
  const selectedItem = byStart.find((item) => itemKey(item) === selected) ?? null
  const materializeOccurrence = materialize.mutate
  const open = useCallback(
    (item: WindowItem) => {
      if (isComputedOccurrence(item) && item.occurrence_key !== null) {
        materializeOccurrence(
          { event: item.entity_id, key: item.occurrence_key },
          {
            onSuccess: (result) => {
              void navigate({
                to: '/v/$vault/e/$entity',
                params: { vault, entity: result.entity.id },
              })
            },
          },
        )
        return
      }
      void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: item.entity_id } })
    },
    [materializeOccurrence, navigate, vault],
  )
  /** Selects the item before (−1) or after (+1) the selected one by start, bringing it into view. */
  const step = (direction: 1 | -1) => {
    if (byStart.length === 0) return
    const at = selectedItem === null ? -1 : byStart.indexOf(selectedItem)
    const next = byStart[at < 0 ? (direction === 1 ? 0 : byStart.length - 1) : at + direction]
    if (next === undefined) return
    setSelected(itemKey(next))
    if (next.start_t !== null && (next.start_t < v.start || next.start_t >= v.start + v.span)) {
      controls.center(next.start_t)
    }
  }

  // Wheel: zoom at the cursor (or pan, without the modifier). Native, to prevent page scrolling.
  const latest = useRef({ controls, modifier })
  useLayoutEffect(() => {
    latest.current = { controls, modifier }
  })
  useEffect(() => {
    const element = lanes.current
    if (element === null) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const { controls: current, modifier: mode } = latest.current
      const zooming = mode === 'none' || event.ctrlKey || event.metaKey
      const box = element.getBoundingClientRect()
      if (zooming && event.deltaY !== 0) {
        current.zoom(event.clientX - box.left, zoomFactor(event.deltaY / 300))
      } else {
        current.pan(event.deltaX !== 0 ? event.deltaX : event.deltaY)
      }
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      element.removeEventListener('wheel', onWheel)
    }
  }, [])

  const found = axisTicks(lens.calendar, v, dimension.baseUnit)
  const level = found.major[0]?.level ?? found.minor[0]?.level ?? 'base'
  const centerX = v.widthPx / 2

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const distance = event.shiftKey ? v.widthPx / 2 : v.widthPx / 10
    switch (event.key) {
      case 'ArrowDown':
        step(1)
        break
      case 'ArrowUp':
        step(-1)
        break
      case 'Enter':
        if (selectedItem === null) return
        open(selectedItem)
        break
      case 'Escape':
        setSelected(null)
        break
      case '+':
      case '=':
        controls.zoom(centerX, zoomFactor(-1))
        break
      case '-':
      case '_':
        controls.zoom(centerX, zoomFactor(1))
        break
      case 'Home':
        controls.fitAll()
        break
      case 'ArrowLeft':
        controls.pan(-distance)
        break
      case 'ArrowRight':
        controls.pan(distance)
        break
      case 'g':
      case 'G':
        setGoTo(true)
        break
      default:
        return
    }
    event.preventDefault()
  }

  return (
    <div className="flex flex-col gap-3 p-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-semibold">Timeline</h1>
        <RangeLabel
          v={v}
          lens={lens}
          dimension={dimension}
          lenses={lenses}
          level={level}
          major={found.major[0]?.label ?? null}
        />
        <div className="flex-1" />
        <Button
          variant="outline"
          size="icon"
          aria-label="Zoom in"
          onClick={() => {
            controls.zoom(centerX, zoomFactor(-1))
          }}
        >
          <ZoomInIcon aria-hidden />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="Zoom out"
          onClick={() => {
            controls.zoom(centerX, zoomFactor(1))
          }}
        >
          <ZoomOutIcon aria-hidden />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="Fit the dimension"
          onClick={controls.fitAll}
        >
          <MaximizeIcon aria-hidden />
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setGoTo(true)
          }}
        >
          <LocateIcon aria-hidden /> Go to…
        </Button>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          Wheel
          <select
            aria-label="Wheel zooms"
            className="h-8 rounded-md border border-input bg-transparent px-1 text-xs"
            value={modifier}
            onChange={(event) => {
              const next = event.target.value as ZoomModifier
              setModifier(next)
              try {
                localStorage.setItem(MODIFIER_KEY, next)
              } catch {
                // Remembering is a convenience.
              }
            }}
          >
            <option value="none">zooms</option>
            <option value="ctrl">pans (Ctrl zooms)</option>
          </select>
        </label>
      </div>
      <div className="flex items-start gap-3">
        {/* A custom keyboard widget: `application` hands the keys to it (frontend.md §9.6). */}
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
        <div
          ref={ref}
          role="application"
          aria-label="Timeline"
          aria-roledescription="timeline"
          // Keyboard: +/− zoom, Home fits the dimension, ←/→ pan (Shift: further), G goes to a date.
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          tabIndex={0}
          onKeyDown={onKeyDown}
          className="relative flex min-w-0 flex-1 flex-col gap-1 rounded-md border outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <TimeAxis v={v} found={found} />
          <DensityStrip v={v} buckets={data.buckets} />
          <div
            ref={lanes}
            data-testid="timeline-lanes"
            className="relative cursor-grab touch-none overflow-x-hidden overflow-y-auto active:cursor-grabbing"
            style={{ height: LANES_HEIGHT }}
            onPointerDown={(event) => {
              drag.current = { x: event.clientX, moved: 0 }
              capture(event.currentTarget, event.pointerId)
            }}
            onPointerMove={(event) => {
              if (drag.current === null) return
              const dx = event.clientX - drag.current.x
              drag.current = { x: event.clientX, moved: drag.current.moved + Math.abs(dx) }
              if (dx !== 0) controls.pan(-dx)
            }}
            onPointerUp={(event) => {
              // A click on empty space (not a drag) clears the selection.
              if (
                drag.current !== null &&
                drag.current.moved < 3 &&
                event.target === event.currentTarget
              ) {
                setSelected(null)
              }
              drag.current = null
              release(event.currentTarget, event.pointerId)
            }}
          >
            <svg
              width={v.widthPx}
              height={LANES_HEIGHT}
              className="pointer-events-none absolute top-0 left-0"
              aria-hidden
            >
              {found.major.map((tick) => {
                const x = toPx(v, tick.t)
                return (
                  <line
                    key={tick.t.toString()}
                    x1={x}
                    x2={x}
                    y1={0}
                    y2={LANES_HEIGHT}
                    className="stroke-border"
                  />
                )
              })}
            </svg>
            <EventLanes
              v={v}
              layoutV={layoutV}
              lenses={lenses}
              items={laneItems}
              bands={data.bands}
              selected={selected}
              onSelect={setSelected}
              onOpen={open}
            />
            {data.items.length === 0 && data.bands.length === 0 && (
              <p className="pointer-events-none absolute inset-x-0 top-1/2 text-center text-xs text-muted-foreground">
                {loading ? 'Loading events…' : 'No events here.'}
              </p>
            )}
          </div>
          <p
            aria-live="polite"
            className="px-2 text-xs text-muted-foreground"
            data-testid="timeline-status"
          >
            {data.total} {data.total === 1 ? 'event' : 'events'}
            {data.culled > 0 ? `, ${data.culled} shown as density` : ''}
            {selectedItem !== null ? ` · selected: ${selectedItem.name}` : ''}
          </p>
          <Minimap D={dimension.duration} v={v} onCenter={controls.center} />
          {perfEnabled(search) && <PerfOverlay renders={readRenders} />}
        </div>
        {selectedItem !== null && (
          <SelectionPreview
            vault={vault}
            item={selectedItem}
            dimension={dimension}
            lens={lens}
            lenses={lenses}
            onOpen={open}
            onClose={() => {
              setSelected(null)
            }}
          />
        )}
      </div>
      {goTo && (
        <GoToDialog
          dimension={dimension}
          lenses={lenses}
          onGo={controls.show}
          onClose={() => {
            setGoTo(false)
          }}
        />
      )}
    </div>
  )
}
