import type { EntityViewProps } from '@/core/modules'
import { useGroupLeaders } from '@/data'

import { LinkRows } from './link-rows'

/** The leadership succession, in order (timeless leaders first, then by validity). */
export function LeadershipPanel({ vault, entityId }: EntityViewProps) {
  const leaders = useGroupLeaders(vault, entityId)
  const items = leaders.data?.items ?? []
  if (leaders.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No leaders.</p>
  return (
    <LinkRows vault={vault} label="Leaders" items={items.map((leadership) => leadership.item)} />
  )
}
