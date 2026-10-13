import { Link } from '@tanstack/react-router'
import { DnaIcon } from 'lucide-react'

import type { EntityViewProps } from '@/core/modules'
import { useLinks } from '@/data'

/** A character's species as chips in the page header (from `species.is_a`). */
export function SpeciesChip({ vault, entityId }: EntityViewProps) {
  const links = useLinks(vault, entityId, { type: ['species.is_a'], direction: 'out' })
  const items = links.data?.items ?? []
  if (items.length === 0) return null
  return (
    <ul aria-label="Species" className="flex flex-col items-start gap-1">
      {items.map((item) => (
        <li key={item.link.id}>
          <Link
            to="/v/$vault/e/$entity"
            params={{ vault, entity: item.other.id }}
            className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs hover:bg-accent"
          >
            <DnaIcon aria-hidden className="size-3" />
            {item.other.name}
          </Link>
        </li>
      ))}
    </ul>
  )
}
