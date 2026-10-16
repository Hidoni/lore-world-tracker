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
import { iconFor, iconMap, useKindRegistry, type KindRegistry } from '@/core/registry'
import { Section, SELECT_CLASS } from '@/core/settings'
import {
  fieldErrors,
  useCreateCustomKind,
  useCustomKinds,
  useDeleteCustomKind,
  useMutations,
  useUpdateCustomKind,
  type CustomKind,
} from '@/data'

import { problemText, SLUG, slugify, VISIBILITIES, type VisibilityChoice } from './shared'

const CAPABILITIES = [
  { key: 'has_existence', label: 'Exists in time (lifespans, existence facts)' },
  { key: 'can_be_multiversal', label: 'Can be multiversal (no home dimension)' },
  { key: 'can_have_worldline', label: 'Can travel (worldlines)' },
] as const

type Capabilities = CustomKind['capabilities']

/**
 * Settings → Kinds (custom_fields.md, UI): built-in kinds for reference, custom kinds created,
 * edited, archived (they and their entities are hidden) or deleted once no entity has them.
 */
export function KindsSettings({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  const kinds = useCustomKinds(vault)
  const registry = useKindRegistry(vault)
  const update = useUpdateCustomKind(vault)
  const remove = useDeleteCustomKind(vault)
  const [editing, setEditing] = useState<CustomKind | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const custom = kinds.data?.items ?? []
  const builtIn = (registry?.kinds ?? []).filter((kind) => kind.module !== 'custom_fields')

  return (
    <div className="flex flex-col gap-4">
      <Section
        title="Custom kinds"
        description="Kinds of your own (Artifact, Spell, Ship): their entities work like any other."
      >
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {kinds.isSuccess && custom.length === 0 && (
          <p className="text-sm text-muted-foreground">No custom kinds yet.</p>
        )}
        {custom.length > 0 && (
          <ul aria-label="Custom kinds" className="flex flex-col divide-y">
            {custom.map((kind) => {
              const Icon = iconFor(kind.icon)
              return (
                <li key={kind.key} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                  <Icon aria-hidden className="size-4" style={{ color: kind.color }} />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="font-medium">{kind.label}</span>
                    <span className="text-xs text-muted-foreground">
                      {kind.key} · {kind.entities} {kind.entities === 1 ? 'entity' : 'entities'}
                    </span>
                  </div>
                  {kind.archived && <Badge variant="secondary">Archived</Badge>}
                  {editable && (
                    <div className="flex gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Edit ${kind.label}`}
                        onClick={() => {
                          setError(null)
                          setEditing(kind)
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`${kind.archived ? 'Unarchive' : 'Archive'} ${kind.label}`}
                        disabled={update.isPending}
                        onClick={() => {
                          setError(null)
                          update.mutate(
                            {
                              key: kind.key,
                              body: { revision: kind.revision, archived: !kind.archived },
                            },
                            {
                              onError: (failure) => {
                                setError(problemText(failure))
                              },
                            },
                          )
                        }}
                      >
                        {kind.archived ? 'Unarchive' : 'Archive'}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive"
                        aria-label={`Delete ${kind.label}`}
                        disabled={remove.isPending}
                        onClick={() => {
                          setError(null)
                          remove.mutate(kind.key, {
                            onSuccess: () => toast.success(`Deleted ${kind.label}`),
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
            })}
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
            New kind
          </Button>
        )}
      </Section>
      <Section title="Built-in kinds" description="Defined by the app and its modules.">
        <ul aria-label="Built-in kinds" className="flex flex-col divide-y">
          {builtIn.map((kind) => (
            <li key={kind.key} className="flex items-center gap-2 py-2 text-sm">
              <kind.icon aria-hidden className="size-4" style={{ color: kind.color }} />
              <span className="font-medium">{kind.label}</span>
              <span className="text-xs text-muted-foreground">
                {kind.key} · {kind.module}
              </span>
            </li>
          ))}
        </ul>
      </Section>
      {editing !== null && (
        <KindDialog
          vault={vault}
          kind={editing === 'new' ? null : editing}
          registry={registry}
          onClose={() => {
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}

/** The curated icons as a radio group. */
function IconPicker({ value, onChange }: { value: string; onChange: (icon: string) => void }) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-sm font-medium">Icon</legend>
      <div role="radiogroup" aria-label="Icon" className="flex flex-wrap gap-1">
        {Object.entries(iconMap).map(([name, Icon]) => (
          <button
            key={name}
            type="button"
            role="radio"
            aria-checked={value === name}
            aria-label={name}
            title={name}
            className={`rounded-md border p-1.5 ${value === name ? 'border-primary bg-accent' : 'border-transparent hover:bg-accent'}`}
            onClick={() => {
              onChange(name)
            }}
          >
            <Icon aria-hidden className="size-4" />
          </button>
        ))}
      </div>
    </fieldset>
  )
}

/** Creates or edits a custom kind. */
function KindDialog({
  vault,
  kind,
  registry,
  onClose,
}: {
  vault: string
  kind: CustomKind | null
  registry: KindRegistry | undefined
  onClose: () => void
}) {
  const create = useCreateCustomKind(vault)
  const update = useUpdateCustomKind(vault)
  const mutation = kind ? update : create
  const [label, setLabel] = useState(kind?.label ?? '')
  const [plural, setPlural] = useState(kind?.plural ?? '')
  const [slug, setSlug] = useState<string | null>(null) // null: follows the label
  const [icon, setIcon] = useState(kind?.icon ?? 'box')
  const [color, setColor] = useState(kind?.color ?? '#64748b')
  const [description, setDescription] = useState(kind?.description ?? '')
  const [visibility, setVisibility] = useState<VisibilityChoice>(kind?.default_visibility ?? '')
  const [capabilities, setCapabilities] = useState<Capabilities>(
    kind?.capabilities ?? {
      has_existence: true,
      can_be_multiversal: true,
      can_have_worldline: false,
    },
  )
  const key = slug ?? slugify(label)
  const ownKey = kind?.key ?? `custom.${key}`
  const [parents, setParents] = useState<string[]>(kind?.allowed_parents ?? ['misc'])
  const parentChoices = [
    { key: ownKey, label: `${label.trim() || 'This kind'} (itself)` },
    ...(registry?.kinds ?? [])
      .filter((other) => !other.capabilities.is_system && other.key !== ownKey)
      .filter((other) => !other.capabilities.is_time_bound)
      .map((other) => ({ key: other.key, label: other.label })),
  ]
  const errors = fieldErrors(mutation.error)
  const failure =
    mutation.error && Object.keys(errors).length === 0 ? problemText(mutation.error) : null
  const badKey = kind === null && !SLUG.test(key)

  const submit = () => {
    const common = {
      label: label.trim(),
      plural: plural.trim() || `${label.trim()}s`,
      icon,
      color,
      description: description.trim(),
      allowed_parents: parents,
      capabilities,
      default_visibility: visibility === '' ? null : visibility,
    }
    const done = {
      onSuccess: () => {
        toast.success(kind ? `Saved ${common.label}` : `Created ${common.label}`)
        onClose()
      },
    }
    if (kind) update.mutate({ key: kind.key, body: { ...common, revision: kind.revision } }, done)
    else create.mutate({ ...common, key }, done)
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
            <DialogTitle>{kind ? `Edit ${kind.label}` : 'New kind'}</DialogTitle>
            <DialogDescription>
              {kind ? kind.key : `Its entities’ kind will be custom.${key || '…'}.`}
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="kind-label">Label</Label>
              <Input
                id="kind-label"
                placeholder="Artifact"
                value={label}
                maxLength={100}
                onChange={(event) => {
                  setLabel(event.target.value)
                }}
              />
              {errors.label && <p className="text-sm text-destructive">{errors.label}</p>}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="kind-plural">Plural</Label>
              <Input
                id="kind-plural"
                placeholder={label.trim() ? `${label.trim()}s` : 'Artifacts'}
                value={plural}
                maxLength={100}
                onChange={(event) => {
                  setPlural(event.target.value)
                }}
              />
            </div>
          </div>
          {kind === null && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="kind-key">Key</Label>
              <Input
                id="kind-key"
                value={key}
                maxLength={60}
                onChange={(event) => {
                  setSlug(event.target.value)
                }}
              />
              {(errors.key ?? badKey) && (
                <p className="text-sm text-destructive">
                  {errors.key ?? 'Lowercase letters, digits and _, starting with a letter.'}
                </p>
              )}
            </div>
          )}
          <IconPicker value={icon} onChange={setIcon} />
          <div className="flex items-center gap-3">
            <Label htmlFor="kind-color">Color</Label>
            <input
              id="kind-color"
              type="color"
              className="h-8 w-12 rounded border"
              value={color}
              onChange={(event) => {
                setColor(event.target.value)
              }}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="kind-description">Description</Label>
            <Textarea
              id="kind-description"
              value={description}
              onChange={(event) => {
                setDescription(event.target.value)
              }}
            />
          </div>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-sm font-medium">Can be nested under</legend>
            <div className="grid grid-cols-2 gap-1">
              {parentChoices.map((choice) => (
                <div key={choice.key} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    id={`kind-parent-${choice.key}`}
                    checked={parents.includes(choice.key)}
                    onCheckedChange={(checked) => {
                      setParents(
                        checked === true
                          ? [...parents, choice.key]
                          : parents.filter((other) => other !== choice.key),
                      )
                    }}
                  />
                  <Label htmlFor={`kind-parent-${choice.key}`}>{choice.label}</Label>
                </div>
              ))}
            </div>
            {errors['allowed_parents.0'] && (
              <p className="text-sm text-destructive">{errors['allowed_parents.0']}</p>
            )}
          </fieldset>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-sm font-medium">Capabilities</legend>
            {CAPABILITIES.map((capability) => (
              <div key={capability.key} className="flex items-center gap-2 text-sm">
                <Checkbox
                  id={`kind-capability-${capability.key}`}
                  checked={capabilities[capability.key] ?? false}
                  onCheckedChange={(checked) => {
                    setCapabilities({ ...capabilities, [capability.key]: checked === true })
                  }}
                />
                <Label htmlFor={`kind-capability-${capability.key}`}>{capability.label}</Label>
              </div>
            ))}
            {errors['capabilities.can_be_multiversal'] && (
              <p className="text-sm text-destructive">
                {errors['capabilities.can_be_multiversal']}
              </p>
            )}
          </fieldset>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="kind-visibility">New entities are</Label>
            <select
              id="kind-visibility"
              className={SELECT_CLASS}
              value={visibility}
              onChange={(event) => {
                setVisibility(event.target.value as VisibilityChoice)
              }}
            >
              <option value="">As the vault’s default</option>
              {VISIBILITIES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {failure}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending || label.trim() === '' || badKey}>
              {kind ? 'Save' : 'Create'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
