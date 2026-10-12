import { Link } from '@tanstack/react-router'
import { LockIcon, XIcon } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EventDialog, IMPORTANCE } from '@/core/events'
import { formatIn, type DimensionTime, type Lens } from '@/core/time'
import { useEntity, useLinks } from '@/data'

import type { WindowItem } from './use-timeline-window'

/** Whether the item is a computed occurrence (it has no event of its own yet). */
export function isComputedOccurrence(item: WindowItem): boolean {
  return item.occurrence_key !== null && item.occurrence_state === null
}

/**
 * The selected item's preview (frontend.md §9.4): name, dates in the display calendar, importance
 * and category, participants, and Open / Edit time.
 */
export function SelectionPreview({
  vault,
  item,
  dimension,
  lens,
  lenses,
  onOpen,
  relative = false,
  onClose,
}: {
  vault: string
  item: WindowItem
  dimension: DimensionTime
  lens: Lens
  lenses: readonly Lens[]
  onOpen: (item: WindowItem) => void
  /** Its start is relative to another record: it isn't dragged; its offset is edited instead. */
  relative?: boolean
  onClose: () => void
}) {
  const computed = isComputedOccurrence(item)
  const participants = useLinks(vault, item.entity_id, {
    type: ['core.participant'],
    direction: 'out',
  })
  const entity = useEntity(vault, item.entity_id, {}, { enabled: !computed })
  const [editing, setEditing] = useState(false)
  const at = (t: bigint | null, precision: string | null, approximate: boolean) =>
    t === null
      ? '—'
      : (formatIn(
          lens,
          { t, precision: precision ?? item.start_precision, approximate },
          dimension,
          lenses,
        ) ?? t.toString())
  const end =
    item.end_kind === 'unknown'
      ? 'Unknown'
      : item.end_kind === 'instant' || item.end_t === item.start_t
        ? null
        : at(item.end_t, item.end_precision, item.end_approximate)
  const people = participants.data?.items ?? []
  return (
    <aside
      aria-label="Selected event"
      className="flex w-72 shrink-0 flex-col gap-2 rounded-md border p-3 text-sm"
    >
      <div className="flex items-start gap-2">
        <h2 className="flex-1 font-medium">
          {computed ? (
            item.name
          ) : (
            <Link
              to="/v/$vault/e/$entity"
              params={{ vault, entity: item.entity_id }}
              className="underline-offset-2 hover:underline"
            >
              {item.name}
            </Link>
          )}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label="Close the preview"
          onClick={onClose}
        >
          <XIcon aria-hidden />
        </Button>
      </div>
      {item.occurrence_key !== null && (
        <p className="text-xs text-muted-foreground">
          {computed
            ? 'An occurrence of a recurring event'
            : `A customized occurrence (${item.occurrence_state ?? ''})`}
        </p>
      )}
      {relative && (
        <p className="flex items-center gap-1 text-xs text-muted-foreground">
          <LockIcon aria-hidden className="size-3" /> Relative to another record: edit its offset
          rather than dragging it.
        </p>
      )}
      <dl className="grid grid-cols-[3.5rem_1fr] gap-x-2 gap-y-1">
        <dt className="text-muted-foreground">Start</dt>
        <dd>{at(item.start_t, item.start_precision, item.start_approximate)}</dd>
        {end !== null && (
          <>
            <dt className="text-muted-foreground">End</dt>
            <dd>{end}</dd>
          </>
        )}
      </dl>
      <div className="flex flex-wrap gap-1">
        <Badge variant="outline">
          Importance {item.importance} · {IMPORTANCE[item.importance] ?? ''}
        </Badge>
        {item.category !== null && <Badge variant="outline">{item.category}</Badge>}
      </div>
      {people.length > 0 && (
        <section aria-label="Participants">
          <h3 className="text-xs font-medium text-muted-foreground uppercase">Participants</h3>
          <ul className="flex flex-col">
            {people.slice(0, 8).map((link) => (
              <li key={link.link.id}>
                <Link
                  to="/v/$vault/e/$entity"
                  params={{ vault, entity: link.other.id }}
                  className="underline-offset-2 hover:underline"
                >
                  {link.other.name}
                </Link>
                {link.link.role ? (
                  <span className="text-muted-foreground"> · {link.link.role}</span>
                ) : null}
              </li>
            ))}
            {people.length > 8 && (
              <li className="text-muted-foreground">and {people.length - 8} more</li>
            )}
          </ul>
        </section>
      )}
      <div className="flex flex-wrap gap-1">
        <Button
          size="sm"
          onClick={() => {
            onOpen(item)
          }}
        >
          Open
        </Button>
        {!computed && entity.data !== undefined && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setEditing(true)
            }}
          >
            {relative ? 'Edit offset' : 'Edit time'}
          </Button>
        )}
      </div>
      {editing && entity.data !== undefined && (
        <EventDialog
          mode="edit"
          vault={vault}
          entity={entity.data}
          parent={null}
          onClose={() => {
            setEditing(false)
          }}
        />
      )}
    </aside>
  )
}
