import { Link } from '@tanstack/react-router'

import type { EntityViewProps } from '@/core/modules'
import { useChildren, useLinks } from '@/data'

import { LinkRows } from './link-rows'

/** Sub-groups (by parent) and the groups that are part of it over time (`part_of`), with a link
 * to the org chart. */
export function StructurePanel({ vault, entityId }: EntityViewProps) {
  const children = useChildren(vault, entityId, { kind: ['group'], limit: 500 })
  const parts = useLinks(vault, entityId, { type: ['groups.part_of'] })
  const subgroups = children.data?.items ?? []
  const links = parts.data?.items ?? []
  if (children.isPending || parts.isPending) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }
  if (subgroups.length === 0 && links.length === 0) {
    return <p className="text-sm text-muted-foreground">No sub-groups.</p>
  }
  return (
    <div className="flex flex-col gap-2">
      <Link
        to="/v/$vault/m/$module/$"
        params={{ vault, module: 'groups', _splat: `${entityId}/org-chart` }}
        className="text-sm text-primary underline-offset-2 hover:underline"
      >
        Open the org chart
      </Link>
      {subgroups.length > 0 && (
        <ul aria-label="Sub-groups" className="flex flex-wrap gap-x-4 gap-y-1">
          {subgroups.map((group) => (
            <li key={group.id}>
              <Link
                to="/v/$vault/e/$entity"
                params={{ vault, entity: group.id }}
                className="text-sm text-primary underline-offset-2 hover:underline"
              >
                {group.name}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {links.length > 0 && <LinkRows vault={vault} label="Parts" items={links} showLabel />}
    </div>
  )
}
