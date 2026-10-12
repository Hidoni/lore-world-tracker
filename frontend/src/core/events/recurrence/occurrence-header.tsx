import { Link } from '@tanstack/react-router'

import { Badge } from '@/components/ui/badge'
import { FieldDisplay, isEmpty } from '@/core/fields'
import { useKind } from '@/core/registry'
import { useEntity, type Entity } from '@/data'

import { eventTime } from '../event-time'

export const STATE_LABEL: Record<string, string> = {
  referenced: 'Customized',
  modified: 'Moved',
  cancelled: 'Cancelled',
}

/** `1` → 1st, `2` → 2nd, `58` → 58th. */
export function ordinal(n: number): string {
  const tens = n % 100
  const suffix = tens >= 11 && tens <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] ?? 'th')
  return `${n}${suffix}`
}

/**
 * The header of a materialized occurrence's page (recurrence.md §7): "Occurrence #58 of
 * <series>", its state, and the series' field values it inherits (shown as defaults where it
 * sets none).
 */
export function OccurrenceHeader({ vault, entity }: { vault: string; entity: Entity }) {
  const time = eventTime(entity)
  const series = useEntity(vault, time.seriesId ?? '', {}, { enabled: time.seriesId !== null })
  const kind = useKind('event', vault)
  if (time.seriesId === null) return null
  const own = entity.fields
  const inherited = (kind?.fields ?? []).filter(
    (field) =>
      !field.archived &&
      isEmpty(own[field.key]) &&
      series.data !== undefined &&
      !isEmpty(series.data.fields[field.key]),
  )
  return (
    <div role="note" className="flex flex-col gap-1 rounded-md border bg-muted/40 p-3 text-sm">
      <p>
        Occurrence{time.occurrenceNumber === null ? '' : ` #${time.occurrenceNumber}`} of{' '}
        {series.data === undefined ? (
          '…'
        ) : (
          <Link
            to="/v/$vault/e/$entity"
            params={{ vault, entity: series.data.id }}
            className="font-medium underline-offset-2 hover:underline"
          >
            {series.data.name}
          </Link>
        )}
        {time.occurrenceState !== null && (
          <Badge variant="outline" className="ml-2">
            {STATE_LABEL[time.occurrenceState] ?? time.occurrenceState}
          </Badge>
        )}
      </p>
      {inherited.length > 0 && series.data !== undefined && (
        <dl aria-label="From the series" className="grid grid-cols-[auto_1fr] gap-x-3 text-xs">
          {inherited.map((field) => (
            <div key={field.key} className="contents">
              <dt className="text-muted-foreground">{field.label}</dt>
              <dd>
                <FieldDisplay vault={vault} field={field} value={series.data.fields[field.key]} />{' '}
                <span className="text-muted-foreground">(from the series)</span>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}
