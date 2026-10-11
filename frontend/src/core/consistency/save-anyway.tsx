import { useId, useState } from 'react'
import { create } from 'zustand'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useEntity, type BlockingFinding } from '@/data'

interface Pending {
  vault: string
  findings: BlockingFinding[]
  resolve: (note: string | null) => void
}

interface SaveAnywayState {
  pending: Pending | null
  /** Shows the dialog; resolves to the author's note, or `null` when they cancel. */
  request: (vault: string, findings: BlockingFinding[]) => Promise<string | null>
  settle: (note: string | null) => void
}

export const useSaveAnyway = create<SaveAnywayState>()((set, get) => ({
  pending: null,
  request: (vault, findings) =>
    new Promise((resolve) => {
      // A newer refusal replaces one still open: that one gives up.
      get().pending?.resolve(null)
      set({ pending: { vault, findings, resolve } })
    }),
  settle: (note) => {
    get().pending?.resolve(note)
    set({ pending: null })
  },
}))

/** The `SaveAnywayPrompt` for `withSaveAnyway`. */
export function requestSaveAnyway(vault: string, findings: BlockingFinding[]) {
  return useSaveAnyway.getState().request(vault, findings)
}

function SubjectName({ vault, id }: { vault: string; id: string }) {
  const entity = useEntity(vault, id)
  return <>{entity.data?.name ?? 'an entity'}</>
}

/**
 * "Save anyway" (consistency.md §5): a write refused with `422 consistency_error` lists its
 * blocking findings here. When they can all be suppressed, a note marks the save intentional and
 * the write is resent with `suppress`; hard rules can't be saved anyway.
 */
export function SaveAnywayDialog() {
  const pending = useSaveAnyway((state) => state.pending)
  const settle = useSaveAnyway((state) => state.settle)
  if (pending === null) return null
  return (
    <SaveAnywayContent
      key={pending.findings.map((f) => f.fingerprint).join()}
      pending={pending}
      settle={settle}
    />
  )
}

function SaveAnywayContent({
  pending,
  settle,
}: {
  pending: Pending
  settle: (note: string | null) => void
}) {
  const [note, setNote] = useState('')
  const noteId = useId()
  const blocked = pending.findings.some((finding) => !finding.suppressible)
  const trimmed = note.trim()
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) settle(null)
      }}
    >
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{blocked ? 'Can’t save this' : 'Save anyway?'}</DialogTitle>
          <DialogDescription>
            {blocked
              ? 'It breaks a rule that can’t be overridden.'
              : 'This change breaks consistency rules. Save it anyway if it’s intentional.'}
          </DialogDescription>
        </DialogHeader>
        <ul className="flex flex-col gap-2 text-sm">
          {pending.findings.map((finding) => (
            <li key={finding.fingerprint || finding.rule_id} className="rounded-md border p-2">
              <p>{finding.message}</p>
              <p className="text-xs text-muted-foreground">
                {finding.rule_id}
                {finding.subjects.length > 0 && ' · '}
                {finding.subjects.map((id, index) => (
                  <span key={id}>
                    {index > 0 && ', '}
                    <SubjectName vault={pending.vault} id={id} />
                  </span>
                ))}
                {!finding.suppressible && ' · can’t be overridden'}
              </p>
            </li>
          ))}
        </ul>
        {!blocked && (
          <div className="flex flex-col gap-1.5">
            <label htmlFor={noteId} className="text-sm font-medium">
              Why is this intentional?
            </label>
            <Textarea
              id={noteId}
              value={note}
              maxLength={2000}
              onChange={(event) => {
                setNote(event.target.value)
              }}
            />
          </div>
        )}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              settle(null)
            }}
          >
            {blocked ? 'Close' : 'Cancel'}
          </Button>
          {!blocked && (
            <Button
              type="button"
              disabled={trimmed === ''}
              onClick={() => {
                settle(trimmed)
              }}
            >
              Save anyway (intentional)
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
