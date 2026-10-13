import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import type { EntityViewProps } from '@/core/modules'
import { useTimeContext } from '@/core/time'
import { useLocationEvents } from '@/data'

/**
 * "What happened here": the events at this location on the time context's timeline, by start,
 * with those at places inside it unless the toggle is off.
 */
export function EventsHerePanel({ vault, entityId }: EntityViewProps) {
  const { timelineId } = useTimeContext(vault)
  const [inside, setInside] = useState(true)
  const events = useLocationEvents(vault, entityId, timelineId, {
    include_descendants: inside,
  })
  const items = events.data?.items ?? []
  return (
    <div className="flex flex-col gap-2">
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={inside}
          onChange={(event) => {
            setInside(event.target.checked)
          }}
        />
        Include places inside
      </label>
      {timelineId === null ? (
        <p className="text-sm text-muted-foreground">Choose a dimension to see its events.</p>
      ) : events.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing happened here on this timeline.</p>
      ) : (
        <ol aria-label="Events here" className="flex flex-col gap-1">
          {items.map((item) => (
            <li key={item.id} className="flex gap-3 text-sm">
              <span className="w-40 shrink-0 truncate text-muted-foreground">
                {item.display.start ?? '—'}
              </span>
              <Link
                to="/v/$vault/e/$entity"
                params={{ vault, entity: item.id }}
                className="text-primary underline-offset-2 hover:underline"
              >
                {item.name}
              </Link>
              {!item.site_ids.includes(entityId) && (
                <span className="text-xs text-muted-foreground">(inside)</span>
              )}
            </li>
          ))}
        </ol>
      )}
      {events.data?.truncated && (
        <p className="text-xs text-muted-foreground">Showing the first {items.length}.</p>
      )}
    </div>
  )
}
