import { useNavigate } from '@tanstack/react-router'
import { MoreHorizontalIcon, PencilIcon } from 'lucide-react'
import { useEffect, useRef, useState, type ComponentProps } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Kind } from '@/core/registry'
import {
  useDeleteEntity,
  useEntity,
  useMutations,
  useUpdateEntity,
  type components,
  type Entity,
} from '@/data'

import { Breadcrumbs } from './breadcrumbs'
import { ListEditor } from './list-editor'
import { TrashDialog } from './trash-dialogs'

type EntityUpdate = components['schemas']['EntityUpdate']
type Visibility = components['schemas']['Visibility']

const VISIBILITIES: { value: Visibility; label: string }[] = [
  { value: 'public', label: 'Public' },
  { value: 'spoiler', label: 'Spoiler' },
  { value: 'private', label: 'Private' },
]

function isVisibility(value: string): value is Visibility {
  return VISIBILITIES.some((option) => option.value === value)
}

function NameEditor({
  name,
  onSave,
  busy,
}: {
  name: string
  onSave: (name: string) => void
  busy: boolean
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const editing = draft !== null
  useEffect(() => {
    if (editing) input.current?.select()
  }, [editing])
  if (draft === null) {
    return (
      <div className="flex items-center gap-1">
        <h1 className="text-2xl font-semibold">{name}</h1>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Rename"
          onClick={() => {
            setDraft(name)
          }}
        >
          <PencilIcon />
        </Button>
      </div>
    )
  }
  const onKeyDown: NonNullable<ComponentProps<'input'>['onKeyDown']> = (event) => {
    if (event.key === 'Escape') setDraft(null)
    if (event.key !== 'Enter') return
    event.preventDefault()
    const trimmed = draft.trim()
    if (trimmed && trimmed !== name) onSave(trimmed)
    setDraft(null)
  }
  return (
    <>
      <h1 className="sr-only">{name}</h1>
      <Input
        aria-label="Name"
        ref={input}
        value={draft}
        maxLength={300}
        disabled={busy}
        className="h-9 max-w-md text-xl font-semibold"
        onChange={(event) => {
          setDraft(event.target.value)
        }}
        onKeyDown={onKeyDown}
        onBlur={() => {
          setDraft(null)
        }}
      />
    </>
  )
}

function DimensionBadge({
  vault,
  entity,
  kind,
}: {
  vault: string
  entity: Entity
  kind: Kind | undefined
}) {
  const dimension = useEntity(
    vault,
    entity.dimension_id ?? '',
    {},
    { enabled: entity.dimension_id !== null },
  )
  if (entity.dimension_id === null) {
    return kind?.capabilities.can_be_multiversal ? (
      <Badge variant="outline">Multiversal</Badge>
    ) : null
  }
  return <Badge variant="outline">{dimension.data?.name ?? 'Dimension'}</Badge>
}

/**
 * The entity header (frontend.md §7): icon, inline-editable name, kind badge, dimension or
 * multiversal badge, branch-only badge, breadcrumbs, aliases, tags and visibility. Editing needs
 * `Mutations` (absent in reader mode).
 */
export function EntityHeader({
  vault,
  entity,
  kind,
}: {
  vault: string
  entity: Entity
  kind: Kind | undefined
}) {
  const editable = useMutations() !== null && entity.deleted_at === null
  const update = useUpdateEntity(vault)
  const trash = useDeleteEntity(vault)
  const navigate = useNavigate()
  const [trashing, setTrashing] = useState(false)
  const save = (body: Omit<EntityUpdate, 'revision'>): void => {
    update.mutate({ id: entity.id, body: { ...body, revision: entity.revision } })
  }
  const Icon = kind?.icon
  const aliases = entity.aliases.map((alias) => alias.alias)

  return (
    <header className="flex flex-col gap-3">
      <Breadcrumbs vault={vault} parentId={entity.parent_id} name={entity.name} />
      <div className="flex flex-wrap items-center gap-2">
        {Icon !== undefined && (
          <Icon className="size-6" style={{ color: entity.color ?? kind?.color }} aria-hidden />
        )}
        {editable ? (
          <NameEditor
            name={entity.name}
            busy={update.isPending}
            onSave={(name) => {
              save({ name })
            }}
          />
        ) : (
          <h1 className="text-2xl font-semibold">{entity.name}</h1>
        )}
        <Badge>{kind?.label ?? entity.kind}</Badge>
        <DimensionBadge vault={vault} entity={entity} kind={kind} />
        {entity.origin_timeline_id !== null && <Badge variant="outline">Branch-only</Badge>}
        {entity.deleted_at !== null && <Badge variant="destructive">In the trash</Badge>}
        <div className="flex-1" />
        {editable && (
          <Select
            value={entity.visibility}
            onValueChange={(value) => {
              if (isVisibility(value) && value !== entity.visibility) save({ visibility: value })
            }}
          >
            <SelectTrigger aria-label="Visibility" className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {VISIBILITIES.map(({ value, label }) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {!editable && entity.visibility !== 'public' && (
          <Badge variant="secondary">
            {VISIBILITIES.find((v) => v.value === entity.visibility)?.label}
          </Badge>
        )}
        {editable && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="More actions">
                <MoreHorizontalIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onSelect={() => {
                  setTrashing(true)
                }}
              >
                Move to trash
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Aliases</dt>
        <dd>
          <ListEditor
            label="Aliases"
            values={aliases}
            disabled={update.isPending}
            {...(editable
              ? {
                  onChange: (next: string[]) => {
                    const kept = entity.aliases.filter((alias) => next.includes(alias.alias))
                    const added = next.filter((alias) => !aliases.includes(alias))
                    save({
                      aliases: [
                        ...kept.map(({ id, alias, alias_kind, visibility }) => ({
                          id,
                          alias,
                          alias_kind,
                          visibility,
                        })),
                        ...added.map((alias) => ({ alias })),
                      ],
                    })
                  },
                }
              : {})}
          />
        </dd>
        <dt className="text-muted-foreground">Tags</dt>
        <dd>
          <ListEditor
            label="Tags"
            values={entity.tags.map((tag) => tag.name)}
            disabled={update.isPending}
            {...(editable
              ? {
                  onChange: (tags: string[]) => {
                    save({ tags })
                  },
                }
              : {})}
          />
        </dd>
      </dl>
      {trashing && (
        <TrashDialog
          vault={vault}
          entityId={entity.id}
          name={entity.name}
          busy={trash.isPending}
          onClose={() => {
            setTrashing(false)
          }}
          onConfirm={() => {
            trash.mutate(
              { id: entity.id },
              {
                onSuccess: () => {
                  setTrashing(false)
                  void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: entity.id } })
                },
              },
            )
          }}
        />
      )}
    </header>
  )
}
