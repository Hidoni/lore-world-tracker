import { DateError, fromFields, unitBounds, type TimePoint } from '@lore/chronology'
import { toPx, type Viewport } from '@lore/chronology/viewport'
import { useSearch } from '@tanstack/react-router'
import { LocateIcon, MaximizeIcon, ZoomInIcon, ZoomOutIcon } from 'lucide-react'
import {
  useCallback,
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

import { Minimap } from './minimap'
import { PerfOverlay, perfEnabled } from './perf-overlay'
import { capture, release } from './pointer'
import { axisTicks, TimeAxis } from './time-axis'
import { useViewport, zoomFactor, type ViewportControls } from './use-viewport'

const LANES_HEIGHT = 240
const DEFAULT_WIDTH = 960
const MODIFIER_KEY = 'lore.timeline.zoomModifier'

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
 * drag, keyboard (+/−, Home, ←/→, G) and toolbar controls. Event lanes come with #81.
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
    <Timeline vault={vault} dimension={dimension} lens={context.lens} lenses={context.lenses} />
  )
}

function Timeline({
  dimension,
  lens,
  lenses,
}: {
  vault: string
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
  const drag = useRef<{ x: number } | null>(null)
  const lanes = useRef<HTMLDivElement>(null)

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
    const step = event.shiftKey ? v.widthPx / 2 : v.widthPx / 10
    switch (event.key) {
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
        controls.pan(-step)
        break
      case 'ArrowRight':
        controls.pan(step)
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
        className="relative flex flex-col gap-1 rounded-md border outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <TimeAxis v={v} found={found} />
        <div
          ref={lanes}
          data-testid="timeline-lanes"
          className="relative cursor-grab touch-none active:cursor-grabbing"
          style={{ height: LANES_HEIGHT }}
          onPointerDown={(event) => {
            drag.current = { x: event.clientX }
            capture(event.currentTarget, event.pointerId)
          }}
          onPointerMove={(event) => {
            if (drag.current === null) return
            const dx = event.clientX - drag.current.x
            drag.current = { x: event.clientX }
            if (dx !== 0) controls.pan(-dx)
          }}
          onPointerUp={(event) => {
            drag.current = null
            release(event.currentTarget, event.pointerId)
          }}
        >
          <svg width={v.widthPx} height={LANES_HEIGHT} className="block" aria-hidden>
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
          <p className="pointer-events-none absolute inset-x-0 top-1/2 text-center text-xs text-muted-foreground">
            Events appear here with the next timeline layers.
          </p>
        </div>
        <Minimap D={dimension.duration} v={v} onCenter={controls.center} />
        {perfEnabled(search) && <PerfOverlay renders={readRenders} />}
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
