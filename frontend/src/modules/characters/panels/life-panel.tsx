import { Link } from '@tanstack/react-router'

import type { EntityViewProps } from '@/core/modules'
import { useTimeContext } from '@/core/time'
import { useCharacterLife } from '@/data'

/**
 * The character's life: the events they take part in on the time context's timeline, by start,
 * with their roles. Existence and ages come with M7.
 */
export function LifePanel({ vault, entityId }: EntityViewProps) {
  const { timelineId } = useTimeContext(vault)
  const life = useCharacterLife(vault, entityId, timelineId)
  const items = life.data?.items ?? []
  if (timelineId === null) {
    return <p className="text-sm text-muted-foreground">Choose a dimension to see its events.</p>
  }
  if (life.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">Takes part in no events on this timeline.</p>
    )
  }
  return (
    <ol aria-label="Life events" className="flex flex-col gap-1">
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
          {item.roles.length > 0 && (
            <span className="text-xs text-muted-foreground">as {item.roles.join(', ')}</span>
          )}
        </li>
      ))}
    </ol>
  )
}
