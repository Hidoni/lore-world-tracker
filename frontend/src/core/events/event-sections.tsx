import { Link } from '@tanstack/react-router'
import { AlertTriangleIcon, PlusIcon, XIcon } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  useCreateLink,
  useDeleteLink,
  useEventTreeLevel,
  useFindings,
  useLinks,
  useMutations,
  type components,
  type Entity,
} from '@/data'

import { EventDialog } from './event-dialog'
import { eventTime } from './event-time'
import { LinkAdder } from './link-adder'

type EntityLink = components['schemas']['EntityLink']

const CAUSES = 'core.causes'
const PARTICIPANT = 'core.participant'
const EFFECT_BEFORE_CAUSE = 'core.event.effect_before_cause'
/** Roles offered while typing (time-model.md §9.4); any text is fine. */
export const ROLE_SUGGESTIONS = [
  'attacker',
  'defender',
  'victim',
  'witness',
  'leader',
  'organizer',
  'casualty',
]

function EntityLinkName({ vault, item }: { vault: string; item: EntityLink }) {
  return (
    <Link
      to="/v/$vault/e/$entity"
      params={{ vault, entity: item.other.id }}
      className="font-medium underline-offset-2 hover:underline"
    >
      {item.other.name}
    </Link>
  )
}

function RemoveLink({ vault, item, label }: { vault: string; item: EntityLink; label: string }) {
  const remove = useDeleteLink(vault)
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-7"
      aria-label={label}
      disabled={remove.isPending}
      onClick={() => {
        remove.mutate(item.link.id)
      }}
    >
      <XIcon aria-hidden />
    </Button>
  )
}

/**
 * The event's sub-events in its timeline, by start (the outline's level under it), with
 * "Create sub-event".
 */
export function SubEventsSection({
  vault,
  entity,
  editable,
}: {
  vault: string
  entity: Entity
  editable: boolean
}) {
  const { timelineId } = eventTime(entity)
  const level = useEventTreeLevel(vault, timelineId, entity.id)
  const [creating, setCreating] = useState(false)
  const items = level.data?.pages.flatMap((page) => page.items) ?? []
  return (
    <div className="flex flex-col gap-2 text-sm">
      {level.isPending ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground">No sub-events.</p>
      ) : (
        <ul aria-label="Sub-events" className="flex flex-col gap-1">
          {items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-baseline gap-2">
              <Link
                to="/v/$vault/e/$entity"
                params={{ vault, entity: item.id }}
                className="font-medium underline-offset-2 hover:underline"
              >
                {item.name}
              </Link>
              <span className="text-xs text-muted-foreground">
                {item.display.start ?? '—'}
                {item.display.end !== null && item.end_t !== item.start_t
                  ? ` – ${item.display.end}`
                  : ''}
              </span>
              {item.has_children && <Badge variant="outline">has sub-events</Badge>}
            </li>
          ))}
        </ul>
      )}
      {level.hasNextPage && (
        <Button
          variant="ghost"
          size="sm"
          className="self-start"
          disabled={level.isFetchingNextPage}
          onClick={() => {
            void level.fetchNextPage()
          }}
        >
          Show more
        </Button>
      )}
      {editable && (
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => {
            setCreating(true)
          }}
        >
          <PlusIcon aria-hidden /> Create sub-event
        </Button>
      )}
      {creating && (
        <EventDialog
          mode="create"
          vault={vault}
          parent={{ id: entity.id, name: entity.name, dimension_id: entity.dimension_id }}
          onClose={() => {
            setCreating(false)
          }}
        />
      )}
    </div>
  )
}

