import { Link } from '@tanstack/react-router'

import type { EntityViewProps } from '@/core/modules'
import { useChildren, useLinks } from '@/data'

import { LinkList } from './link-list'

const DESCENT = 'species.descended_from'

/** Ancestors, descendants and subspecies of a species. */
export function DescentPanel({ vault, entityId }: EntityViewProps) {
  const links = useLinks(vault, entityId, { type: [DESCENT] })
  const children = useChildren(vault, entityId, { kind: ['species'], limit: 500 })
  if (links.isPending || children.isPending) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }
  const items = links.data?.items ?? []
  const ancestors = items.filter((item) => item.direction === 'out')
  const descendants = items.filter((item) => item.direction === 'in')
  const subspecies = children.data?.items ?? []
  return (
    <div className="flex flex-col gap-3">
      {ancestors.length + descendants.length + subspecies.length === 0 && (
        <p className="text-sm text-muted-foreground">No known ancestors or descendants.</p>
      )}
      {ancestors.length > 0 && (
        <section aria-label="Descended from" className="flex flex-col gap-1">
          <h3 className="text-xs font-medium text-muted-foreground">Descended from</h3>
          <LinkList vault={vault} label="Descended from" items={ancestors} />
        </section>
      )}
      {descendants.length > 0 && (
        <section aria-label="Ancestor of" className="flex flex-col gap-1">
          <h3 className="text-xs font-medium text-muted-foreground">Ancestor of</h3>
          <LinkList vault={vault} label="Ancestor of" items={descendants} />
        </section>
      )}
      {subspecies.length > 0 && (
        <section aria-label="Subspecies" className="flex flex-col gap-1">
          <h3 className="text-xs font-medium text-muted-foreground">Subspecies</h3>
          <ul aria-label="Subspecies" className="flex flex-wrap gap-x-4 gap-y-1">
            {subspecies.map((child) => (
              <li key={child.id} className="text-sm">
                <Link
                  to="/v/$vault/e/$entity"
                  params={{ vault, entity: child.id }}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {child.name}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <Link
        to="/v/$vault/m/$module/$"
        params={{ vault, module: 'species', _splat: 'descent-tree' }}
        className="self-start text-xs text-muted-foreground underline-offset-2 hover:underline"
      >
        Species descent tree
      </Link>
    </div>
  )
}
