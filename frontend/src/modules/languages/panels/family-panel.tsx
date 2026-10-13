import { Link } from '@tanstack/react-router'

import type { EntityViewProps } from '@/core/modules'
import { useChildren, useLinks } from '@/data'

import { RowsSection } from './link-rows'

const DESCENT = 'languages.descended_from'
const BORROWING = 'languages.borrowed_from'

/** Ancestors, descendants, dialects and borrowings of a language. */
export function FamilyPanel({ vault, entityId }: EntityViewProps) {
  const links = useLinks(vault, entityId, { type: [DESCENT, BORROWING] })
  const children = useChildren(vault, entityId, { kind: ['language'], limit: 500 })
  if (links.isPending || children.isPending) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }
  const items = links.data?.items ?? []
  const of = (type: string, direction: string) =>
    items.filter((item) => item.link.link_type === type && item.direction === direction)
  const dialects = children.data?.items ?? []
  if (items.length === 0 && dialects.length === 0) {
    return <p className="text-sm text-muted-foreground">No known relatives.</p>
  }
  return (
    <div className="flex flex-col gap-3">
      <RowsSection vault={vault} title="Descended from" items={of(DESCENT, 'out')} />
      <RowsSection vault={vault} title="Ancestor of" items={of(DESCENT, 'in')} />
      {dialects.length > 0 && (
        <section aria-label="Dialects" className="flex flex-col gap-1">
          <h3 className="text-xs font-medium text-muted-foreground">Dialects</h3>
          <ul aria-label="Dialects" className="flex flex-wrap gap-x-4 gap-y-1">
            {dialects.map((dialect) => (
              <li key={dialect.id} className="text-sm">
                <Link
                  to="/v/$vault/e/$entity"
                  params={{ vault, entity: dialect.id }}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {dialect.name}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <RowsSection vault={vault} title="Borrows from" items={of(BORROWING, 'out')} />
      <RowsSection vault={vault} title="Lends to" items={of(BORROWING, 'in')} />
      <Link
        to="/v/$vault/m/$module/$"
        params={{ vault, module: 'languages', _splat: 'family-tree' }}
        className="self-start text-xs text-muted-foreground underline-offset-2 hover:underline"
      >
        Language family tree
      </Link>
    </div>
  )
}
