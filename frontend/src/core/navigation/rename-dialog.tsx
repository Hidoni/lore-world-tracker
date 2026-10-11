import { useState } from 'react'

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

/** Renames an entity (sidebar, lists). */
export function RenameDialog({
  name,
  busy,
  onClose,
  onRename,
}: {
  name: string
  busy: boolean
  onClose: () => void
  onRename: (name: string) => void
}) {
  const [value, setValue] = useState(name)
  const trimmed = value.trim()
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault()
            if (trimmed !== '' && trimmed !== name) onRename(trimmed)
            else onClose()
          }}
        >
          <DialogHeader>
            <DialogTitle>Rename {name}</DialogTitle>
            <DialogDescription>Links and mentions keep pointing at it.</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rename-entity">Name</Label>
            <Input
              id="rename-entity"
              value={value}
              onChange={(event) => {
                setValue(event.target.value)
              }}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy || trimmed === ''}>
              Rename
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
