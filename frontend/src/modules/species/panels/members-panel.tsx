import type { EntityViewProps } from '@/core/modules'
import { useEntityAsOf } from '@/core/time'
import { useSpeciesMembers } from '@/data'

import { LinkList } from './link-list'

/** Everyone and everything of the species (at any time; the time cursor filters with M7). */
export function SpeciesMembersPanel({ vault, entityId }: EntityViewProps) {
  const asOf = useEntityAsOf(vault, entityId)
  const members = useSpeciesMembers(vault, entityId, asOf)
  if (members.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  const items = members.data?.items ?? []
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No members.</p>
  return <LinkList vault={vault} label="Members" items={items} />
}
