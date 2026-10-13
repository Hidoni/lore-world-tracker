import type { EntityViewProps } from '@/core/modules'
import { useEntity, useLinks } from '@/data'

import { CONNECTED_TO } from '../types'
import { LinkList } from './link-list'

const ROUTES: Record<string, string> = {
  road: 'road',
  river: 'river',
  sea_route: 'sea route',
  portal: 'portal',
  tunnel: 'tunnel',
  other: 'other',
}

/** Locations connected to this one (roads, rivers, portals… a portal may cross dimensions). */
export function ConnectionsPanel({ vault, entityId }: EntityViewProps) {
  const entity = useEntity(vault, entityId)
  const links = useLinks(vault, entityId, { type: [CONNECTED_TO] })
  if (links.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  return (
    <LinkList
      vault={vault}
      label="Connections"
      links={links.data?.items ?? []}
      kinds={ROUTES}
      empty="Not connected to other locations."
      dimension={entity.data?.dimension_id ?? null}
    />
  )
}
