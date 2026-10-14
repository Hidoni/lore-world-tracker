import { DateError, fromFields, unitBounds, type TimePoint } from '@lore/chronology'
import { fromPx, toPx, type Viewport } from '@lore/chronology/viewport'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import {
  ChevronRightIcon,
  ListIcon,
  LocateIcon,
  MaximizeIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from 'lucide-react'
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
  CreateBranchDialog,
  formatIn,
  reachableFrom,
  TimePointPicker,
  useBranching,
  useCorrespondenceGraph,
  useTimeContext,
  type Cursor,
  type DimensionTime,
  type Lens,
} from '@/core/time'
import { toast } from 'sonner'

import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import { droppedEntity } from '@/core/links'
import { eventTime } from '@/core/events'
import { useActiveModules } from '@/core/modules'
import {
  useDimensions,
  useEntity,
  useMaterializeOccurrence,
  useMutations,
  useUpdateLatest,
} from '@/data'

import { CompareMenu, DivergenceMarkers, useDifferences } from './compare'
import { CursorLine, TickSnap } from './cursor-line'
import { DimensionLaneGroup, DimensionLaneMenu } from './dimension-lanes'
import { dragTime, pointAt, type DragMode } from './drag-edit'
import { EraBands } from './era-bands'
import { DensityStrip, type DragPreview, type Drawn, type PressHandler } from './event-lanes'
import {
  FiltersPanel,
  GROUP_MODES,
  NO_FILTERS,
  windowFilters,
  type GroupMode,
  type Named,
  type TimelineFilters,
} from './filters-panel'
import {
  CompareGroup,
  GroupHeader,
  groupItems,
  LaneGroupView,
  ParticipantLane,
  SubEventGroup,
  type LaneGroup,
  type LaneProps,
} from './lane-groups'
import { Minimap } from './minimap'
import { OverlayStrip } from './overlay-strip'
import { PerfOverlay, perfEnabled } from './perf-overlay'
import { capture, release } from './pointer'
import { isComputedOccurrence, SelectionPreview } from './selection-preview'
import { axisTicks, TimeAxis } from './time-axis'
import { TimelineDialogs, type TimelineAction } from './timeline-dialogs'
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

/** Whether any of a group's items or bands overlaps the view. */
function inView(group: LaneGroup, v: Viewport): boolean {
  const end = v.start + v.span
  return (
    group.items.some(
      (item) =>
        item.start_t !== null && item.start_t < end && (item.end_t ?? item.start_t) >= v.start,
    ) || group.bands.some((band) => band.from < end && band.to >= v.start)
  )
}

/** A drilled-in event's name, for the breadcrumb. */
function DrillName({ vault, id }: { vault: string; id: string }) {
  const entity = useEntity(vault, id)
  return <>{entity.data?.name ?? '…'}</>
}

type ItemAction = 'edit' | 'sub-event' | 'participants' | 'causes'

/** The context menu of an item (frontend.md §9.4). */
function ItemMenu({
  item,
  editable,
  expanded,
  onOpen,
  onAction,
  onToggleExpanded,
  onDrillIn,
  onMaterialize,
}: {
  item: WindowItem
  editable: boolean
  expanded: boolean
  onOpen: () => void
  onAction: (action: ItemAction) => void
  onToggleExpanded: () => void
  onDrillIn: () => void
  onMaterialize: () => void
}) {
  const computed = isComputedOccurrence(item)
  const act = (action: ItemAction) => () => {
    onAction(action)
  }
  return (
    <>
      <ContextMenuItem onSelect={onOpen}>Open {item.name}</ContextMenuItem>
      {editable && !computed && (
        <>
          <ContextMenuItem onSelect={act('edit')}>Edit time…</ContextMenuItem>
          <ContextMenuItem onSelect={act('sub-event')}>New sub-event…</ContextMenuItem>
          <ContextMenuItem onSelect={act('participants')}>Add a participant…</ContextMenuItem>
          <ContextMenuItem onSelect={act('causes')}>Link a cause or effect…</ContextMenuItem>
        </>
      )}
      {editable && computed && (
        <ContextMenuItem onSelect={onMaterialize}>Materialize this occurrence</ContextMenuItem>
      )}
      {!computed && (
        <>
          <ContextMenuSeparator />
          {item.has_children && (
            <ContextMenuItem onSelect={onToggleExpanded}>
              {expanded ? 'Collapse its sub-events' : 'Expand its sub-events'}
            </ContextMenuItem>
          )}
          <ContextMenuItem onSelect={onDrillIn}>Drill in</ContextMenuItem>
        </>
      )}
    </>
  )
}

