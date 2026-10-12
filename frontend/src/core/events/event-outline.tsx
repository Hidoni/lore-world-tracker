import { Link, useNavigate } from '@tanstack/react-router'
import { ChevronDownIcon, ChevronRightIcon, PlusIcon } from 'lucide-react'
import { useState, type KeyboardEvent } from 'react'

import { Button } from '@/components/ui/button'
import { formatDurationIn, useTimeContext, type DimensionTime, type Lens } from '@/core/time'
import { useEventTreeLevel, useMutations, useTimelines, type EventTreeNode } from '@/data'
import { cn } from '@/lib/utils'

import { EventDialog } from './event-dialog'
import { IMPORTANCE } from './event-time'

type Node = EventTreeNode

/** The level durations are measured down to: days when the calendar has them, else its finest. */
function durationLevel(lens: Lens): string {
  const levels = lens.calendar?.levels ?? []
  return levels.includes('day') ? 'day' : (levels[0] ?? 'base')
}

function durationOf(
  node: Node,
  lens: Lens | null,
  time: DimensionTime | null,
  all: readonly Lens[],
) {
  const start = node.start_t
  const end = node.end_t
  if (start === null || end === null || lens === null || time === null) return '—'
  if (node.display.end === '?') return 'Unknown'
  return formatDurationIn(lens, { t: start, precision: durationLevel(lens) }, end, time, all) ?? '—'
}

const GRID =
  'grid grid-cols-[minmax(12rem,2fr)_minmax(8rem,1fr)_minmax(8rem,1fr)_minmax(6rem,1fr)_5rem_6rem] items-center'

interface Shared {
  vault: string
  timelineId: string
  expanded: ReadonlySet<string>
  toggle: (id: string, open?: boolean) => void
  lens: Lens | null
  time: DimensionTime | null
  lenses: readonly Lens[]
}

/** The rows of one level (and, under each expanded row, its children), with "Show more". */
function Level({
  shared,
  parent,
  depth,
}: {
  shared: Shared
  parent: string | null
  depth: number
}) {
  const level = useEventTreeLevel(shared.vault, shared.timelineId, parent)
  const nodes = level.data?.pages.flatMap((page) => page.items) ?? []
  if (level.isPending) {
    return (
      <div role="row" className="py-1 text-muted-foreground" style={{ paddingLeft: depth * 20 }}>
        <span role="gridcell">Loading…</span>
      </div>
    )
  }
  if (nodes.length === 0 && parent === null) {
    return (
      <div role="row" className="py-2 text-muted-foreground">
        <span role="gridcell">No events in this timeline yet.</span>
      </div>
    )
  }
  return (
    <>
      {nodes.map((node) => {
        const open = shared.expanded.has(node.id)
        return <Row key={node.id} shared={shared} node={node} depth={depth} open={open} />
      })}
      {level.hasNextPage && (
        <div role="row" style={{ paddingLeft: depth * 20 + 28 }}>
          <span role="gridcell">
            <Button
              variant="ghost"
              size="sm"
              disabled={level.isFetchingNextPage}
              onClick={() => {
                void level.fetchNextPage()
              }}
            >
              Show more
            </Button>
          </span>
        </div>
      )}
    </>
  )
}

function Row({
  shared,
  node,
  depth,
  open,
}: {
  shared: Shared
  node: Node
  depth: number
  open: boolean
}) {
  return (
    <>
      <div
        data-outline-row={node.id}
        data-parent={node.parent_id ?? ''}
        role="row"
        aria-level={depth + 1}
        aria-expanded={node.has_children ? open : undefined}
        aria-label={node.name}
        tabIndex={-1}
        className={cn(
          GRID,
          'border-t py-1 outline-none focus-visible:bg-accent focus-visible:ring-2',
        )}
      >
        <div role="gridcell" className="pr-3">
          <div className="flex items-center gap-1" style={{ paddingLeft: depth * 20 }}>
            {node.has_children ? (
              <button
                type="button"
                tabIndex={-1}
                aria-label={open ? `Collapse ${node.name}` : `Expand ${node.name}`}
                className="rounded-sm p-0.5 hover:bg-accent"
                onClick={() => {
                  shared.toggle(node.id)
                }}
              >
                {open ? (
                  <ChevronDownIcon aria-hidden className="size-4" />
                ) : (
                  <ChevronRightIcon aria-hidden className="size-4" />
                )}
              </button>
            ) : (
              <span className="inline-block w-5" />
            )}
            <Link
              to="/v/$vault/e/$entity"
              params={{ vault: shared.vault, entity: node.id }}
              tabIndex={-1}
              className="font-medium underline-offset-2 hover:underline"
            >
              {node.name}
            </Link>
          </div>
        </div>
        <div role="gridcell" className="pr-3">
          {node.display.start ?? '—'}
        </div>
        <div role="gridcell" className="pr-3">
          {node.display.end === null || node.end_t === node.start_t ? '—' : node.display.end}
        </div>
        <div role="gridcell" className="pr-3">
          {durationOf(node, shared.lens, shared.time, shared.lenses)}
        </div>
        <div role="gridcell" className="pr-3" title={IMPORTANCE[node.importance]}>
          {node.importance}
        </div>
        <div role="gridcell" className="text-right">
          {node.participants}
        </div>
      </div>
      {open && <Level shared={shared} parent={node.id} depth={depth + 1} />}
    </>
  )
}

