import { Link } from '@tanstack/react-router'

import type { EntityViewProps } from '@/core/modules'
import { KindIcon, useKind } from '@/core/registry'
import { useLocationTree, type LocationNode } from '@/data'

import { LOCATION, typeLabel, typeOrder } from '../types'

/** The locations directly inside this one, grouped by type (types in the field's order). */
export function ContentsPanel({ vault, entityId }: EntityViewProps) {
  const kind = useKind(LOCATION, vault)
  const tree = useLocationTree(vault, { root: entityId })
  const items = tree.data?.items ?? []
  const order = typeOrder(kind)
  const groups = new Map<string, LocationNode[]>()
  for (const item of items) {
    const key = item.location_type ?? ''
    groups.set(key, [...(groups.get(key) ?? []), item])
  }
  const sorted = [...groups.entries()].sort(([a], [b]) => {
    const rank = (key: string) => (key === '' ? Infinity : order.indexOf(key) + 1 || order.length)
    return rank(a) - rank(b)
  })
  return (
    <div className="flex flex-col gap-3">
      {tree.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No locations inside.</p>
      ) : (
        sorted.map(([type, members]) => {
          const title = typeLabel(kind, type || null) ?? 'Other places'
          return (
            <section key={type} aria-label={title} className="flex flex-col gap-1">
              <h3 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                {kind && (
                  <KindIcon
                    kind={kind}
                    value={type || null}
                    className="size-3.5"
                    style={{ color: kind.color }}
                  />
                )}
                {title} <span aria-hidden>({members.length})</span>
              </h3>
              <ul className="flex flex-wrap gap-x-4 gap-y-1">
                {members.map((member) => (
                  <li key={member.id}>
                    <Link
                      to="/v/$vault/e/$entity"
                      params={{ vault, entity: member.id }}
                      className="text-sm text-primary underline-offset-2 hover:underline"
                    >
                      {member.name}
                    </Link>
                    {member.child_count > 0 && (
                      <span className="text-xs text-muted-foreground"> · {member.child_count}</span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )
        })
      )}
      <Link
        to="/v/$vault/m/$module/$"
        params={{ vault, module: 'locations', _splat: 'tree' }}
        className="self-start text-xs text-muted-foreground underline-offset-2 hover:underline"
      >
        Location tree
      </Link>
    </div>
  )
}
