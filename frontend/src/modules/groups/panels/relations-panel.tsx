import type { EntityViewProps } from '@/core/modules'
import { useLinks } from '@/data'

import { LinkRows } from './link-rows'

const RELATIONS = ['groups.allied_with', 'groups.at_war_with', 'groups.vassal_of']

/** Alliances, wars and vassalage with other groups. */
export function GroupRelationsPanel({ vault, entityId }: EntityViewProps) {
  const links = useLinks(vault, entityId, { type: RELATIONS })
  const items = links.data?.items ?? []
  if (links.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No alliances, wars or vassals.</p>
  }
  return <LinkRows vault={vault} label="Relations" items={items} showLabel />
}
