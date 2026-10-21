import { zodResolver } from '@hookform/resolvers/zod'
import { useNavigate } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { z } from 'zod'

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
import { EventForm } from '@/core/events'
import { FieldEditor, fieldsSchema, PLACEHOLDER_TYPES, type FieldDef } from '@/core/fields'
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

/** The kind's required fields the dialog asks for (types with an editor here). */
function requiredFields(kind: Kind): FieldDef[] {
  return kind.fields.filter(
    (field) => field.required && !field.archived && !PLACEHOLDER_TYPES.has(field.type),
  )
}

interface Values {
  name: string
  fields: Record<string, unknown>
}

/** The form of one kind (react-hook-form + the zod schema built from its field definitions). */
function KindForm({
  vault,
  kind,
  dimensions,
  initialName,
  initialParent,
  initialDimension,
  onCreated,
  onCancel,
}: {
  vault: string
  kind: Kind
  dimensions: readonly { id: string; name: string }[]
  initialName: string
  initialParent: { id: string; name: string } | null
  initialDimension: string | null | undefined
  onCreated: (entity: { id: string; name: string }) => void
  onCancel: () => void
}) {
  const create = useCreateEntity(vault)
  const required = useMemo(() => requiredFields(kind), [kind])
  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(1, 'A name is required').max(300, 'At most 300 characters'),
        fields: fieldsSchema(required),
      }),
    [required],
  )
  const form = useForm<Values>({
    resolver: zodResolver(schema) as never,
    defaultValues: { name: initialName, fields: { ...kind.createDefaults } },
  })
  // A multiversal parent leaves the child's placement to its kind's default.
  const [dimension, setDimension] = useState<string | null>(initialDimension ?? null)
  const [parent, setParent] = useState<{ id: string; name: string } | null>(
    initialParent !== null && kind.allowedParents.length > 0 ? initialParent : null,
  )
  const placement =
    dimension ??
    (kind.capabilities.can_be_multiversal ? MULTIVERSAL : (dimensions[0]?.id ?? MULTIVERSAL))
  const serverErrors = fieldErrors(create.error)
  const errors = form.formState.errors

  const submit = form.handleSubmit((values) => {
    create.mutate(
      {
        kind: kind.key,
        name: values.name.trim(),
        dimension_id: placement === MULTIVERSAL ? null : placement,
        parent_id: parent?.id ?? null,
        ...(Object.keys(values.fields).length > 0 ? { fields: values.fields } : {}),
      },
      {
        onSuccess: (result) => {
          onCreated({ id: result.entity.id, name: result.entity.name })
        },
      },
    )
  })

  const nameError = errors.name?.message ?? serverErrors.name
  return (
    <form
      onSubmit={(event) => {
        void submit(event)
      }}
      className="flex flex-col gap-4"
      noValidate
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="new-entity-name">Name</Label>
        <Input
          id="new-entity-name"
          maxLength={300}
          aria-invalid={nameError !== undefined}
          {...form.register('name')}
        />
        {nameError !== undefined && <p className="text-sm text-destructive">{nameError}</p>}
      </div>
      {required.map((field) => {
        const message = errors.fields?.[field.key]?.message ?? serverErrors[`fields.${field.key}`]
        const id = `new-entity-field-${field.key}`
        return (
          <div key={field.key} className="flex flex-col gap-1.5">
            <Label htmlFor={id}>{field.label}</Label>
            <Controller
              control={form.control}
              name={`fields.${field.key}`}
              render={({ field: control }) => (
                <FieldEditor
                  field={field}
                  id={id}
                  suggest={{ vault, kind: kind.key }}
                  value={control.value}
                  invalid={message !== undefined}
                  onChange={control.onChange}
                  onCommit={(next) => {
                    if (next !== undefined) control.onChange(next)
                  }}
                  onCancel={() => undefined}
                />
              )}
            />
            {message !== undefined && <p className="text-sm text-destructive">{message}</p>}
          </div>
        )
      })}
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
          {kind.capabilities.can_be_multiversal && (
            <option value={MULTIVERSAL}>Multiversal (every dimension)</option>
          )}
          {dimensions.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
      </div>
      {kind.allowedParents.length > 0 && (
        <ParentPicker vault={vault} kind={kind} value={parent} onChange={setParent} />
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={create.isPending}>
          Create
        </Button>
      </DialogFooter>
    </form>
  )
}

/**
 * Create an entity of any kind (frontend.md §7): name, kind, its required fields, parent (of an
 * allowed kind) and its dimension, or multiversal where the kind allows it. Opens the new entity.
 */
export function CreateEntityDialog({
  vault,
  initialKind,
  initialName = '',
  initialParent = null,
  onClose,
  onCreated,
}: {
  vault: string
  initialKind?: string
  initialName?: string
  /** A parent to start with (new child), with its dimension (`null`: multiversal). */
  initialParent?: { id: string; name: string; dimension_id: string | null } | null
  onClose: () => void
  /** Called with the new entity instead of opening it (e.g. to link to it). */
  onCreated?: (entity: { id: string; name: string }) => void
}) {
  const registry = useKindRegistry(vault)
  const kinds = creatableKinds(registry?.kinds ?? [])
  const dimensions = useEntities(vault, { kind: ['dimension'], limit: 100 })
  const navigate = useNavigate()
  const [kindKey, setKindKey] = useState(initialKind ?? '')
  const kind = kinds.find((candidate) => candidate.key === (kindKey || kinds[0]?.key))

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
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
            }}
          >
            {kinds.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        {kind?.key === 'event' ? (
          // Events need a start (and take an end, timeline, importance…): their own form.
          <EventForm
            mode="create"
            vault={vault}
            initialName={initialName}
            parent={initialParent?.dimension_id == null ? null : initialParent}
            onClose={onClose}
            onSaved={(entity) => {
              if (onCreated) {
                onCreated({ id: entity.id, name: entity.name })
                return
              }
              void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: entity.id } })
            }}
          />
        ) : (
          kind !== undefined && (
            <KindForm
              key={kind.key}
              vault={vault}
              kind={kind}
              dimensions={dimensions.data?.items ?? []}
              initialName={initialName}
              initialParent={initialParent}
              initialDimension={initialParent?.dimension_id}
              onCancel={onClose}
              onCreated={(entity) => {
                if (onCreated) {
                  onCreated(entity)
                  return
                }
                onClose()
                void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: entity.id } })
              }}
            />
          )
        )}
      </DialogContent>
    </Dialog>
  )
}
