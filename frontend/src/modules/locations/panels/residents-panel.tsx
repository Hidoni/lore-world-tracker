import type { EntityViewProps } from '@/core/modules'
import { useLocationResidents } from '@/data'

import { LinkList } from './link-list'

const RESIDENCE: Record<string, string> = {
  home: 'home',
  base: 'base',
  prison: 'prisoner',
  exile: 'in exile',
  other: 'other',
}

/** Who and what resides here (at any time; the time cursor filters them with M7). */
export function ResidentsPanel({ vault, entityId }: EntityViewProps) {
  const residents = useLocationResidents(vault, entityId)
  if (residents.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  return (
    <LinkList
      vault={vault}
      label="Residents"
      links={residents.data?.items ?? []}
      kinds={RESIDENCE}
      empty="Nobody resides here."
    />
  )
}
