import { useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  isRevisionConflict,
  keys,
  stringifyDomain,
  useDataSource,
  useUpdateEntity,
  type components,
  type Entity,
} from '@/data'

export type EntityChange = Omit<components['schemas']['EntityUpdate'], 'revision'>

export type SaveResult = { ok: true } | { ok: false; error: unknown }

/**
 * Saves changes to an entity at its current revision (frontend.md §5.1). A `409
 * revision_conflict` opens the conflict dialog: reload theirs (drop mine), overwrite (save mine
 * on top of theirs) or copy mine to the clipboard. Other errors come back to the caller (field
 * errors) and are toasted.
 */
export function useEntitySaver(
  vault: string,
  entity: Entity,
): {
  save: (change: EntityChange) => Promise<SaveResult>
  saving: boolean
  dialog: ReactNode
  /** Changes when a conflict is resolved: editors keyed by it drop their drafts. */
  generation: number
} {
  const update = useUpdateEntity(vault)
  const source = useDataSource()
  const client = useQueryClient()
  const [conflict, setConflict] = useState<EntityChange | null>(null)
  const [busy, setBusy] = useState(false)
  const [generation, setGeneration] = useState(0)

  const save = async (change: EntityChange): Promise<SaveResult> => {
    try {
      await update.mutateAsync({ id: entity.id, body: { ...change, revision: entity.revision } })
      return { ok: true }
    } catch (error) {
      if (isRevisionConflict(error)) setConflict(change)
      return { ok: false, error }
    }
  }

  const reload = async (): Promise<void> => {
    setConflict(null)
    setGeneration((value) => value + 1)
    await client.invalidateQueries({ queryKey: keys.entity(vault, entity.id) })
  }

  const overwrite = async (change: EntityChange): Promise<void> => {
    setBusy(true)
    try {
      const fresh = await source.entity(vault, entity.id)
      await update.mutateAsync({ id: entity.id, body: { ...change, revision: fresh.revision } })
      setConflict(null)
      setGeneration((value) => value + 1)
    } catch (error) {
      if (!isRevisionConflict(error)) setConflict(null)
    } finally {
      setBusy(false)
    }
  }

  const copy = async (change: EntityChange): Promise<void> => {
    try {
      await navigator.clipboard.writeText(stringifyDomain(change))
      toast.success('Your change is on the clipboard')
    } catch {
      toast.error('Couldn’t copy to the clipboard')
    }
  }

  const dialog =
    conflict === null ? null : (
      <Dialog
        open
        onOpenChange={(open) => {
          if (!open) void reload()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Someone saved this entity first</DialogTitle>
            <DialogDescription>
              “{entity.name}” changed since you opened it. Keep their version, save yours on top of
              it, or copy yours to the clipboard first.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => {
                void copy(conflict)
              }}
            >
              Copy mine
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                void reload()
              }}
            >
              Reload theirs
            </Button>
            <Button
              disabled={busy}
              onClick={() => {
                void overwrite(conflict)
              }}
            >
              Overwrite
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    )

  return { save, saving: update.isPending || busy, dialog, generation }
}
