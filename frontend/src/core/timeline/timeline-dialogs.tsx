import type { TimePoint } from '@lore/chronology'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { CausesSection, EventDialog, ParticipantsSection } from '@/core/events'
import { useEntity } from '@/data'

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
  }
}
