import { Link } from '@tanstack/react-router'

import type { components } from '@/data'

type EntityLink = components['schemas']['EntityLink']

/** The other ends of links, as a wrapping list of names. */
export function LinkList({
  vault,
  label,
  items,
}: {
  vault: string
  label: string
  items: readonly EntityLink[]
}) {
  return (
    <ul aria-label={label} className="flex flex-wrap gap-x-4 gap-y-1">
      {items.map((item) => (
        <li key={item.link.id} className="text-sm">
          <Link
            to="/v/$vault/e/$entity"
            params={{ vault, entity: item.other.id }}
            className="text-primary underline-offset-2 hover:underline"
          >
            {item.other.name}
          </Link>
        </li>
      ))}
    </ul>
  )
}
