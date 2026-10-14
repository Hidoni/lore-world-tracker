import type { TimePoint } from '@lore/chronology'
import { useId, useState } from 'react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { CausesSection, EventDialog, ParticipantsSection } from '@/core/events'
import type { DraggedEntity } from '@/core/links'
import { useCreateLink, useEntity } from '@/data'

const PARTICIPANT = 'core.participant'
const CAUSES = 'core.causes'

/** What the timeline opens a dialog for (frontend.md §9.4). */
export type TimelineAction =
  | {
      kind: 'create'
      start: TimePoint | null
      parent: { id: string; name: string; dimension_id: string | null } | null
    }
  | { kind: 'edit'; id: string }
  | { kind: 'participants'; id: string }
  | { kind: 'causes'; id: string }
  /** An entity dropped on an event: a participant, or (an event) a cause or an effect. */
  | { kind: 'drop'; event: { id: string; name: string }; entity: DraggedEntity }

function LinksDialog({
  vault,
  id,
  kind,
  onClose,
}: {
  vault: string
  id: string
  kind: 'participants' | 'causes'
  onClose: () => void
}) {
  const entity = useEntity(vault, id)
  const title = kind === 'participants' ? 'Participants' : 'Causes and effects'
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {title}
            {entity.data === undefined ? '' : ` of ${entity.data.name}`}
          </DialogTitle>
          <DialogDescription>
            {kind === 'participants'
              ? 'Who or what takes part in the event.'
              : 'What led to the event, and what it led to.'}
          </DialogDescription>
        </DialogHeader>
        {entity.data === undefined ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : kind === 'participants' ? (
          <ParticipantsSection vault={vault} entity={entity.data} editable />
        ) : (
          <CausesSection vault={vault} entity={entity.data} editable />
        )}
      </DialogContent>
    </Dialog>
  )
}

/**
 * An entity dropped on a timeline event (visual linking, frontend.md §9.4): another event
 * becomes its cause or effect (the direction asked), anything else a participant (the role
 * asked).
 */
function DropDialog({
  vault,
  event,
  dropped,
  onClose,
}: {
  vault: string
  event: { id: string; name: string }
  dropped: DraggedEntity
  onClose: () => void
}) {
  const id = useId()
  const entity = useEntity(vault, dropped.id)
  const create = useCreateLink(vault)
  const [role, setRole] = useState('')
  const [causes, setCauses] = useState(true)
  const name = entity.data?.name ?? dropped.name ?? '…'
  const isEvent = (entity.data?.kind ?? dropped.kind) === 'event'
  const ready = entity.data !== undefined && dropped.id !== event.id
  const submit = (): void => {
    const body = isEvent
      ? {
          link_type: CAUSES,
          source_id: causes ? dropped.id : event.id,
          target_id: causes ? event.id : dropped.id,
        }
      : {
          link_type: PARTICIPANT,
          source_id: event.id,
          target_id: dropped.id,
          ...(role.trim() === '' ? {} : { role: role.trim() }),
        }
    create.mutate(body, { onSuccess: onClose })
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isEvent ? `Link ${name} and ${event.name}` : `Add ${name} to ${event.name}`}
          </DialogTitle>
          <DialogDescription>
            {dropped.id === event.id
              ? 'An event can’t be linked to itself.'
              : isEvent
                ? 'Which one led to the other?'
                : 'A participant, with an optional role.'}
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(submitted) => {
            submitted.preventDefault()
            if (ready) submit()
          }}
        >
          {isEvent ? (
            <fieldset className="flex flex-col gap-1 text-sm">
              <legend className="sr-only">Direction</legend>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name={`${id}-direction`}
                  checked={causes}
                  onChange={() => {
                    setCauses(true)
                  }}
                />
                {name} causes {event.name}
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name={`${id}-direction`}
                  checked={!causes}
                  onChange={() => {
                    setCauses(false)
                  }}
                />
                {event.name} causes {name}
              </label>
            </fieldset>
          ) : (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-role`}>Role</Label>
              <Input
                id={`${id}-role`}
                value={role}
                maxLength={200}
                placeholder="witness, commander, …"
                onChange={(changed) => {
                  setRole(changed.target.value)
                }}
              />
            </div>
          )}
          {create.error && (
            <p role="alert" className="text-sm text-destructive">
              {create.error.message}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!ready || create.isPending}>
              {isEvent ? 'Link' : 'Add participant'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function EditDialog({ vault, id, onClose }: { vault: string; id: string; onClose: () => void }) {
  const entity = useEntity(vault, id)
  if (entity.data === undefined) return null
  return (
    <EventDialog mode="edit" vault={vault} entity={entity.data} parent={null} onClose={onClose} />
  )
}

/** The dialog of a timeline action: a new event (or sub-event), its time, its links. */
export function TimelineDialogs({
  vault,
  dimensionId,
  timelineId,
  action,
  onClose,
}: {
  vault: string
  dimensionId: string
  timelineId: string | null
  action: TimelineAction
  onClose: () => void
}) {
  switch (action.kind) {
    case 'create':
      return (
        <EventDialog
          mode="create"
          vault={vault}
          dimensionId={dimensionId}
          parent={action.parent}
          initialStart={action.start}
          timelineId={timelineId}
          onClose={onClose}
        />
      )
    case 'edit':
      return <EditDialog vault={vault} id={action.id} onClose={onClose} />
    case 'participants':
    case 'causes':
      return <LinksDialog vault={vault} id={action.id} kind={action.kind} onClose={onClose} />
    case 'drop':
      return (
        <DropDialog vault={vault} event={action.event} dropped={action.entity} onClose={onClose} />
      )
  }
}
