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
import { useKindRegistry } from '@/core/registry'
import {
  fieldErrors,
  useCreateLink,
  useLinkTypes,
  useQuickSearch,
  useUpdateLink,
  type components,
} from '@/data'
import { cn } from '@/lib/utils'

import { LinkDataForm } from './link-data-form'
import { linkOptions, type LinkOption } from './link-options'

type Visibility = components['schemas']['Visibility']
type LinkOut = components['schemas']['LinkOut']

const SELECT_CLASS =
  'h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
const VISIBILITIES: { value: Visibility | ''; label: string }[] = [
  { value: '', label: 'Default' },
  { value: 'public', label: 'Public' },
  { value: 'spoiler', label: 'Spoiler' },
  { value: 'private', label: 'Private' },
]

interface Target {
  id: string
  name: string
  kind: string
}

/** What the dialog edits: a new link from `entity`, or an existing link (type and ends fixed). */
export type LinkDialogMode =
  { mode: 'add' } | { mode: 'edit'; link: LinkOut; label: string; other: Target }

/**
 * Adds or edits a link (frontend.md §7): target search, the link types that fit both ends' kinds
 * (in either direction), role, `data` from the type's schema, visibility. Validity fields wait for
 * temporal links (M7-05).
 */
export function LinkDialog({
  vault,
  entity,
  onClose,
  ...props
}: {
  vault: string
  entity: { id: string; name: string; kind: string }
  onClose: () => void
} & LinkDialogMode) {
  const editing = props.mode === 'edit' ? props : null
  const types = useLinkTypes(vault)
  const registry = useKindRegistry(vault)
  const create = useCreateLink(vault)
  const update = useUpdateLink(vault)
  const [target, setTarget] = useState<Target | null>(editing?.other ?? null)
  const [optionId, setOptionId] = useState('')
  const [role, setRole] = useState(editing?.link.role ?? '')
  const [data, setData] = useState<Record<string, unknown>>(editing?.link.data ?? {})
  const [visibility, setVisibility] = useState<Visibility | ''>(editing?.link.visibility ?? '')
  const [badJson, setBadJson] = useState(false)

  const options = linkOptions(types.data?.items ?? [], entity.kind, target?.kind ?? null)
  const option: LinkOption | undefined = editing
    ? undefined
    : (options.find((candidate) => candidate.id === optionId) ?? options[0])
  const linkType = editing
    ? types.data?.items.find((type) => type.key === editing.link.link_type)
    : option?.type
  const needsValidity = linkType?.temporal === 'required'
  const mutation = editing ? update : create
  const errors = fieldErrors(mutation.error)
  const kindLabel = (key: string) => registry?.kind(key)?.label ?? key

  const submit = () => {
    const common = {
      role: role.trim() === '' ? null : role.trim(),
      data,
      ...(visibility === '' ? {} : { visibility }),
    }
    if (editing) {
      update.mutate(
        { id: editing.link.id, body: { ...common, revision: editing.link.revision } },
        { onSuccess: onClose },
      )
      return
    }
    if (target === null || option === undefined) return
    const [source, other] = option.reversed ? [target.id, entity.id] : [entity.id, target.id]
    create.mutate(
      { ...common, link_type: option.type.key, source_id: source, target_id: other },
      { onSuccess: onClose },
    )
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
            <DialogTitle>{editing ? 'Edit link' : `Link ${entity.name}`}</DialogTitle>
            <DialogDescription>
              {editing
                ? `${entity.name} ${editing.label} ${editing.other.name}.`
                : 'Choose what it links to and how.'}
            </DialogDescription>
          </DialogHeader>
          {!editing && (
            <TargetPicker
              vault={vault}
              exclude={entity.id}
              value={target}
              kindLabel={kindLabel}
              onChange={(next) => {
                setTarget(next)
                setOptionId('')
              }}
            />
          )}
          {!editing && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="link-type">Link type</Label>
              <select
                id="link-type"
                className={SELECT_CLASS}
                value={option?.id ?? ''}
                disabled={options.length === 0}
                onChange={(event) => {
                  setOptionId(event.target.value)
                  setData({})
                }}
              >
                {options.length === 0 && <option value="">No link type fits these kinds</option>}
                {options.map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.label}
                  </option>
                ))}
              </select>
              {option && target && (
                <p className="text-xs text-muted-foreground">
                  {entity.name} {option.label} {target.name}
                </p>
              )}
              {errors.link_type && <p className="text-sm text-destructive">{errors.link_type}</p>}
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="link-role">Role</Label>
            <Input
              id="link-role"
              placeholder="e.g. commander"
              maxLength={200}
              value={role}
              onChange={(event) => {
                setRole(event.target.value)
              }}
            />
            {errors.role && <p className="text-sm text-destructive">{errors.role}</p>}
          </div>
          {linkType?.data_schema && (
            <LinkDataForm
              key={linkType.key}
              schema={linkType.data_schema}
              value={data}
              onChange={setData}
              errors={errors}
              onInvalidJson={setBadJson}
            />
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="link-visibility">Visibility</Label>
            <select
              id="link-visibility"
              className={SELECT_CLASS}
              value={visibility}
              onChange={(event) => {
                setVisibility(event.target.value as Visibility | '')
              }}
            >
              {VISIBILITIES.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {choice.label}
                </option>
              ))}
            </select>
          </div>
          <fieldset disabled className="grid grid-cols-2 gap-3 opacity-60">
            <legend className="mb-1 text-sm font-medium">Valid</legend>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="link-valid-from">From</Label>
              <Input id="link-valid-from" placeholder="Always" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="link-valid-to">To</Label>
              <Input id="link-valid-to" placeholder="Always" />
            </div>
            <p className="col-span-2 text-xs text-muted-foreground">
              Dated links arrive with temporal world state (M7).
            </p>
          </fieldset>
          {needsValidity && !editing && (
            <p className="text-sm text-destructive">
              This link type needs validity dates, which can’t be entered yet.
            </p>
          )}
          {mutation.error && Object.keys(errors).length === 0 && (
            <p role="alert" className="text-sm text-destructive">
              {mutation.error.message}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={
                mutation.isPending ||
                badJson ||
                (!editing && (target === null || option === undefined || needsValidity))
              }
            >
              {editing ? 'Save' : 'Add link'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Searches entities by name or alias (`/search/quick`). */
function TargetPicker({
  vault,
  exclude,
  value,
  kindLabel,
  onChange,
}: {
  vault: string
  exclude: string
  value: Target | null
  kindLabel: (kind: string) => string
  onChange: (target: Target | null) => void
}) {
  const [query, setQuery] = useState('')
  const search = useQuickSearch(vault, { q: query.trim() })
  const hits = (search.data?.items ?? []).filter((hit) => hit.entity_id !== exclude).slice(0, 8)
  if (value !== null) {
    return (
      <div className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">Target</span>
        <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
          <span className="flex-1">
            {value.name} <span className="text-muted-foreground">({kindLabel(value.kind)})</span>
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              onChange(null)
            }}
          >
            Change
          </Button>
        </div>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor="link-target">Target</Label>
      <Input
        id="link-target"
        placeholder="Search by name…"
        autoComplete="off"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value)
        }}
      />
      {query.trim() !== '' && (
        <ul aria-label="Targets" className="flex max-h-48 flex-col overflow-y-auto text-sm">
          {hits.length === 0 && !search.isPending && (
            <li className="px-2 py-1 text-muted-foreground">No matches</li>
          )}
          {hits.map((hit) => (
            <li key={hit.entity_id}>
              <button
                type="button"
                className={cn(
                  'flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left hover:bg-accent',
                )}
                onClick={() => {
                  setQuery('')
                  onChange({ id: hit.entity_id, name: hit.name, kind: hit.kind })
                }}
              >
                <span className="flex-1 truncate">{hit.name}</span>
                <span className="text-xs text-muted-foreground">{kindLabel(hit.kind)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