/** A drag the event's time can't follow (a relative anchor, a calendar duration…). */
class LockedError extends Error {}

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
      cursor={context.moment}
      onCursor={context.setCursor}
      dimensionId={dimensionId}
    />
  )
}

function Timeline({
  vault,
  timelineId,
  dimension,
  lens,
  lenses,
  cursor,
  onCursor,
  dimensionId,
}: {
  vault: string
  dimensionId: string
  timelineId: string | null
  dimension: DimensionTime
  lens: Lens
  lenses: readonly Lens[]
  /** The time cursor's moment (`null`: all time). */
  cursor: bigint | null
  onCursor: (cursor: Cursor) => void
}) {
  const [ref, width] = useWidth()
  const controls: ViewportControls = useViewport(dimension.duration, width)
  const v = controls.viewport
  const search: { perf?: unknown; in?: string } = useSearch({ strict: false })
  const editable = useMutations() !== null
  const branching = useBranching(vault)
  /** "Branch here": the moment to branch the viewed timeline at. */
  const [branchAt, setBranchAt] = useState<bigint | null>(null)
  const [filters, setFilters] = useState<TimelineFilters>(NO_FILTERS)
  const [grouping, setGrouping] = useState<GroupMode>('auto')
  const [expanded, setExpanded] = useState<Named[]>([])
  const [action, setAction] = useState<TimelineAction | null>(null)
  /** Drilled-in events, outermost first (`in` in the URL). */
  const drill = useMemo(() => (search.in ?? '').split(',').filter((id) => id !== ''), [search.in])
  const drillParent = drill.at(-1) ?? null
  const query = useMemo(
    () => ({
      ...windowFilters(filters),
      ...(drillParent === null ? {} : { parent: drillParent }),
    }),
    [filters, drillParent],
  )
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
  const { window: data, loading } = useTimelineWindow(
    vault,
    timelineId,
    v,
    dimension.duration,
    query,
  )
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
  /** An entity dropped on an item: a computed occurrence is materialized first (to link it). */
  const dropEntity = useCallback(
    (item: WindowItem, transfer: DataTransfer) => {
      const entity = droppedEntity(transfer, vault)
      if (entity === null) return
      if (isComputedOccurrence(item) && item.occurrence_key !== null) {
        materializeOccurrence(
          { event: item.entity_id, key: item.occurrence_key },
          {
            onSuccess: (result) => {
              setAction({
                kind: 'drop',
                event: { id: result.entity.id, name: result.entity.name },
                entity,
              })
            },
          },
        )
        return
      }
      setAction({ kind: 'drop', event: { id: item.entity_id, name: item.name }, entity })
    },
    [materializeOccurrence, vault],
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
  const minor = found.minor[0] ?? found.major[0]
  const snap = new TickSnap(
    lens.calendar,
    minor?.level ?? 'base',
    minor?.level === 'base' ? minor.multiple : 1n,
    dimension.duration,
  )
  const formatAt = (t: bigint) =>
    formatIn(lens, { t, precision: minor?.level ?? 'base' }, dimension, lenses) ?? t.toString()

  // --- direct editing (frontend.md §9.4) -------------------------------------------------------
  const update = useUpdateLatest(vault, { toast: false })
  const [itemDrag, setItemDrag] = useState<DragPreview | null>(null)
  const pressed = useRef<{ drawn: Drawn; mode: DragMode; x0: number; dx: number } | null>(null)
  const editing = useRef({ v, snap, lenses })
  useLayoutEffect(() => {
    editing.current = { v, snap, lenses }
  })
  const updateEvent = update.mutate
  /** Saves a drag: the edge's moment snapped to the axis' minor unit, typed in its calendar. */
  const commitDrag = useCallback(
    (drawn: Drawn, mode: DragMode, dx: number) => {
      const { v: view, snap: snapper, lenses: all } = editing.current
      const item = drawn.item
      const edge = mode === 'end' ? item.end_t : item.start_t
      if (edge === null) return
      const delta = snapper.snap(edge + (fromPx(view, dx) - fromPx(view, 0))) - edge
      if (delta === 0n) return
      updateEvent(
        {
          id: item.entity_id,
          change: (entity) => {
            const time = eventTime(entity)
            if (time.start === null || time.end === null) throw new Error('It has no time to move.')
            const result = dragTime(time.start, time.end, mode, delta, all)
            if (result.kind === 'locked') throw new LockedError(result.reason)
            return { ext: { start: result.start, end: result.end } }
          },
        },
        {
          onSuccess: () => {
            toast.success(`Moved ${item.name}`)
          },
          onError: (error) => {
            toast.error(error.message, {
              ...(error instanceof LockedError
                ? {
                    action: {
                      label: 'Edit',
                      onClick: () => {
                        setAction({ kind: 'edit', id: item.entity_id })
                      },
                    },
                  }
                : {}),
            })
          },
        },
      )
    },
    [updateEvent],
  )
  const onPress = useCallback<PressHandler>((event, drawn, mode) => {
    // Computed occurrences have no event of their own to change.
    if (isComputedOccurrence(drawn.item)) return
    pressed.current = { drawn, mode, x0: event.clientX, dx: 0 }
  }, [])
  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      const press = pressed.current
      if (press === null) return
      press.dx = event.clientX - press.x0
      if (Math.abs(press.dx) >= 3) {
        setItemDrag({ key: press.drawn.key, mode: press.mode, dx: press.dx })
      }
    }
    const onUp = () => {
      const press = pressed.current
      pressed.current = null
      if (press === null) return
      setItemDrag(null)
      if (Math.abs(press.dx) >= 3) commitDrag(press.drawn, press.mode, press.dx)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [commitDrag])

  // The selected event's time: relative anchors show a lock and aren't dragged.
  const selectedEntity = useEntity(
    vault,
    selectedItem?.entity_id ?? '',
    {},
    { enabled: selectedItem !== null && !isComputedOccurrence(selectedItem) },
  )
  const relative =
    selectedEntity.data !== undefined &&
    selectedEntity.data.id === selectedItem?.entity_id &&
    eventTime(selectedEntity.data).start?.anchor.kind === 'relative'

  // The context menu's target: an item, or a moment of empty space.
  const [menu, setMenu] = useState<{ key: string | null; t: bigint }>({ key: null, t: 0n })
  const onMenu = useCallback((key: string) => {
    setMenu((current) => ({ ...current, key }))
  }, [])
  const menuItem = menu.key === null ? null : (byStart.find((i) => itemKey(i) === menu.key) ?? null)
  const createAt = (t: bigint) => {
    setAction({
      kind: 'create',
      start: pointAt(lens, snap.snap(t), minor?.level ?? 'base', lenses),
      parent:
        drillParent === null
          ? null
          : { id: drillParent, name: drillName ?? '', dimension_id: dimension.id },
    })
  }

  // Sub-events: expanded inline, or drilled into.
  const expandedIds = new Set(expanded.map((parent) => parent.id))
  const toggleExpanded = (item: WindowItem) => {
    setExpanded((current) =>
      current.some((parent) => parent.id === item.entity_id)
        ? current.filter((parent) => parent.id !== item.entity_id)
        : [...current, { id: item.entity_id, name: item.name }],
    )
  }
  const drillTo = (ids: readonly string[], range: { start: bigint; end: bigint } | null) => {
    void navigate({
      to: '.',
      search: (previous: Record<string, unknown>) => ({
        ...previous,
        in: ids.length === 0 ? undefined : ids.join(','),
        ...(range === null ? {} : { from: range.start.toString(), to: range.end.toString() }),
      }),
    })
  }
  const drillIn = (item: WindowItem) => {
    const start = item.start_t ?? v.start
    const end = item.end_t !== null && item.end_t > start ? item.end_t : start + v.span / 10n
    const pad = (end - start) / 20n
    setExpanded((current) => current.filter((parent) => parent.id !== item.entity_id))
    drillTo([...drill, item.entity_id], { start: start - pad, end: end + pad })
  }
  // The lanes: sub-events of expanded events move to their own group; the rest is grouped.
  const mainItems = useMemo(
    () => laneItems.filter((item) => item.parent_id === null || !expandedIds.has(item.parent_id)),
    // `expandedIds` is derived from `expanded`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [laneItems, expanded],
  )
  const categories = useMemo(
    () => [
      ...new Set(data.items.flatMap((item) => (item.category === null ? [] : [item.category]))),
    ],
    [data.items],
  )
  /** Compare mode: the other timelines shown under the viewed one (frontend.md §9.5). */
  const [compare, setCompare] = useState<string[]>([])
  const compared = branching.timelines
    .map(({ node }) => node)
    .filter((node) => compare.includes(node.id) && node.id !== timelineId)
  const comparing = compared.length > 0
  const differences = useDifferences(vault, comparing ? [branching.current, ...compared] : [])
  /** Dimension lanes: other dimensions' events mapped onto this axis (frontend.md §9.5). */
  const correspondencesOn = useActiveModules(vault).modules.some(
    (module) => module.id === 'correspondences',
  )
  const graph = useCorrespondenceGraph(vault, { enabled: correspondencesOn })
  const dimensionNames = useDimensions(vault).data?.items
  const laneOptions: Named[] =
    graph === null
      ? []
      : reachableFrom(graph, dimensionId).map((id) => ({
          id,
          name: dimensionNames?.find((item) => item.id === id)?.name ?? 'Dimension',
        }))
  const [dimensionLanes, setDimensionLanes] = useState<string[]>([])
  const lane: LaneProps = {
    v,
    layoutV,
    lenses,
    selected,
    onSelect: setSelected,
    onOpen: open,
    drag: itemDrag,
    locked: relative ? selected : null,
    onPress: editable ? onPress : undefined,
    onMenu,
    onDropEntity: editable ? dropEntity : undefined,
    highlight: comparing && timelineId !== null ? (differences.get(timelineId) ?? null) : null,
  }
  /** What a screen reader hears when an item is selected: its name, dates and importance. */
  const announce = (item: WindowItem) => {
    const at = (t: bigint | null, precision: string | null) =>
      t === null
        ? null
        : (formatIn(lens, { t, precision: precision ?? item.start_precision }, dimension, lenses) ??
          t.toString())
    const start = at(item.start_t, item.start_precision)
    const end = item.end_t === item.start_t ? null : at(item.end_t, item.end_precision)
    return [
      item.name,
      end === null ? start : `${start ?? '?'} to ${end}`,
      `importance ${item.importance}`,
    ]
      .filter((part) => part !== null)
      .join(', ')
  }
  const drillEntity = useEntity(vault, drillParent ?? '', {}, { enabled: drillParent !== null })
  const drillName = drillParent === null ? null : (drillEntity.data?.name ?? null)

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
      case 'e':
      case 'E':
        // Expand or collapse the selected event's sub-events.
        if (!selectedItem?.has_children) return
        toggleExpanded(selectedItem)
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
        <select
          aria-label="Group lanes"
          className="h-8 rounded-md border border-input bg-transparent px-1 text-xs"
          value={grouping}
          onChange={(event) => {
            setGrouping(event.target.value as GroupMode)
          }}
        >
          {GROUP_MODES.map((mode) => (
            <option key={mode.value} value={mode.value}>
              {mode.label}
            </option>
          ))}
        </select>
        <CompareMenu branching={branching} value={compare} onChange={setCompare} />
        <DimensionLaneMenu
          options={laneOptions}
          value={dimensionLanes}
          onChange={setDimensionLanes}
        />
        <FiltersPanel
          vault={vault}
          dimensionId={dimensionId}
          categories={categories}
          value={filters}
          onChange={setFilters}
        />
        <Button asChild variant="outline" size="sm">
          <Link to="/v/$vault/d/$dimension/events" params={{ vault, dimension: dimensionId }}>
            <ListIcon aria-hidden /> List view
          </Link>
        </Button>
      </div>
      {drill.length > 0 && (
        <nav aria-label="Drilled into" className="flex flex-wrap items-center gap-1 text-sm">
          <button
            type="button"
            className="text-muted-foreground underline-offset-2 hover:underline"
            onClick={() => {
              drillTo([], null)
            }}
          >
            All events
          </button>
          {drill.map((id, index) => (
            <span key={id} className="flex items-center gap-1">
              <ChevronRightIcon aria-hidden className="size-3.5 text-muted-foreground" />
              {index === drill.length - 1 ? (
                <span aria-current="location" className="font-medium">
                  <DrillName vault={vault} id={id} />
                </span>
              ) : (
                <button
                  type="button"
                  className="underline-offset-2 hover:underline"
                  onClick={() => {
                    drillTo(drill.slice(0, index + 1), null)
                  }}
                >
                  <DrillName vault={vault} id={id} />
                </button>
              )}
            </span>
          ))}
        </nav>
      )}
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
          <div className="relative flex flex-col gap-1">
            <EraBands v={v} calendar={lens.calendar} />
            <TimeAxis v={v} found={found} />
            <OverlayStrip v={v} calendar={lens.calendar} />
            <DensityStrip v={v} buckets={data.buckets} />
            <ContextMenu
              onOpenChange={(opened) => {
                if (!opened) setMenu((current) => ({ ...current, key: null }))
              }}
            >
              <ContextMenuTrigger asChild>
                <div
                  ref={lanes}
                  data-testid="timeline-lanes"
                  className="relative cursor-grab touch-none overflow-x-hidden overflow-y-auto active:cursor-grabbing"
                  style={{ height: LANES_HEIGHT }}
                  onContextMenuCapture={(event) => {
                    // Empty space (an item's own handler names it next): the moment there.
                    const box = event.currentTarget.getBoundingClientRect()
                    setMenu({ key: null, t: fromPx(v, event.clientX - box.left) })
                  }}
                  onDoubleClick={(event) => {
                    // Double-click on empty space creates an event there (frontend.md §9.4).
                    if (
                      !editable ||
                      (event.target as HTMLElement).closest('[data-item]') !== null
                    ) {
                      return
                    }
                    const box = event.currentTarget.getBoundingClientRect()
                    createAt(fromPx(v, event.clientX - box.left))
                  }}
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
                  {comparing && (
                    <DivergenceMarkers
                      v={v}
                      height={LANES_HEIGHT}
                      timelines={
                        branching.current === null ? compared : [branching.current, ...compared]
                      }
                    />
                  )}
                  {comparing && (
                    <GroupHeader label={`${branching.current?.name ?? 'This timeline'} (viewed)`} />
                  )}
                  {grouping === 'participant' ? (
                    filters.participants.length === 0 ? (
                      <p className="p-3 text-xs text-muted-foreground">
                        Choose participants in the filters to see their swimlanes.
                      </p>
                    ) : (
                      filters.participants.map((participant) => (
                        <ParticipantLane
                          key={participant.id}
                          vault={vault}
                          timelineId={timelineId}
                          D={dimension.duration}
                          filters={query}
                          participant={participant}
                          lane={lane}
                          onRemove={() => {
                            setFilters({
                              ...filters,
                              participants: filters.participants.filter(
                                (each) => each.id !== participant.id,
                              ),
                            })
                          }}
                        />
                      ))
                    )
                  ) : (
                    groupItems(mainItems, data.bands, grouping)
                      // A group with nothing in view (its events are elsewhere in the tiles) is left out.
                      .filter((group) => group.label === null || inView(group, v))
                      .map((group) => <LaneGroupView key={group.key} group={group} lane={lane} />)
                  )}
                  {expanded.map((parent) => (
                    <SubEventGroup
                      key={parent.id}
                      vault={vault}
                      timelineId={timelineId}
                      D={dimension.duration}
                      filters={query}
                      parent={parent}
                      lane={lane}
                      onCollapse={() => {
                        setExpanded((current) => current.filter((each) => each.id !== parent.id))
                      }}
                    />
                  ))}
                  {compared.map((node) => (
                    <CompareGroup
                      key={node.id}
                      vault={vault}
                      timeline={{ id: node.id, name: node.name }}
                      D={dimension.duration}
                      filters={query}
                      lane={lane}
                      highlight={differences.get(node.id) ?? null}
                      onRemove={() => {
                        setCompare((current) => current.filter((id) => id !== node.id))
                      }}
                    />
                  ))}
                  {graph !== null &&
                    laneOptions
                      .filter((option) => dimensionLanes.includes(option.id))
                      .map((option) => (
                        <DimensionLaneGroup
                          key={option.id}
                          vault={vault}
                          graph={graph}
                          dimensionId={dimensionId}
                          other={option}
                          lane={lane}
                          onRemove={() => {
                            setDimensionLanes((current) => current.filter((id) => id !== option.id))
                          }}
                        />
                      ))}
                  {data.items.length === 0 && data.bands.length === 0 && (
                    <p className="pointer-events-none absolute inset-x-0 top-1/2 text-center text-xs text-muted-foreground">
                      {loading ? 'Loading events…' : 'No events here.'}
                    </p>
                  )}
                </div>
              </ContextMenuTrigger>
              <ContextMenuContent>
                {menuItem === null ? (
                  <>
                    {editable && (
                      <ContextMenuItem
                        onSelect={() => {
                          createAt(menu.t)
                        }}
                      >
                        New event here…
                      </ContextMenuItem>
                    )}
                    {editable && branching.enabled && timelineId !== null && (
                      <ContextMenuItem
                        onSelect={() => {
                          setBranchAt(menu.t)
                        }}
                      >
                        Branch here…
                      </ContextMenuItem>
                    )}
                    {drill.length > 0 && (
                      <ContextMenuItem
                        onSelect={() => {
                          drillTo(drill.slice(0, -1), null)
                        }}
                      >
                        Back out of {drillName ?? 'this event'}
                      </ContextMenuItem>
                    )}
                    {!editable && drill.length === 0 && (
                      <ContextMenuItem disabled>No actions here</ContextMenuItem>
                    )}
                  </>
                ) : (
                  <ItemMenu
                    item={menuItem}
                    editable={editable}
                    expanded={expandedIds.has(menuItem.entity_id)}
                    onOpen={() => {
                      open(menuItem)
                    }}
                    onAction={(kind) => {
                      setAction(
                        kind === 'sub-event'
                          ? {
                              kind: 'create',
                              start: null,
                              parent: {
                                id: menuItem.entity_id,
                                name: menuItem.name,
                                dimension_id: dimension.id,
                              },
                            }
                          : { kind, id: menuItem.entity_id },
                      )
                    }}
                    onToggleExpanded={() => {
                      toggleExpanded(menuItem)
                    }}
                    onDrillIn={() => {
                      drillIn(menuItem)
                    }}
                    onMaterialize={() => {
                      if (menuItem.occurrence_key === null) return
                      materializeOccurrence({
                        event: menuItem.entity_id,
                        key: menuItem.occurrence_key,
                      })
                    }}
                  />
                )}
              </ContextMenuContent>
            </ContextMenu>
            <CursorLine
              v={v}
              moment={cursor}
              present={dimension.present}
              snap={snap}
              format={formatAt}
              onChange={onCursor}
            />
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
          <p aria-live="polite" className="sr-only" data-testid="timeline-announcement">
            {selectedItem === null ? '' : announce(selectedItem)}
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
            relative={relative}
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
      {branchAt !== null && (
        <CreateBranchDialog
          vault={vault}
          parentTimelineId={timelineId}
          initialPoint={{
            anchor: { kind: 'absolute', t: branchAt.toString() },
            precision: 'base',
          }}
          onClose={() => {
            setBranchAt(null)
          }}
        />
      )}
      {action !== null && (
        <TimelineDialogs
          vault={vault}
          dimensionId={dimensionId}
          timelineId={timelineId}
          action={action}
          onClose={() => {
            setAction(null)
          }}
        />
      )}
    </div>
  )
}
