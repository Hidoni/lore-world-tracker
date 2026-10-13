import { Link } from '@tanstack/react-router'

import { useKindRegistry } from '@/core/registry'
import type { components } from '@/data'

type EntityLink = components['schemas']['EntityLink']

/** Words for the `data.kind` values of the module's link types. */
const KINDS: Record<string, string> = {
  biological: 'biological',
  adoptive: 'adoptive',
  step: 'step',
  foster: 'foster',
  full: 'full',
  half: 'half',
  marriage: 'married',
  partnership: 'partners',
  betrothal: 'betrothed',
}

/** What a link adds to its label: its `data.kind`, `data.capacity` or role. */
export function linkDetail(item: EntityLink): string | null {
  const { data, role } = item.link
  const parts = [
    typeof data.kind === 'string' ? (KINDS[data.kind] ?? data.kind) : null,
    typeof data.capacity === 'string' ? data.capacity : null,
    role,
  ].filter((part): part is string => part !== null && part !== '')
  return parts.length === 0 ? null : parts.join(', ')
}

/** Links as "label Other (detail)" rows, with the other end's kind icon. */
export function LinkRows({
  vault,
  label,
  items,
}: {
  vault: string
  label: string
  items: readonly EntityLink[]
}) {
  const registry = useKindRegistry(vault)
  return (
    <ul aria-label={label} className="flex flex-col gap-1">
      {items.map((item) => {
        const Icon = registry?.kind(item.other.kind)?.icon
        const detail = linkDetail(item)
        return (
          <li key={item.link.id} className="flex flex-wrap items-center gap-1.5 text-sm">
            <span className="text-muted-foreground">{item.label}</span>
            {Icon && <Icon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />}
            <Link
              to="/v/$vault/e/$entity"
              params={{ vault, entity: item.other.id }}
              className="text-primary underline-offset-2 hover:underline"
            >
              {item.other.name}
            </Link>
            {detail !== null && <span className="text-xs text-muted-foreground">({detail})</span>}
          </li>
        )
      })}
    </ul>
  )
}
