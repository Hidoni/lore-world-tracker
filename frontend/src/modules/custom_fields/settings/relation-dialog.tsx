import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import { useKindRegistry, type Kind } from '@/core/registry'
import { fieldErrors, useCreateLinkType } from '@/data'

import { problemText } from './shared'

/**
 * A relation field ("Wielder → Character"): a custom link type from `kind` to the kinds chosen,
 * read "A Wielder B" (and back with the inverse label), shown like a field on the kind's pages.
 */
export function RelationDialog({
  vault,
  kind,
  onClose,
}: {
  vault: string
  kind: Kind
  onClose: () => void
}) {
  const registry = useKindRegistry(vault)
  const create = useCreateLinkType(vault)
  const [label, setLabel] = useState('')
  const [inverse, setInverse] = useState('')
  const [targets, setTargets] = useState<string[]>([])
  const choices = (registry?.kinds ?? []).filter(
    (other) => !other.capabilities.is_system || other.key === 'dimension',
  )
  const errors = fieldErrors(create.error)
  const failure =
    create.error && Object.keys(errors).length === 0 ? problemText(create.error) : null

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="max-h-[90svh] overflow-y-auto">
        <form
          className="flex flex-col gap-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            create.mutate(
              {
                label: label.trim(),
                inverse_label: inverse.trim() || null,
                source_kinds: [kind.key],
                target_kinds: targets,
              },
              {
                onSuccess: () => {
                  toast.success(`Created ${label.trim()}`)
                  onClose()
                },
              },
            )
          }}
        >
          <DialogHeader>
            <DialogTitle>New relation field</DialogTitle>
            <DialogDescription>
              On {kind.plural}: links to the entities chosen, shown like a field.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="relation-label">Label</Label>
            <Input
              id="relation-label"
              placeholder="Wielder"
              value={label}
              maxLength={100}
              onChange={(event) => {
                setLabel(event.target.value)
              }}
            />
            {errors.label && <p className="text-sm text-destructive">{errors.label}</p>}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="relation-inverse">Seen from the other side</Label>
            <Input
              id="relation-inverse"
              placeholder="Wields"
              value={inverse}
              maxLength={100}
              onChange={(event) => {
                setInverse(event.target.value)
              }}
            />
          </div>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-sm font-medium">Links to</legend>
            <div className="grid grid-cols-2 gap-1">
              {choices.map((other) => (
                <div key={other.key} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    id={`relation-target-${other.key}`}
                    checked={targets.includes(other.key)}
                    onCheckedChange={(checked) => {
                      setTargets(
                        checked === true
                          ? [...targets, other.key]
                          : targets.filter((key) => key !== other.key),
                      )
                    }}
                  />
                  <Label htmlFor={`relation-target-${other.key}`}>{other.label}</Label>
                </div>
              ))}
            </div>
          </fieldset>
          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {failure}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={create.isPending || label.trim() === '' || targets.length === 0}
            >
              Create
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
