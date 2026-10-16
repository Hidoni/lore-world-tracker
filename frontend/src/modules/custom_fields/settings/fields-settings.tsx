import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { useKindRegistry } from '@/core/registry'
import { Section, SELECT_CLASS } from '@/components/settings-section'
import {
  useCustomFields,
  useDeleteCustomField,
  useLinkTypes,
  useMutations,
  useReorderCustomFields,
  useUpdateCustomField,
  type CustomField,
} from '@/data'

import { relationTypesOf } from '../relations'
import { FieldDialog } from './field-dialog'
import { RelationDialog } from './relation-dialog'
import { problemText } from './shared'

const GENERAL = 'General'

/**
 * Settings → Fields (custom_fields.md, UI): pick a kind (or every kind), then its custom fields
 * by section, in order: add, edit, reorder, archive (values kept, hidden) or delete (with their
 * values, after confirming). Relation fields are custom link types from the kind.
 */
export function FieldsSettings({ vault }: { vault: string }) {
  const editable = useMutations() !== null
  const registry = useKindRegistry(vault)
  const kinds = (registry?.kinds ?? []).filter((kind) => !kind.capabilities.is_system)
  const [kind, setKind] = useState('*')
  const fields = useCustomFields(vault, kind === '*' ? '*' : kind)
  const linkTypes = useLinkTypes(vault)
  const update = useUpdateCustomField(vault)
  const remove = useDeleteCustomField(vault)
  const reorder = useReorderCustomFields(vault)
  const [editing, setEditing] = useState<CustomField | 'new' | null>(null)
  const [deleting, setDeleting] = useState<CustomField | null>(null)
  const [relation, setRelation] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const items = fields.data?.items ?? []
  const current = registry?.kind(kind)
  const builtIn = (current?.fields ?? []).filter((field) => !field.key.startsWith('custom.'))
  const relations = kind === '*' ? [] : relationTypesOf(linkTypes.data?.items ?? [], kind)
  const sections = [...new Set(items.map((field) => field.section ?? GENERAL))]

  const move = (field: CustomField, by: number) => {
    const own = items.filter((other) => other.kind_key === field.kind_key)
    const index = own.findIndex((other) => other.id === field.id)
    const ids = own.map((other) => other.id)
    const [moved] = ids.splice(index, 1)
    if (moved === undefined) return
    ids.splice(index + by, 0, moved)
    reorder.mutate({ kind_key: field.kind_key, ids })
  }

  const row = (field: CustomField) => {
    const own = items.filter((other) => other.kind_key === field.kind_key)
    const index = own.findIndex((other) => other.id === field.id)
    return (
      <li key={field.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="font-medium">{field.label}</span>
          <span className="text-xs text-muted-foreground">
            {field.key} · {field.type}
            {field.multiple && ' (several)'} · {field.entities_with_values} with values
          </span>
        </div>
        {field.kind_key === '*' && kind !== '*' && <Badge variant="outline">Every kind</Badge>}
        {field.temporal && <Badge variant="outline">Over time</Badge>}
        {field.required && <Badge variant="outline">Required</Badge>}
        {field.default_visibility !== 'public' && (
          <Badge variant="outline">{field.default_visibility}</Badge>
        )}
        {field.archived && <Badge variant="secondary">Archived</Badge>}
        {editable && (
          <div className="flex gap-1">
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Move ${field.label} up`}
              disabled={index <= 0 || reorder.isPending}
              onClick={() => {
                move(field, -1)
              }}
            >
              ↑
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Move ${field.label} down`}
              disabled={index === own.length - 1 || reorder.isPending}
              onClick={() => {
                move(field, 1)
              }}
            >
              ↓
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Edit ${field.label}`}
              onClick={() => {
                setError(null)
                setEditing(field)
              }}
            >
              Edit
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`${field.archived ? 'Unarchive' : 'Archive'} ${field.label}`}
              disabled={update.isPending}
              onClick={() => {
                setError(null)
                update.mutate(
                  { id: field.id, body: { revision: field.revision, archived: !field.archived } },
                  {
                    onError: (failure) => {
                      setError(problemText(failure))
                    },
                  },
                )
              }}
            >
              {field.archived ? 'Unarchive' : 'Archive'}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-destructive"
              aria-label={`Delete ${field.label}`}
              disabled={remove.isPending}
              onClick={() => {
                setError(null)
                if (field.entities_with_values > 0) {
                  setDeleting(field)
                  return
                }
                remove.mutate(
                  { id: field.id },
                  {
                    onSuccess: () => toast.success(`Deleted ${field.label}`),
                    onError: (failure) => {
                      setError(problemText(failure))
                    },
                  },
                )
              }}
            >
              Delete
            </Button>
          </div>
        )}
      </li>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Label htmlFor="fields-kind">Kind</Label>
        <select
          id="fields-kind"
          className={SELECT_CLASS}
          value={kind}
          onChange={(event) => {
            setKind(event.target.value)
          }}
        >
          <option value="*">Every kind</option>
          {kinds.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <Section
        title="Custom fields"
        description={
          kind === '*'
            ? 'Fields every kind has (except dimensions, timelines and calendars).'
            : `${current?.label ?? kind} fields of your own, and those of every kind.`
        }
      >
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {fields.isSuccess && items.length === 0 && (
          <p className="text-sm text-muted-foreground">No custom fields yet.</p>
        )}
        {sections.map((section) => (
          <div key={section} className="flex flex-col">
            <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              {section}
            </h3>
            <ul aria-label={`${section} fields`} className="flex flex-col divide-y">
              {items.filter((field) => (field.section ?? GENERAL) === section).map(row)}
            </ul>
          </div>
        ))}
        {editable && (
          <Button
            variant="outline"
            className="self-start"
            onClick={() => {
              setError(null)
              setEditing('new')
            }}
          >
            New field
          </Button>
        )}
      </Section>
      {kind !== '*' && (
        <Section
          title="Relation fields"
          description="Links to other entities shown like fields (Wielder → Character): custom link types from this kind."
        >
          {relations.length === 0 ? (
            <p className="text-sm text-muted-foreground">No relation fields yet.</p>
          ) : (
            <ul aria-label="Relation fields" className="flex flex-col divide-y">
              {relations.map((type) => (
                <li key={type.key} className="flex items-center gap-2 py-2 text-sm">
                  <span className="font-medium">{type.label}</span>
                  <span className="text-xs text-muted-foreground">
                    →{' '}
                    {type.target_kinds === '*'
                      ? 'any kind'
                      : type.target_kinds
                          .map((target) => registry?.kind(target)?.label ?? target)
                          .join(', ')}
                  </span>
                  {type.archived && <Badge variant="secondary">Archived</Badge>}
                </li>
              ))}
            </ul>
          )}
          {editable && (
            <Button
              variant="outline"
              className="self-start"
              onClick={() => {
                setRelation(true)
              }}
            >
              New relation field
            </Button>
          )}
          <p className="text-xs text-muted-foreground">Edit or archive them in Link types.</p>
        </Section>
      )}
      {kind !== '*' && builtIn.length > 0 && (
        <Section title="Built-in fields" description="Defined by the app and its modules.">
          <ul aria-label="Built-in fields" className="flex flex-col divide-y">
            {builtIn.map((field) => (
              <li key={field.key} className="flex items-center gap-2 py-2 text-sm">
                <span className="font-medium">{field.label}</span>
                <span className="text-xs text-muted-foreground">
                  {field.key} · {field.type}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {editing !== null && (
        <FieldDialog
          vault={vault}
          kind={editing === 'new' ? kind : editing.kind_key}
          field={editing === 'new' ? null : editing}
          onClose={() => {
            setEditing(null)
          }}
        />
      )}
      {deleting !== null && (
        <DeleteFieldDialog
          vault={vault}
          field={deleting}
          onClose={() => {
            setDeleting(null)
          }}
        />
      )}
      {relation && current && (
        <RelationDialog
          vault={vault}
          kind={current}
          onClose={() => {
            setRelation(false)
          }}
        />
      )}
    </div>
  )
}

/** Deleting a field with values deletes them too (one change: undo brings them back). */
function DeleteFieldDialog({
  vault,
  field,
  onClose,
}: {
  vault: string
  field: CustomField
  onClose: () => void
}) {
  const remove = useDeleteCustomField(vault)
  const count = field.entities_with_values
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete {field.label}?</DialogTitle>
          <DialogDescription>
            {count} {count === 1 ? 'entity has a value' : 'entities have values'} for it: they are
            deleted too (undo brings them back). Archive the field to keep them, hidden.
          </DialogDescription>
        </DialogHeader>
        {remove.error && (
          <p role="alert" className="text-sm text-destructive">
            {problemText(remove.error)}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending}
            onClick={() => {
              remove.mutate(
                { id: field.id, deleteValues: true },
                {
                  onSuccess: () => {
                    toast.success(`Deleted ${field.label} and its values`)
                    onClose()
                  },
                },
              )
            }}
          >
            Delete with values
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