/** One side of the causality: causes (links into the event) or effects (out of it). */
function CausalList({
  vault,
  entity,
  items,
  side,
  flagged,
  editable,
}: {
  vault: string
  entity: Entity
  items: readonly EntityLink[]
  side: 'cause' | 'effect'
  /** Other events a finding names together with this one. */
  flagged: ReadonlySet<string>
  editable: boolean
}) {
  const create = useCreateLink(vault)
  const [creating, setCreating] = useState<string | null>(null)
  const title = side === 'cause' ? 'Causes' : 'Effects'
  const link = (other: string, description: string) => {
    const [source, target] = side === 'cause' ? [other, entity.id] : [entity.id, other]
    create.mutate({
      link_type: CAUSES,
      source_id: source,
      target_id: target,
      ...(description === '' ? {} : { data: { description } }),
    })
  }
  return (
    <section aria-label={title} className="flex flex-col gap-1">
      <h3 className="text-xs font-medium text-muted-foreground uppercase">{title}</h3>
      {items.length === 0 ? (
        <p className="text-muted-foreground">None.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((item) => {
            const description = item.link.data.description
            return (
              <li key={item.link.id} className="flex flex-wrap items-center gap-2">
                <EntityLinkName vault={vault} item={item} />
                {flagged.has(item.other.id) && (
                  <Badge
                    variant="outline"
                    className="border-amber-500/40 text-amber-700 dark:text-amber-400"
                  >
                    <AlertTriangleIcon aria-hidden /> Effect before cause
                  </Badge>
                )}
                {typeof description === 'string' && description !== '' && (
                  <span className="text-muted-foreground">{description}</span>
                )}
                {editable && (
                  <RemoveLink
                    vault={vault}
                    item={item}
                    label={`Remove ${side} ${item.other.name}`}
                  />
                )}
              </li>
            )
          })}
        </ul>
      )}
      {editable && (
        <LinkAdder
          vault={vault}
          label={`Add ${side === 'cause' ? 'a cause' : 'an effect'}`}
          kinds={['event']}
          exclude={new Set([entity.id, ...items.map((item) => item.other.id)])}
          detail={{ label: 'Description', placeholder: 'How (optional)' }}
          pending={create.isPending}
          onAdd={(target, description) => {
            link(target.id, description)
          }}
          onCreate={setCreating}
        />
      )}
      {creating !== null && (
        <EventDialog
          mode="create"
          vault={vault}
          dimensionId={entity.dimension_id}
          initialName={creating}
          onClose={() => {
            setCreating(null)
          }}
          onSaved={(created) => {
            link(created.id, '')
          }}
        />
      )}
    </section>
  )
}

/**
 * Causes and effects (`core.causes`, time-model.md §9.3): linked events on both sides with their
 * descriptions, add (search, or create a new event) and remove, and the `effect_before_cause`
 * finding shown on the pairs it names.
 */
export function CausesSection({
  vault,
  entity,
  editable,
}: {
  vault: string
  entity: Entity
  editable: boolean
}) {
  const links = useLinks(vault, entity.id, { type: [CAUSES] })
  const author = useMutations() !== null
  const findings = useFindings(
    vault,
    { entity: entity.id, rule: [EFFECT_BEFORE_CAUSE] },
    { enabled: author },
  )
  const flagged = new Set(
    (findings.data?.items ?? []).flatMap((finding) =>
      finding.subjects.map((subject) => subject.id).filter((id) => id !== entity.id),
    ),
  )
  const items = links.data?.items ?? []
  return (
    <div className="grid gap-4 text-sm sm:grid-cols-2">
      <CausalList
        vault={vault}
        entity={entity}
        side="cause"
        items={items.filter((item) => item.direction === 'in')}
        flagged={flagged}
        editable={editable}
      />
      <CausalList
        vault={vault}
        entity={entity}
        side="effect"
        items={items.filter((item) => item.direction === 'out')}
        flagged={flagged}
        editable={editable}
      />
    </div>
  )
}

/**
 * Participants (`core.participant`, time-model.md §9.4): entities of any kind with their roles,
 * quick-add from search with role suggestions, and remove.
 */
export function ParticipantsSection({
  vault,
  entity,
  editable,
}: {
  vault: string
  entity: Entity
  editable: boolean
}) {
  const links = useLinks(vault, entity.id, { type: [PARTICIPANT], direction: 'out' })
  const create = useCreateLink(vault)
  const items = links.data?.items ?? []
  return (
    <div className="flex flex-col gap-2 text-sm">
      {links.isPending ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground">No participants yet.</p>
      ) : (
        <ul aria-label="Participants" className="flex flex-col gap-1">
          {items.map((item) => (
            <li key={item.link.id} className="flex flex-wrap items-center gap-2">
              <EntityLinkName vault={vault} item={item} />
              {item.link.role !== null && item.link.role !== '' && (
                <Badge variant="secondary">{item.link.role}</Badge>
              )}
              {editable && (
                <RemoveLink
                  vault={vault}
                  item={item}
                  label={`Remove participant ${item.other.name}`}
                />
              )}
            </li>
          ))}
        </ul>
      )}
      {editable && (
        <LinkAdder
          vault={vault}
          label="Add a participant"
          exclude={new Set([entity.id])}
          detail={{ label: 'Role', placeholder: 'Role (optional)', suggestions: ROLE_SUGGESTIONS }}
          pending={create.isPending}
          onAdd={(target, role) => {
            create.mutate({
              link_type: PARTICIPANT,
              source_id: entity.id,
              target_id: target.id,
              ...(role === '' ? {} : { role }),
            })
          }}
        />
      )}
    </div>
  )
}
