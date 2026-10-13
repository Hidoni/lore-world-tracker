import type { EntityViewProps } from '@/core/modules'
import { useLinks } from '@/data'

import { LinkList } from './link-list'

/** The locations the species is native to (with the locations module). */
export function NativeToPanel({ vault, entityId }: EntityViewProps) {
  const links = useLinks(vault, entityId, { type: ['species.native_to'], direction: 'out' })
  if (links.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  const items = links.data?.items ?? []
  if (items.length === 0)
    return <p className="text-sm text-muted-foreground">Native nowhere known.</p>
  return <LinkList vault={vault} label="Native to" items={items} />
}
