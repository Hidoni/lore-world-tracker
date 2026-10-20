import { MapPinPlusIcon, PlusIcon, TagIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { CreateEntityDialog } from '@/core/entities'
import { useEntity, useQuickSearch } from '@/data'

/** What a new pin points at: an entity, or a label. */
export type PinChoice = { target: string } | { label: string }

/**
 * Adding a pin where the map was clicked (or a region just drawn): an entity (search by name), a
 * new location created there (a child of the map's location), or a plain label.
 */
export function AddPinDialog({
  vault,
  location,
  noun = 'pin',
  onAdd,
  onClose,
}: {
  vault: string
  /** What is being added. */
  noun?: 'pin' | 'region'
  /** The map's location (the parent of a location created here). */
  location: string
  onAdd: (choice: PinChoice) => void
  onClose: () => void
}) {
  const [q, setQ] = useState('')
  const [creating, setCreating] = useState(false)
  const found = useQuickSearch(vault, { q })
  const place = useEntity(vault, location)
  const hits = q.trim() === '' ? [] : (found.data?.items ?? [])
  if (creating && place.data !== undefined) {
    return (
      <CreateEntityDialog
        vault={vault}
        initialKind="location"
        initialName={q.trim()}
        initialParent={{
          id: place.data.id,
          name: place.data.name,
          dimension_id: place.data.dimension_id,
        }}
        onClose={onClose}
        onCreated={(entity) => {
          onAdd({ target: entity.id })
        }}
      />
    )
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
          <DialogTitle>Add a {noun}</DialogTitle>
          <DialogDescription>
            {noun === 'pin'
              ? 'Pin a place, a character or an event here, or write a label.'
              : 'The place this region is (its controllers color it), or a label.'}
          </DialogDescription>
        </DialogHeader>
        <Input
          type="search"
          aria-label="Find an entity"
          placeholder="Name…"
          value={q}
          onChange={(event) => {
            setQ(event.target.value)
          }}
        />
        {hits.length > 0 && (
          <ul aria-label="Matches" className="flex max-h-60 flex-col overflow-y-auto">
            {hits.map((hit) => (
              <li key={hit.doc_id}>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-sm hover:bg-accent"
                  onClick={() => {
                    onAdd({ target: hit.entity_id })
                  }}
                >
                  <MapPinPlusIcon aria-hidden className="size-4" />
                  {hit.name}
                  <span className="text-xs text-muted-foreground">{hit.kind}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setCreating(true)
            }}
          >
            <PlusIcon aria-hidden />
            Create a location here
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={q.trim() === ''}
            onClick={() => {
              onAdd({ label: q.trim() })
            }}
          >
            <TagIcon aria-hidden />
            {q.trim() === '' ? 'Add a label' : `Add the label “${q.trim()}”`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
