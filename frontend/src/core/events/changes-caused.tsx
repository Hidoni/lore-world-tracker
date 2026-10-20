import { Link } from '@tanstack/react-router'

import { EXISTS, FieldDisplay, NAME } from '@/core/fields'
import { useKind } from '@/core/registry'
import { SpanDisplay } from '@/core/time'
import { useCausedFacts, useEntity, type Fact } from '@/data'

const moment = (t: bigint | null, precision: string | undefined) =>
  t === null ? null : { t, precision: precision ?? 'base' }

function Change({ vault, fact }: { vault: string; fact: Fact }) {
  const entity = useEntity(vault, fact.entity_id)
  const kind = useKind(entity.data?.kind ?? '', vault)
  const field = kind?.fields.find((candidate) => candidate.key === fact.field_key)
  const what =
    fact.field_key === EXISTS
      ? 'exists'
      : fact.field_key === NAME
        ? `is named “${String(fact.value)}”`
        : null
  const dimension = entity.data?.dimension_id ?? null
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 text-sm">
      <Link
        to="/v/$vault/e/$entity"
        params={{ vault, entity: fact.entity_id }}
        className="font-medium hover:underline"
      >
        {entity.data?.name ?? '…'}
      </Link>
      {what !== null ? (
        <span>{what}</span>
      ) : (
        <span>
          {field?.label ?? fact.field_key}:{' '}
          {field !== undefined ? (
            <FieldDisplay vault={vault} field={field} value={fact.value} />
          ) : (
            String(fact.value)
          )}
        </span>
      )}
      {dimension !== null && (
        <span className="text-muted-foreground">
          <SpanDisplay
            vault={vault}
            dimension={dimension}
            start={moment(fact.valid_from_t, fact.valid_from?.precision)}
            end={moment(fact.valid_to_t, fact.valid_to?.precision)}
            startPoint={fact.valid_from}
            endPoint={fact.valid_to}
          />
        </span>
      )}
    </li>
  )
}

/**
 * An event's "changes caused" (frontend.md §7): the facts whose source it is (a birth, a
 * coronation's new title), by entity, field and start.
 */
export function ChangesCausedSection({ vault, eventId }: { vault: string; eventId: string }) {
  const facts = useCausedFacts(vault, eventId)
  const items = facts.data?.items ?? []
  if (facts.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No changes recorded as caused by it.</p>
  }
  return (
    <ul className="flex flex-col gap-1">
      {items.map((fact) => (
        <Change key={fact.id} vault={vault} fact={fact} />
      ))}
    </ul>
  )
}
