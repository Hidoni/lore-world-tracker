import type { EntityViewProps } from '@/core/modules'
import { useSpeciesMembers } from '@/data'

import { LinkList } from './link-list'

/** Everyone and everything of the species (at any time; the time cursor filters with M7). */
export function SpeciesMembersPanel({ vault, entityId }: EntityViewProps) {
  const members = useSpeciesMembers(vault, entityId)
  if (members.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  const items = members.data?.items ?? []
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No members.</p>
  return <LinkList vault={vault} label="Members" items={items} />
}
