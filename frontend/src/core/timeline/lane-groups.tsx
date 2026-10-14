import type { Viewport } from '@lore/chronology/viewport'
import { ChevronDownIcon, XIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { IMPORTANCE } from '@/core/events'
import type { Lens } from '@/core/time'
import type { WindowFilters } from '@/data'

import { EventLanes, type DragPreview, type PressHandler } from './event-lanes'
import type { Named } from './filters-panel'
import { useTimelineWindow, type SeriesBand, type WindowItem } from './use-timeline-window'

/** A group of lanes: its items and series bands, under a label (none: the only group). */
export interface LaneGroup {
  key: string
  label: string | null
  items: WindowItem[]
  bands: SeriesBand[]
}

const UNCATEGORIZED = 'Uncategorized'

/**
 * Items and bands grouped for the lanes (frontend.md §9.3): one group (`auto`), by category
 * (by name, uncategorized last) or by importance (most important first). Empty groups are left
 * out.
 */
export function groupItems(
  items: readonly WindowItem[],
  bands: readonly SeriesBand[],
  mode: 'auto' | 'category' | 'importance',
): LaneGroup[] {
  if (mode === 'auto') return [{ key: 'all', label: null, items: [...items], bands: [...bands] }]
  const groups = new Map<string, LaneGroup>()
  const of = (value: { category: string | null; importance: number }) => {
    const key = mode === 'category' ? (value.category ?? '') : String(value.importance)
    let group = groups.get(key)
    if (group === undefined) {
      const label =
        mode === 'category'
          ? key === ''
            ? UNCATEGORIZED
            : key
          : `${key} · ${IMPORTANCE[value.importance] ?? ''}`
      group = { key, label, items: [], bands: [] }
      groups.set(key, group)
    }
    return group
  }
  for (const item of items) of(item).items.push(item)
  for (const band of bands) of(band).bands.push(band)
  return [...groups.values()].sort((a, b) =>
    mode === 'importance'
      ? Number(b.key) - Number(a.key)
      : a.key === ''
        ? 1
        : b.key === ''
          ? -1
          : a.key.localeCompare(b.key),
  )
}

/** What every lane group shares: the view and the item handlers. */
export interface LaneProps {
  v: Viewport
  layoutV: Viewport
  lenses: readonly Lens[]
  selected: string | null
  onSelect: (key: string | null) => void
  onOpen: (item: WindowItem) => void
  drag: DragPreview | null
  locked: string | null
  onPress: PressHandler | undefined
  onMenu: ((key: string) => void) | undefined
  /** An entity dragged onto an item (visual linking); off on read-only timelines. */
  onDropEntity?: ((item: WindowItem, transfer: DataTransfer) => void) | undefined
  /** Compare mode: the events (entity ids) that differ, outlined. */
  highlight?: ReadonlySet<string> | null
}

/** A group's label row, kept at the left while panning. */
export function GroupHeader({ label, actions }: { label: string; actions?: ReactNode }) {
  return (
    <div className="sticky left-0 flex items-center gap-1 border-t px-2 pt-1 text-xs font-medium text-muted-foreground">
      {label}
      {actions}
    </div>
  )
}

/** One group of lanes under its label. */
export function LaneGroupView({ group, lane }: { group: LaneGroup; lane: LaneProps }) {
  return (
    <section aria-label={group.label ?? 'Events'} data-testid="lane-group">
      {group.label !== null && <GroupHeader label={group.label} />}
      <EventLanes {...lane} items={group.items} bands={group.bands} />
    </section>
  )
}

/**
 * A parent event's sub-events expanded inline (frontend.md §9.3): nested lanes under the main
 * ones, from a window filtered to its descendants.
 */
export function SubEventGroup({
  vault,
  timelineId,
  D,
  filters,
  parent,
  lane,
  onCollapse,
}: {
  vault: string
  timelineId: string | null
  D: bigint
  filters: WindowFilters
  parent: Named
  lane: LaneProps
  onCollapse: () => void
}) {
  const { window: data, loading } = useTimelineWindow(vault, timelineId, lane.v, D, {
    ...filters,
    parent: parent.id,
  })
  return (
    <section
      aria-label={`Sub-events of ${parent.name}`}
      data-testid="sub-event-group"
      className="pl-3"
    >
      <GroupHeader
        label={`${parent.name}: sub-events`}
        actions={
          <button
            type="button"
            aria-label={`Collapse ${parent.name}`}
            className="rounded p-0.5 hover:text-foreground"
            onClick={onCollapse}
          >
            <ChevronDownIcon aria-hidden className="size-3.5" />
          </button>
        }
      />
      {data.items.length === 0 && data.bands.length === 0 ? (
        <p className="px-2 py-1 text-xs text-muted-foreground">
          {loading ? 'Loading…' : 'No sub-events here.'}
        </p>
      ) : (
        <EventLanes {...lane} items={data.items} bands={data.bands} />
      )}
    </section>
  )
}

/** A participant's swimlane (frontend.md §9.3): the events it takes part in. */
export function ParticipantLane({
  vault,
  timelineId,
  D,
  filters,
  participant,
  lane,
  onRemove,
}: {
  vault: string
  timelineId: string | null
  D: bigint
  filters: WindowFilters
  participant: Named
  lane: LaneProps
  onRemove: () => void
}) {
  const { window: data, loading } = useTimelineWindow(vault, timelineId, lane.v, D, {
    ...filters,
    participant: [participant.id],
  })
  return (
    <section aria-label={participant.name} data-testid="lane-group">
      <GroupHeader
        label={participant.name}
        actions={
          <button
            type="button"
            aria-label={`Remove ${participant.name}`}
            className="rounded p-0.5 hover:text-foreground"
            onClick={onRemove}
          >
            <XIcon aria-hidden className="size-3" />
          </button>
        }
      />
      {data.items.length === 0 && data.bands.length === 0 ? (
        <p className="px-2 py-1 text-xs text-muted-foreground">
          {loading ? 'Loading…' : 'No events here.'}
        </p>
      ) : (
        <EventLanes {...lane} items={data.items} bands={data.bands} />
      )}
    </section>
  )
}

/**
 * Compare mode (frontend.md §9.5): another timeline's events in lanes of their own under the
 * main ones, on the same axis, read-only (opening an event still works). Events that timeline
 * created or changed after its branch point are outlined.
 */
export function CompareGroup({
  vault,
  timeline,
  D,
  filters,
  lane,
  highlight,
  onRemove,
}: {
  vault: string
  timeline: Named
  D: bigint
  filters: WindowFilters
  lane: LaneProps
  highlight: ReadonlySet<string> | null
  onRemove: () => void
}) {
  const { window: data, loading } = useTimelineWindow(vault, timeline.id, lane.v, D, filters)
  const readOnly: LaneProps = {
    ...lane,
    drag: null,
    locked: null,
    onPress: undefined,
    onMenu: undefined,
    onDropEntity: undefined,
    highlight,
  }
  return (
    <section aria-label={`Compared: ${timeline.name}`} data-testid="compare-group">
      <GroupHeader
        label={timeline.name}
        actions={
          <button
            type="button"
            aria-label={`Stop comparing ${timeline.name}`}
            className="rounded p-0.5 hover:text-foreground"
            onClick={onRemove}
          >
            <XIcon aria-hidden className="size-3" />
          </button>
        }
      />
      {data.items.length === 0 && data.bands.length === 0 ? (
        <p className="px-2 py-1 text-xs text-muted-foreground">
          {loading ? 'Loading…' : 'No events here.'}
        </p>
      ) : (
        <EventLanes {...readOnly} items={data.items} bands={data.bands} />
      )}
    </section>
  )
}
