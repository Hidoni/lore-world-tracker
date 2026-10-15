import { useActiveModules } from '@/core/modules'
import { MomentDisplay } from '@/core/time'
import { usePresence, useUpdateLink, type Entity, type EntityLink } from '@/data'

const SELECT_CLASS =
  'h-7 rounded-md border border-input bg-transparent px-1 text-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

/**
 * Which visit of a time traveler takes part in an event (time-model.md §11.4): when several
 * segments of the participant's worldline cover the event's start, a choice of them, saved as
 * the link's `data.segment_id`. Nothing to show otherwise (or with the worldlines module off).
 */
export function VisitChoice({
  vault,
  event,
  item,
  editable,
}: {
  vault: string
  event: Entity
  item: EntityLink
  editable: boolean
}) {
  const on = useActiveModules(vault).modules.some((module) => module.id === 'worldlines')
  const ext = (event.ext ?? {}) as { start_t?: unknown; timeline_id?: unknown }
  const start = typeof ext.start_t === 'bigint' ? ext.start_t : null
  const at =
    on && start !== null && event.dimension_id !== null
      ? {
          dimension: event.dimension_id,
          timeline: typeof ext.timeline_id === 'string' ? ext.timeline_id : null,
          t: start,
        }
      : null
  const presence = usePresence(vault, item.other.id, at)
  const update = useUpdateLink(vault)
  const segments = presence.data?.segments ?? []
  if (segments.length < 2) return null
  const chosen = typeof item.link.data.segment_id === 'string' ? item.link.data.segment_id : ''
  const label = `Which visit of ${item.other.name}`
  if (!editable) {
    const segment = segments.find((each) => each.id === chosen)
    return segment === undefined ? null : (
      <span className="text-xs text-muted-foreground">visit {segment.seq}</span>
    )
  }
  return (
    <span className="flex items-center gap-1 text-xs">
      {chosen === '' && <span className="text-amber-600">Which visit?</span>}
      <select
        aria-label={label}
        className={SELECT_CLASS}
        value={chosen}
        disabled={update.isPending}
        onChange={(change) => {
          const data = { ...item.link.data }
          if (change.target.value === '') delete data.segment_id
          else data.segment_id = change.target.value
          update.mutate({ id: item.link.id, body: { revision: item.link.revision, data } })
        }}
      >
        <option value="">Choose…</option>
        {segments.map((segment) => (
          <option key={segment.id ?? segment.seq} value={segment.id ?? ''}>
            Visit {segment.seq}
          </option>
        ))}
      </select>
      {segments.map((segment) =>
        segment.id === chosen && segment.start_t !== null ? (
          <span key={segment.id} className="text-muted-foreground">
            from{' '}
            <MomentDisplay
              vault={vault}
              dimension={segment.dimension_id}
              moment={{ t: segment.start_t, precision: 'base' }}
            />
          </span>
        ) : null,
      )}
    </span>
  )
}
