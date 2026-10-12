import { Link, useParams } from '@tanstack/react-router'
import { ChevronRightIcon, ListIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { useTimeContext } from '@/core/time'
import { useEventTreeLevel, type EventTreeNode } from '@/data'
import { cn } from '@/lib/utils'

const ROW =
  'group flex min-w-0 items-center gap-1 rounded-md py-1 pr-1 text-sm hover:bg-accent focus-within:bg-accent'

interface LevelProps {
  vault: string
  timelineId: string
  /** `null`: the timeline's top-level events. */
  parent: EventTreeNode | null
  depth: number
  onNavigate: (() => void) | undefined
}

/** One level of the event hierarchy, fetched when shown. */
function EventLevel(props: LevelProps) {
  const { vault, timelineId, parent, depth } = props
  const level = useEventTreeLevel(vault, timelineId, parent?.id ?? null)
  const items = level.data?.pages.flatMap((page) => page.items) ?? []
  const indent = { paddingLeft: `${depth * 0.75 + 0.25}rem` }
  if (level.isPending) {
    return (
      <p className="py-1 text-xs text-muted-foreground" style={indent}>
        Loading…
      </p>
    )
  }
  if (items.length === 0 && parent === null) {
    return (
      <p className="py-1 text-xs text-muted-foreground" style={indent}>
        No events on this timeline yet
      </p>
    )
  }
  return (
    <ul className="flex flex-col" aria-label={parent ? `Inside ${parent.name}` : undefined}>
      {items.map((item) => (
        <EventRow key={item.id} {...props} node={item} />
      ))}
      {level.hasNextPage && (
        <li style={indent}>
          <button
            type="button"
            className="py-1 text-xs text-muted-foreground hover:text-foreground"
            disabled={level.isFetchingNextPage}
            onClick={() => {
              void level.fetchNextPage()
            }}
          >
            Show more
          </button>
        </li>
      )}
    </ul>
  )
}

function EventRow({ node, ...props }: LevelProps & { node: EventTreeNode }) {
  const { vault, depth, onNavigate } = props
  const [open, setOpen] = useState(false)
  const params = useParams({ strict: false })
  const current = params.entity === node.id
  return (
    <li>
      <div
        className={cn(ROW, current && 'bg-accent font-medium')}
        style={{ paddingLeft: `${depth * 0.75}rem` }}
      >
        {node.has_children ? (
          <button
            type="button"
            aria-expanded={open}
            aria-label={`${open ? 'Collapse' : 'Expand'} ${node.name}`}
            className="rounded p-0.5 text-muted-foreground hover:text-foreground"
            onClick={() => {
              setOpen(!open)
            }}
          >
            <ChevronRightIcon
              aria-hidden
              className={cn('size-3.5 transition-transform', open && 'rotate-90')}
            />
          </button>
        ) : (
          <span className="w-[1.125rem] shrink-0" aria-hidden />
        )}
        <Link
          to="/v/$vault/e/$entity"
          params={{ vault, entity: node.id }}
          aria-current={current ? 'page' : undefined}
          title={node.display.start ?? undefined}
          className="flex min-w-0 flex-1 items-baseline gap-1.5 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={onNavigate}
        >
          <span className="min-w-[50%] flex-1 truncate">{node.name}</span>
          {node.display.start !== null && (
            <span className="min-w-0 truncate text-[11px] text-muted-foreground">
              {node.display.start}
            </span>
          )}
        </Link>
      </div>
      {open && <EventLevel {...props} parent={node} depth={depth + 1} />}
    </li>
  )
}

/**
 * The event hierarchy of the time context's timeline (frontend.md §3): top-level events by time,
 * each lazily expandable into its sub-events and a series into its materialized occurrences
 * (`/timelines/{id}/event-tree`).
 */
export function EventsSection({
  vault,
  open,
  onToggle,
  onNavigate,
}: {
  vault: string
  open: boolean
  onToggle: () => void
  onNavigate: (() => void) | undefined
}) {
  const context = useTimeContext(vault)
  const { dimensionId, timelineId } = context
  if (dimensionId === null || timelineId === null) return null
  return (
    <section aria-label="Events" className="mt-2 flex flex-col">
      <div className="flex items-center gap-1 rounded-md px-1">
        <button
          type="button"
          aria-expanded={open}
          className="flex flex-1 items-center gap-1 py-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
          onClick={onToggle}
        >
          <ChevronRightIcon
            aria-hidden
            className={cn('size-3.5 transition-transform', open && 'rotate-90')}
          />
          Events
        </button>
        <Button
          asChild
          variant="ghost"
          size="icon"
          className="size-6 text-muted-foreground"
          title="Event outline"
        >
          <Link
            to="/v/$vault/d/$dimension/events"
            params={{ vault, dimension: dimensionId }}
            aria-label="Event outline"
            onClick={onNavigate}
          >
            <ListIcon className="size-3.5" />
          </Link>
        </Button>
      </div>
      {open && (
        <EventLevel
          key={timelineId}
          vault={vault}
          timelineId={timelineId}
          parent={null}
          depth={0}
          onNavigate={onNavigate}
        />
      )}
    </section>
  )
}
