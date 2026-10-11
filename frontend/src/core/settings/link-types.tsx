import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
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
import { Textarea } from '@/components/ui/textarea'
import { useKindRegistry, type KindRegistry } from '@/core/registry'
import {
  ApiError,
  fieldErrors,
  useCreateLinkType,
  useDeleteLinkType,
  useLinkTypes,
  useMutations,
  useUpdateLinkType,
  type components,
} from '@/data'

import { Section, SELECT_CLASS } from './shared'

type LinkType = components['schemas']['LinkTypeOut']
type Temporal = components['schemas']['Temporal']
type Unique = components['schemas']['UniquePolicy']

const TEMPORAL: { value: Temporal; label: string }[] = [
  { value: 'optional', label: 'Optionally dated' },
  { value: 'never', label: 'Timeless' },
  { value: 'required', label: 'Always dated' },
]
const UNIQUE: { value: Unique; label: string }[] = [
  { value: 'none', label: 'Any number per pair' },
  { value: 'per_pair', label: 'One per pair' },
  { value: 'per_pair_per_period', label: 'One per pair at a time' },
]

function kindsText(kinds: LinkType['source_kinds'], registry: KindRegistry | undefined) {
  if (kinds === '*') return 'any kind'
  return kinds.map((key) => registry?.kind(key)?.label ?? key).join(', ')
}

/** What a refused link type change means (`409`: used by links, or edits links would break). */
function problemText(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : 'Failed.'
  const conflicts = error.context.conflicts as Record<string, number> | undefined
  const links = error.context.links as number | undefined
  if (links !== undefined) {
    return `${error.detail} Archive it instead: archived types keep their links but take no new ones.`
  }
  if (conflicts) {
    const parts = Object.entries(conflicts).map(([what, count]) => `${what}: ${count} link(s)`)
    return `${error.detail} (${parts.join('; ')})`
  }
  return error.detail
}

/**
 * Link types (data-model.md §6.2): built-in ones read-only, custom ones created, edited,
 * archived (they keep their links, take no new ones) or deleted when nothing uses them.
 */
