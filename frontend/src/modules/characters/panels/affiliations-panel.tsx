import type { EntityViewProps } from '@/core/modules'
import { useEntityAsOf } from '@/core/time'
import { useLinks, useLinkTypes } from '@/data'

import { LinkRows } from './link-rows'

/**
 * Link types of other modules that place a character (docs/modules/characters.md): only those of
 * enabled modules are asked for.
 */
const AFFILIATIONS = [
  'groups.member_of',
  'locations.resides_in',
  'locations.origin',
  'species.is_a',
  'languages.speaks',
]

/** Memberships, residence, origin, species and languages, from the modules that are enabled. */
export function AffiliationsPanel({ vault, entityId }: EntityViewProps) {
  const offered = useLinkTypes(vault)
  const known = new Set(offered.data?.items.map((type) => type.key) ?? [])
  const types = AFFILIATIONS.filter((key) => known.has(key))
  const asOf = useEntityAsOf(vault, entityId)
  const links = useLinks(vault, entityId, { type: types, direction: 'out', ...asOf })
  if (offered.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (types.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No modules with affiliations are enabled.</p>
    )
  }
  const items = links.data?.items ?? []
  if (links.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No affiliations.</p>
  return <LinkRows vault={vault} label="Affiliations" items={items} />
}
