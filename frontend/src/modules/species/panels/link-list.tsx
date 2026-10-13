import { Link } from '@tanstack/react-router'

import { certaintyProps } from '@/core/time'
import type { EntityLink } from '@/data'
import { cn } from '@/lib/utils'

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
        <li
          key={item.link.id}
          {...certaintyProps(item.certainty)}
          className={cn('text-sm', certaintyProps(item.certainty).className)}
        >
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
