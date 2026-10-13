import { Link } from '@tanstack/react-router'

import { useKindRegistry } from '@/core/registry'
import type { components } from '@/data'

type EntityLink = components['schemas']['EntityLink']

/** What a link adds to its label: rank, title, a leader flag, its role. */
export function linkDetail(item: EntityLink): string | null {
  const { data, role } = item.link
  const text = (value: unknown) => (typeof value === 'string' && value !== '' ? value : null)
  const parts = [
    text(data.rank),
    text(data.title),
    data.is_leader === true ? 'leader' : null,
    text(role),
  ].filter((part): part is string => part !== null)
  return parts.length === 0 ? null : parts.join(', ')
}

/** Links as rows: an optional label, the other end (with its kind's icon) and the details. */
export function LinkRows({
  vault,
  label,
  items,
  showLabel = false,
  extra,
}: {
  vault: string
  label: string
  items: readonly EntityLink[]
  /** Show each link's label ("at war with") before the other end. */
  showLabel?: boolean
  /** More text per row (e.g. the sub-group of a member). */
  extra?: (item: EntityLink) => string | null
}) {
  const registry = useKindRegistry(vault)
  return (
    <ul aria-label={label} className="flex flex-col gap-1">
      {items.map((item) => {
        const Icon = registry?.kind(item.other.kind)?.icon
        const detail = linkDetail(item)
        const more = extra?.(item) ?? null
        return (
          <li key={item.link.id} className="flex flex-wrap items-center gap-1.5 text-sm">
            {showLabel && <span className="text-muted-foreground">{item.label}</span>}
            {Icon && <Icon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />}
            <Link
              to="/v/$vault/e/$entity"
              params={{ vault, entity: item.other.id }}
              className="text-primary underline-offset-2 hover:underline"
            >
              {item.other.name}
            </Link>
            {detail !== null && <span className="text-xs text-muted-foreground">({detail})</span>}
            {more !== null && <span className="text-xs text-muted-foreground">{more}</span>}
          </li>
        )
      })}
    </ul>
  )
}
