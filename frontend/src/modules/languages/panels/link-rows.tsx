import { Link } from '@tanstack/react-router'

import type { components } from '@/data'

type EntityLink = components['schemas']['EntityLink']

const FLUENCY: Record<string, string> = {
  native: 'native',
  fluent: 'fluent',
  conversational: 'conversational',
  basic: 'basic',
}

/** Links as rows: the other end and the link's fluency or note. */
export function LinkRows({
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
      {items.map((item) => {
        const { fluency, note } = item.link.data
        const detail =
          typeof fluency === 'string'
            ? (FLUENCY[fluency] ?? fluency)
            : typeof note === 'string'
              ? note
              : null
        return (
          <li key={item.link.id} className="text-sm">
            <Link
              to="/v/$vault/e/$entity"
              params={{ vault, entity: item.other.id }}
              className="text-primary underline-offset-2 hover:underline"
            >
              {item.other.name}
            </Link>
            {detail !== null && <span className="text-xs text-muted-foreground"> ({detail})</span>}
          </li>
        )
      })}
    </ul>
  )
}

/** A titled group of rows, left out when empty. */
export function RowsSection({
  vault,
  title,
  items,
}: {
  vault: string
  title: string
  items: readonly EntityLink[]
}) {
  if (items.length === 0) return null
  return (
    <section aria-label={title} className="flex flex-col gap-1">
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      <LinkRows vault={vault} label={title} items={items} />
    </section>
  )
}
