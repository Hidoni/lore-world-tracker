import { Suspense, useRef } from 'react'

import type { EntityViewProps } from '@/core/modules'
import { useBranching } from '@/core/time'
import { ApiError, useMutations, useSaveTimelineNote, useTimelineNote } from '@/data'
import { isDoc, LazyRichTextEditor, RichTextView, type SaveOutcome } from '@/editor'

/**
 * Per-timeline notes (time-model.md §4.6): what is different about this entity in the viewed
 * branch ("In this timeline she became a pirate"), next to the shared page body. Authors edit it
 * in place (autosaved; an emptied note is deleted); readers see it filtered.
 */
export function TimelineNotesPanel({ vault, entityId }: EntityViewProps) {
  const branching = useBranching(vault)
  const timeline = branching.inBranch ? branching.timelineId : null
  const note = useTimelineNote(vault, entityId, timeline)
  const editable = useMutations() !== null
  const name = branching.name(timeline) ?? 'this branch'
  if (timeline === null) return null
  if (note.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (note.isError) {
    return (
      <p className="text-sm text-muted-foreground">
        {note.error instanceof ApiError && note.error.status === 404
          ? `${name} doesn’t have this entity.`
          : 'The notes couldn’t be loaded.'}
      </p>
    )
  }
  const doc = isDoc(note.data.body) ? note.data.body : null
  if (!editable) {
    return doc === null ? (
      <p className="text-sm text-muted-foreground">No notes for {name}.</p>
    ) : (
      <RichTextView vault={vault} doc={doc} />
    )
  }
  return (
    <NotesEditor
      key={timeline}
      vault={vault}
      entityId={entityId}
      timeline={timeline}
      name={name}
      initial={doc}
      revision={note.data.revision}
    />
  )
}

function NotesEditor({
  vault,
  entityId,
  timeline,
  name,
  initial,
  revision,
}: {
  vault: string
  entityId: string
  timeline: string
  name: string
  initial: Parameters<typeof RichTextView>[0]['doc']
  revision: number
}) {
  const save = useSaveTimelineNote(vault, entityId, timeline)
  // Autosave saves repeatedly: each save goes from the revision the last one returned.
  const current = useRef(revision)
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading the editor…</p>}>
      <LazyRichTextEditor
        vault={vault}
        initial={initial}
        label={`Notes in ${name}`}
        placeholder={`What is different about it in ${name}…`}
        save={async (body): Promise<SaveOutcome> => {
          try {
            const saved = await save.mutateAsync({ body, revision: current.current })
            current.current = saved.revision
            return 'saved'
          } catch (error) {
            return error instanceof ApiError && error.status === 409 ? 'conflict' : 'failed'
          }
        }}
      />
    </Suspense>
  )
}