interface TimelineNode {
  id: string
  name: string
  trashed: boolean
  children: readonly TimelineNode[]
}

function flatten(nodes: readonly TimelineNode[]): TimelineNode[] {
  return nodes.flatMap((node) => [...(node.trashed ? [] : [node]), ...flatten(node.children)])
}

/**
 * The event outline of a dimension (`/v/$vault/d/$dimension/events`, frontend.md §10): a tree
 * table of the timeline's events (name, start, end, duration, importance, participants) ordered
 * by start, each level loaded when it is expanded. Keyboard: ↑/↓ move, → expands (or enters),
 * ← collapses (or goes to the parent), Enter opens, Home/End jump.
 */
export function EventOutline({ vault, dimensionId }: { vault: string; dimensionId: string }) {
  const context = useTimeContext(vault)
  const navigate = useNavigate()
  const editable = useMutations() !== null
  const timelines = useTimelines(vault, dimensionId)
  const options = flatten(timelines.data?.items ?? [])
  const timelineId = context.timelineId
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const [creating, setCreating] = useState(false)
  const toggle = (id: string, open?: boolean) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (open ?? !next.has(id)) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const rows = [...event.currentTarget.querySelectorAll<HTMLElement>('[data-outline-row]')]
    const row = (event.target as HTMLElement).closest<HTMLElement>('[data-outline-row]')
    if (row === null) return
    const index = rows.indexOf(row)
    const id = row.dataset.outlineRow ?? ''
    const focus = (target: HTMLElement | undefined) => {
      if (target === undefined) return
      event.preventDefault()
      target.focus()
    }
    switch (event.key) {
      case 'ArrowDown':
        focus(rows[index + 1])
        break
      case 'ArrowUp':
        focus(rows[index - 1])
        break
      case 'Home':
        focus(rows[0])
        break
      case 'End':
        focus(rows.at(-1))
        break
      case 'ArrowRight':
        event.preventDefault()
        if (row.getAttribute('aria-expanded') === 'false') toggle(id, true)
        else if (row.getAttribute('aria-expanded') === 'true') focus(rows[index + 1])
        break
      case 'ArrowLeft': {
        event.preventDefault()
        if (row.getAttribute('aria-expanded') === 'true') {
          toggle(id, false)
        } else {
          const parent = row.dataset.parent
          focus(rows.find((candidate) => candidate.dataset.outlineRow === parent))
        }
        break
      }
      case 'Enter':
        event.preventDefault()
        void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: id } })
        break
    }
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-semibold">Events</h1>
        <div className="flex-1" />
        {options.length > 1 && (
          <select
            aria-label="Timeline"
            className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
            value={timelineId ?? ''}
            onChange={(event) => {
              context.setTimeline(event.target.value)
              setExpanded(new Set())
            }}
          >
            {options.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
        )}
        {editable && (
          <Button
            onClick={() => {
              setCreating(true)
            }}
          >
            <PlusIcon aria-hidden /> New event
          </Button>
        )}
      </div>
      {timelineId === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div
          role="treegrid"
          aria-label="Event outline"
          tabIndex={-1}
          className="flex flex-col text-sm"
          onKeyDown={onKeyDown}
          onFocus={(event) => {
            // Roving focus: the focused row is the tab stop.
            const rows = event.currentTarget.querySelectorAll<HTMLElement>('[data-outline-row]')
            for (const candidate of rows) candidate.tabIndex = candidate === event.target ? 0 : -1
          }}
          ref={(grid) => {
            // The first row is the tab stop until another row takes focus.
            const rows = [...(grid?.querySelectorAll<HTMLElement>('[data-outline-row]') ?? [])]
            const first = rows[0]
            if (first !== undefined && !rows.some((row) => row.tabIndex === 0)) first.tabIndex = 0
          }}
        >
          <div role="row" className={cn(GRID, 'py-1 text-xs text-muted-foreground')}>
            <span role="columnheader">Name</span>
            <span role="columnheader">Start</span>
            <span role="columnheader">End</span>
            <span role="columnheader">Duration</span>
            <span role="columnheader">Importance</span>
            <span role="columnheader" className="text-right">
              Participants
            </span>
          </div>
          <Level
            shared={{
              vault,
              timelineId,
              expanded,
              toggle,
              lens: context.lens,
              time: context.dimension,
              lenses: context.lenses,
            }}
            parent={null}
            depth={0}
          />
        </div>
      )}
      {creating && (
        <EventDialog
          mode="create"
          vault={vault}
          dimensionId={dimensionId}
          onClose={() => {
            setCreating(false)
          }}
        />
      )}
    </div>
  )
}
