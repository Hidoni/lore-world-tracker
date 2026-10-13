import type { EntityViewProps } from '@/core/modules'
import { useEntityAsOf } from '@/core/time'
import { useLinks } from '@/data'

import { LinkRows } from './link-rows'

/** Who speaks the language (at any time; the time cursor filters with M7), with fluency. */
export function SpeakersPanel({ vault, entityId }: EntityViewProps) {
  const asOf = useEntityAsOf(vault, entityId)
  const links = useLinks(vault, entityId, { type: ['languages.speaks'], direction: 'in', ...asOf })
  if (links.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  const items = links.data?.items ?? []
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No speakers.</p>
  return <LinkRows vault={vault} label="Speakers" items={items} />
}
