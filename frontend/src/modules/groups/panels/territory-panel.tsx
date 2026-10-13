import type { EntityViewProps } from '@/core/modules'
import { useGroupTerritory } from '@/data'

import { LinkRows } from './link-rows'

/** The locations the group controls (with the locations module). */
export function TerritoryPanel({ vault, entityId }: EntityViewProps) {
  const territory = useGroupTerritory(vault, entityId)
  const items = territory.data?.items ?? []
  if (territory.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No territory.</p>
  return <LinkRows vault={vault} label="Territory" items={items} />
}
