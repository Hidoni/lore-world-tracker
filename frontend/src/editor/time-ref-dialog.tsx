import type { TimePoint } from '@lore/chronology'
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
import { TimePointPicker, useTimeContext } from '@/core/time'

/**
 * Picks the date a `timeRef` shows (frontend.md §6): a time point in the current dimension's
 * calendars, an absolute moment, or relative to another record.
 */
export function TimeRefDialog({
  vault,
  onInsert,
  onClose,
}: {
  vault: string
  onInsert: (point: TimePoint) => void
  onClose: () => void
}) {
  const { dimension, lenses } = useTimeContext(vault)
  const [point, setPoint] = useState<TimePoint | null>(null)
  const insert = () => {
    if (point === null) return
    onInsert(point)
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Insert a date</DialogTitle>
          <DialogDescription>Each reader sees it in their own display calendar.</DialogDescription>
        </DialogHeader>
        {dimension === null ? (
          <p className="text-sm text-muted-foreground">Choose a dimension first.</p>
        ) : (
          <TimePointPicker
            dimension={dimension}
            lenses={lenses}
            value={null}
            label="Date"
            onChange={setPoint}
            onConfirm={insert}
          />
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={point === null} onClick={insert}>
            Insert
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
