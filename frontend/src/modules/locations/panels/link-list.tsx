import { Link } from '@tanstack/react-router'

import { useKindRegistry } from '@/core/registry'
import type { EntityLink } from '@/data'

/** Linked entities with their kind's icon and the link's `data.kind` (e.g. home, portal). */
export function LinkList({
  vault,
  label,
  links,
  kinds,
  empty,
  dimension,
}: {
  vault: string
  label: string
  links: readonly EntityLink[]
  /** Labels of `data.kind` values. */
  kinds: Readonly<Record<string, string>>
  empty: string
  /** This entity's dimension: others elsewhere are marked (portals cross dimensions). */
  dimension?: string | null
}) {
  const registry = useKindRegistry(vault)
  if (links.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>
  return (
    <ul aria-label={label} className="flex flex-col gap-1">
      {links.map(({ link, other }) => {
        const Icon = registry?.kind(other.kind)?.icon
        const value = link.data.kind
        const detail = typeof value === 'string' ? (kinds[value] ?? value) : null
        return (
          <li key={link.id} className="flex items-center gap-1.5 text-sm">
            {Icon && <Icon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />}
            <Link
              to="/v/$vault/e/$entity"
              params={{ vault, entity: other.id }}
              className="truncate text-primary underline-offset-2 hover:underline"
            >
              {other.name}
            </Link>
            {detail !== null && <span className="text-xs text-muted-foreground">{detail}</span>}
            {dimension != null &&
              other.dimension_id !== null &&
              other.dimension_id !== dimension && (
                <span className="text-xs text-muted-foreground">(another dimension)</span>
              )}
          </li>
        )
      })}
    </ul>
  )
}