export function LinkTypesSettings({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  const types = useLinkTypes(vault)
  const registry = useKindRegistry(vault)
  const update = useUpdateLinkType(vault)
  const remove = useDeleteLinkType(vault)
  const [editing, setEditing] = useState<LinkType | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const items = types.data?.items ?? []
  const builtIn = items.filter((type) => !type.user_defined)
  const custom = items.filter((type) => type.user_defined)

  const row = (type: LinkType) => (
    <li key={type.key} className="flex flex-wrap items-center gap-2 py-2 text-sm">
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="font-medium">
          {type.label}
          {type.inverse_label && (
            <span className="font-normal text-muted-foreground"> / {type.inverse_label}</span>
          )}
        </span>
        <span className="text-xs text-muted-foreground">
          {type.key} · {kindsText(type.source_kinds, registry)} →{' '}
          {kindsText(type.target_kinds, registry)}
          {type.symmetric && ' · symmetric'}
        </span>
      </div>
      {type.archived && <Badge variant="secondary">Archived</Badge>}
      {editable && type.user_defined && (
        <div className="flex gap-1">
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Edit ${type.label}`}
            onClick={() => {
              setError(null)
              setEditing(type)
            }}
          >
            Edit
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={`${type.archived ? 'Unarchive' : 'Archive'} ${type.label}`}
            disabled={update.isPending}
            onClick={() => {
              setError(null)
              update.mutate(
                { key: type.key, body: { revision: type.revision ?? 0, archived: !type.archived } },
                {
                  onError: (failure) => {
                    setError(problemText(failure))
                  },
                },
              )
            }}
          >
            {type.archived ? 'Unarchive' : 'Archive'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive"
            aria-label={`Delete ${type.label}`}
            disabled={remove.isPending}
            onClick={() => {
              setError(null)
              remove.mutate(type.key, {
                onSuccess: () => {
                  toast.success(`Deleted ${type.label}`)
                },
                onError: (failure) => {
                  setError(problemText(failure))
                },
              })
            }}
          >
            Delete
          </Button>
        </div>
      )}
    </li>
  )

  return (
    <div className="flex flex-col gap-4">
      <Section
        title="Custom link types"
        description="Relations of your own (“sworn enemy of”), between the kinds you choose."
      >
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {custom.length === 0 ? (
          <p className="text-sm text-muted-foreground">No custom link types yet.</p>
        ) : (
          <ul aria-label="Custom link types" className="flex flex-col divide-y">
            {custom.map(row)}
          </ul>
        )}
        {editable && (
          <Button
            variant="outline"
            className="self-start"
            onClick={() => {
              setError(null)
              setEditing('new')
            }}
          >
            New link type
          </Button>
        )}
      </Section>
      <Section title="Built-in link types" description="Defined by the app and its modules.">
        <ul aria-label="Built-in link types" className="flex flex-col divide-y">
          {builtIn.map(row)}
        </ul>
      </Section>
      {editing !== null && (
        <LinkTypeDialog
          vault={vault}
          type={editing === 'new' ? null : editing}
          onClose={() => {
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}

function KindsPicker({
  label,
  value,
  onChange,
  registry,
}: {
  label: string
  value: LinkType['source_kinds']
  onChange: (value: LinkType['source_kinds']) => void
  registry: KindRegistry | undefined
}) {
  const id = `link-type-kinds-${label.toLowerCase()}`
  const kinds =
    registry?.kinds.filter((kind) => kind.key !== 'timeline' && kind.key !== 'calendar') ?? []
  const any = value === '*'
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-sm font-medium">{label}</legend>
      <div className="flex items-center gap-2 text-sm">
        <Checkbox
          id={`${id}-any`}
          checked={any}
          onCheckedChange={(checked) => {
            onChange(checked === true ? '*' : [])
          }}
        />
        <Label htmlFor={`${id}-any`}>Any kind</Label>
      </div>
      {!any && (
        <div className="grid grid-cols-2 gap-1 pl-6">
          {kinds.map((kind) => (
            <div key={kind.key} className="flex items-center gap-2 text-sm">
              <Checkbox
                id={`${id}-${kind.key}`}
                checked={value.includes(kind.key)}
                onCheckedChange={(checked) => {
                  onChange(
                    checked === true
                      ? [...value, kind.key]
                      : value.filter((key) => key !== kind.key),
                  )
                }}
              />
              <Label htmlFor={`${id}-${kind.key}`}>{kind.label}</Label>
            </div>
          ))}
        </div>
      )}
    </fieldset>
  )
}

/** Creates or edits a custom link type. */
function LinkTypeDialog({
  vault,
  type,
  onClose,
}: {
  vault: string
  type: LinkType | null
  onClose: () => void
}) {
  const registry = useKindRegistry(vault)
  const create = useCreateLinkType(vault)
  const update = useUpdateLinkType(vault)
  const mutation = type ? update : create
  const [label, setLabel] = useState(type?.label ?? '')
  const [inverse, setInverse] = useState(type?.inverse_label ?? '')
  const [description, setDescription] = useState(type?.description ?? '')
  const [sources, setSources] = useState<LinkType['source_kinds']>(type?.source_kinds ?? '*')
  const [targets, setTargets] = useState<LinkType['target_kinds']>(type?.target_kinds ?? '*')
  const [symmetric, setSymmetric] = useState(type?.symmetric ?? false)
  const [temporal, setTemporal] = useState<Temporal>(type?.temporal ?? 'optional')
  const [unique, setUnique] = useState<Unique>(type?.unique ?? 'none')
  const errors = fieldErrors(mutation.error)
  const failure =
    mutation.error && Object.keys(errors).length === 0 ? problemText(mutation.error) : null
  const invalidKinds =
    sources !== '*' && sources.length === 0
      ? 'source'
      : targets !== '*' && targets.length === 0
        ? 'target'
        : null

  const submit = () => {
    const body = {
      label: label.trim(),
      inverse_label: symmetric || inverse.trim() === '' ? null : inverse.trim(),
      description: description.trim(),
      source_kinds: sources,
      target_kinds: symmetric ? sources : targets,
      symmetric,
      temporal,
      unique,
    }
    const done = {
      onSuccess: () => {
        toast.success(type ? `Saved ${body.label}` : `Created ${body.label}`)
        onClose()
      },
    }
    if (type)
      update.mutate({ key: type.key, body: { ...body, revision: type.revision ?? 0 } }, done)
    else create.mutate(body, done)
  }

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
            submit()
          }}
        >
          <DialogHeader>
            <DialogTitle>{type ? `Edit ${type.label}` : 'New link type'}</DialogTitle>
            <DialogDescription>
              Read as “A {label.trim() || 'label'} B”
              {!symmetric && inverse.trim() && `, and back as “B ${inverse.trim()} A”`}.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="link-type-label">Label</Label>
            <Input
              id="link-type-label"
              placeholder="sworn enemy of"
              value={label}
              maxLength={100}
              onChange={(event) => {
                setLabel(event.target.value)
              }}
            />
            {errors.label && <p className="text-sm text-destructive">{errors.label}</p>}
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Checkbox
              id="link-type-symmetric"
              checked={symmetric}
              disabled={type !== null}
              onCheckedChange={(checked) => {
                setSymmetric(checked === true)
              }}
            />
            <Label htmlFor="link-type-symmetric">
              Symmetric (reads the same both ways, like “allied with”)
            </Label>
          </div>
          {!symmetric && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="link-type-inverse">Inverse label</Label>
              <Input
                id="link-type-inverse"
                placeholder="sworn enemy of"
                value={inverse}
                maxLength={100}
                onChange={(event) => {
                  setInverse(event.target.value)
                }}
              />
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="link-type-description">Description</Label>
            <Textarea
              id="link-type-description"
              value={description}
              onChange={(event) => {
                setDescription(event.target.value)
              }}
            />
          </div>
          <KindsPicker
            label={symmetric ? 'Between' : 'From'}
            value={sources}
            onChange={setSources}
            registry={registry}
          />
          {!symmetric && (
            <KindsPicker label="To" value={targets} onChange={setTargets} registry={registry} />
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="link-type-temporal">Dates</Label>
              <select
                id="link-type-temporal"
                className={SELECT_CLASS}
                value={temporal}
                onChange={(event) => {
                  setTemporal(event.target.value as Temporal)
                }}
              >
                {TEMPORAL.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="link-type-unique">Repeats</Label>
              <select
                id="link-type-unique"
                className={SELECT_CLASS}
                value={unique}
                onChange={(event) => {
                  setUnique(event.target.value as Unique)
                }}
              >
                {UNIQUE.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {invalidKinds && (
            <p className="text-sm text-destructive">Choose at least one {invalidKinds} kind.</p>
          )}
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
              disabled={mutation.isPending || label.trim() === '' || invalidKinds !== null}
            >
              {type ? 'Save' : 'Create'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
