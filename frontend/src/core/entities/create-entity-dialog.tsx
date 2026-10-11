import { useNavigate } from '@tanstack/react-router'
import { useState, type ComponentProps } from 'react'

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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useKindRegistry, type Kind } from '@/core/registry'
import { fieldErrors, useCreateEntity, useEntities } from '@/data'

const MULTIVERSAL = ''
const SELECT_CLASS =
  'h-9 w-full rounded-md border bg-transparent px-3 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

/** Kinds a user creates through this dialog: system kinds (dimensions, calendars…) have wizards. */
export function creatableKinds(kinds: readonly Kind[]): Kind[] {
  return kinds.filter((kind) => !kind.capabilities.is_system)
}

function ParentPicker({
  vault,
  kind,
  value,
  onChange,
}: {
  vault: string
  kind: Kind
  value: { id: string; name: string } | null
  onChange: (parent: { id: string; name: string } | null) => void
}) {
  const [query, setQuery] = useState('')
  const options = useEntities(vault, {
    kind: [...kind.allowedParents],
    ...(query.trim() ? { q: query.trim() } : {}),
    limit: 8,
  })
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-sm font-medium">Parent</legend>
      <Input
        aria-label="Search parents"
        placeholder="Search…"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value)
        }}
      />
      <ul aria-label="Parents" className="flex max-h-40 flex-col overflow-y-auto text-sm">
        <li>
          <label className="flex items-center gap-2 px-1 py-0.5">
            <input
              type="radio"
              name="parent"
              checked={value === null}
              onChange={() => {
                onChange(null)
              }}
            />
            No parent
          </label>
        </li>
        {options.data?.items.map((option) => (
          <li key={option.id}>
            <label className="flex items-center gap-2 px-1 py-0.5">
              <input
                type="radio"
                name="parent"
                checked={value?.id === option.id}
                onChange={() => {
                  onChange({ id: option.id, name: option.name })
                }}
              />
              {option.name}
            </label>
          </li>
        ))}
      </ul>
    </fieldset>
  )
}

/**
 * Create an entity of any kind (frontend.md §7): name, kind, parent (of an allowed kind) and its
 * dimension, or multiversal where the kind allows it. Opens the new entity's page.
 */
export function CreateEntityDialog({
  vault,
  initialKind,
  onClose,
}: {
  vault: string
  initialKind?: string
  onClose: () => void
}) {
  const registry = useKindRegistry(vault)
  const kinds = creatableKinds(registry?.kinds ?? [])
  const dimensions = useEntities(vault, { kind: ['dimension'], limit: 100 })
  const create = useCreateEntity(vault)
  const navigate = useNavigate()
  const [kindKey, setKindKey] = useState(initialKind ?? '')
  const [name, setName] = useState('')
  const [dimension, setDimension] = useState<string | null>(null)
  const [parent, setParent] = useState<{ id: string; name: string } | null>(null)
  const kind = kinds.find((candidate) => candidate.key === (kindKey || kinds[0]?.key))
  const dimensionItems = dimensions.data?.items ?? []
  const placement =
    dimension ??
    (kind?.capabilities.can_be_multiversal ? MULTIVERSAL : (dimensionItems[0]?.id ?? MULTIVERSAL))
  const errors = fieldErrors(create.error)

  const onSubmit: NonNullable<ComponentProps<'form'>['onSubmit']> = (event) => {
    event.preventDefault()
    if (kind === undefined || !name.trim()) return
    create.mutate(
      {
        kind: kind.key,
        name: name.trim(),
        dimension_id: placement === MULTIVERSAL ? null : placement,
        parent_id: parent?.id ?? null,
      },
      {
        onSuccess: (result) => {
          onClose()
          void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: result.entity.id } })
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
      <DialogContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>New {kind?.label.toLowerCase() ?? 'entity'}</DialogTitle>
            <DialogDescription>
              {kind !== undefined && kind.description !== ''
                ? kind.description
                : 'Create an entity of any kind.'}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="new-entity-kind">Kind</Label>
            <select
              id="new-entity-kind"
              className={SELECT_CLASS}
              value={kind?.key ?? ''}
              onChange={(event) => {
                setKindKey(event.target.value)
                setParent(null)
                setDimension(null)
              }}
            >
              {kinds.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="new-entity-name">Name</Label>
            <Input
              id="new-entity-name"
              value={name}
              maxLength={300}
              aria-invalid={errors.name !== undefined}
              onChange={(event) => {
                setName(event.target.value)
              }}
            />
            {errors.name !== undefined && <p className="text-sm text-destructive">{errors.name}</p>}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="new-entity-dimension">Dimension</Label>
            <select
              id="new-entity-dimension"
              className={SELECT_CLASS}
              value={placement}
              onChange={(event) => {
                setDimension(event.target.value)
              }}
            >
              {kind?.capabilities.can_be_multiversal && (
                <option value={MULTIVERSAL}>Multiversal (every dimension)</option>
              )}
              {dimensionItems.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.name}
                </option>
              ))}
            </select>
          </div>
          {kind !== undefined && kind.allowedParents.length > 0 && (
            <ParentPicker vault={vault} kind={kind} value={parent} onChange={setParent} />
          )}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={kind === undefined || !name.trim() || create.isPending}>
              Create
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
