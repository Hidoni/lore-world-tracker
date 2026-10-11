import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useChildren } from '@/data'

function ConfirmDialog({
  title,
  description,
  confirm,
  destructive,
  busy,
  onConfirm,
  onClose,
}: {
  title: string
  description: string
  confirm: string
  destructive?: boolean
  busy: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <Button
            variant={destructive ? 'destructive' : 'default'}
            disabled={busy}
            onClick={onConfirm}
          >
            {confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Move to trash, warning about children (they stay, shown as roots). */
export function TrashDialog({
  vault,
  entityId,
  name,
  busy,
  onConfirm,
  onClose,
}: {
  vault: string
  entityId: string
  name: string
  busy: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  const children = useChildren(vault, entityId, { limit: 1 })
  const hasChildren = (children.data?.items.length ?? 0) > 0
  return (
    <ConfirmDialog
      title={`Move “${name}” to the trash?`}
      description={
        hasChildren
          ? 'It has children: they stay where they are and show as top-level entries until you restore it. Its links and history are kept.'
          : 'You can restore it from the trash. Its links and history are kept.'
      }
      confirm="Move to trash"
      destructive
      busy={busy}
      onConfirm={onConfirm}
      onClose={onClose}
    />
  )
}

/** Permanent deletion (author only, from the trash). */
export function PurgeDialog({
  name,
  busy,
  onConfirm,
  onClose,
}: {
  name: string
  busy: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  return (
    <ConfirmDialog
      title={`Delete “${name}” permanently?`}
      description="This can’t be undone: the entity and its links are deleted. Its history stays in the change feed."
      confirm="Delete permanently"
      destructive
      busy={busy}
      onConfirm={onConfirm}
      onClose={onClose}
    />
  )
}
