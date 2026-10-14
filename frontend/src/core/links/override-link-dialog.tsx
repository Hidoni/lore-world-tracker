import type { TimePoint } from '@lore/chronology'
import { useId, useState } from 'react'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TimePointPicker, useDimensionLenses, useTimeContext } from '@/core/time'
import { ApiError, useSaveOverride, type EntityLink } from '@/data'

/**
 * Edit a link in a branch (time-model.md §4.4): an inherited link still valid at the branch point
 * (or the branch's override of one) may change its role and when it ends; its start is the shared
 * past. Saving creates or updates the branch's override.
 */
export function OverrideLinkDialog({
  vault,
  item,
  timelineId,
  branchName,
  onClose,
}: {
  vault: string
  item: EntityLink
  timelineId: string
  branchName: string | null
  onClose: () => void
}) {
  const id = useId()
  const time = useTimeContext(vault)
  const { dimension, lenses } = useDimensionLenses(vault, time.dimensionId)
  const save = useSaveOverride(vault)
  const { link, other } = item
  const [role, setRole] = useState(link.role ?? '')
  const [until, setUntil] = useState<TimePoint | null>((link.valid_to ?? null) as TimePoint | null)
  const failure =
    save.error === null
      ? null
      : save.error instanceof ApiError
        ? (save.error.errors[0]?.message ?? save.error.detail)
        : save.error.message
  const submit = () => {
    save.mutate(
      {
        recordType: 'link',
        rootId: link.overrides_id ?? link.id,
        timelineId,
        changes: {
          role: role.trim() === '' ? null : role.trim(),
          valid_to: until,
        },
      },
      {
        onSuccess: () => {
          toast.success(`The link to ${other.name} changed in ${branchName ?? 'this timeline'}`)
          onClose()
        },
      },
    )
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Edit the link to {other.name} in this timeline</DialogTitle>
          <DialogDescription>
            Only {branchName ?? 'this branch'} changes. When the link starts is shared history, so
            only its role and when it ends can differ.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            submit()
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${id}-role`}>Role</Label>
            <Input
              id={`${id}-role`}
              value={role}
              maxLength={200}
              onChange={(event) => {
                setRole(event.target.value)
              }}
            />
          </div>
          {dimension !== null && (
            <TimePointPicker
              vault={vault}
              dimension={dimension}
              lenses={lenses}
              value={until}
              onChange={setUntil}
              label="Until"
            />
          )}
          {failure !== null && (
            <p role="alert" className="text-sm text-destructive">
              {failure}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save in this timeline'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
