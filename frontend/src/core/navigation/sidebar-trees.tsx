import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type Active,
  type Announcements,
  type DragEndEvent,
  type DragStartEvent,
  type Over,
} from '@dnd-kit/core'
import { Link, useParams } from '@tanstack/react-router'
import { ChevronRightIcon, ListIcon, PlusIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import { FindingsBadge } from '@/core/consistency'
import { CreateEntityDialog } from '@/core/entities/create-entity-dialog'
import { useKindRegistry, type Kind, type KindRegistry } from '@/core/registry'
import {
  useDeleteEntity,
  useMutations,
  useRestoreEntity,
  useTreeLevel,
  useUpdateLatest,
  type components,
} from '@/data'
import { cn } from '@/lib/utils'
import { readStored, writeStored } from '@/lib/storage'

import { EventsSection } from './events-section'
import { togglePin, usePlaceList } from './places'
import { RenameDialog } from './rename-dialog'
import { canReparent, childKinds, type TreeEntity } from './reparent'

type TreeNode = components['schemas']['TreeNode']

/** What a drop target carries: the node (`null`: a section's roots) and its ancestors. */
interface DropData {
  node: TreeNode | null
  path: readonly string[]
}

const ROW =
  'group flex min-w-0 items-center gap-1 rounded-md py-1 pr-1 text-sm hover:bg-accent focus-within:bg-accent'

/**
 * The kinds with a sidebar tree: dimensions, then every non-system kind but events (their
 * hierarchy is the events section, by time on a timeline).
 */
export function sectionKinds(registry: KindRegistry): Kind[] {
  return registry.kinds.filter(
    (kind) =>
      kind.key === 'dimension' ||
      (!kind.capabilities.is_system && !kind.capabilities.is_time_bound),
  )
}

const nodeOf = (item: Active | Over | null) =>
  (item?.data.current as { node?: TreeNode | null } | undefined)?.node

/** Screen-reader announcements with entity names (dnd-kit's default reads ids). */
function announcements(registry: KindRegistry): Announcements {
  const where = (over: Over | null) => {
    if (over === null) return 'no place'
    return nodeOf(over)?.name ?? 'the top'
  }
  const verdict = (active: Active, over: Over | null) => {
    const node = nodeOf(active)
    const data = over?.data.current as DropData | undefined
    if (node === undefined || node === null || data === undefined) return ''
    const check = canReparent(registry, node, data.node, data.path)
    return check.ok ? '' : ` ${check.reason}.`
  }
  return {
    onDragStart: ({ active }) => `Picked up ${nodeOf(active)?.name ?? 'an entity'}.`,
    onDragOver: ({ active, over }) =>
      `${nodeOf(active)?.name ?? 'The entity'} is over ${where(over)}.${verdict(active, over)}`,
    onDragEnd: ({ active, over }) =>
      `${nodeOf(active)?.name ?? 'The entity'} was dropped on ${where(over)}.`,
    onDragCancel: ({ active }) => `Moving ${nodeOf(active)?.name ?? 'the entity'} was cancelled.`,
  }
}

const COLLAPSED_KEY = 'lore.sidebar.collapsed'
/** The events section's key among the collapsed sections (not a kind key). */
const EVENTS_KEY = ':events'

function loadCollapsed(): Set<string> {
  try {
    const value: unknown = JSON.parse(readStored(COLLAPSED_KEY) ?? '[]')
    return new Set(Array.isArray(value) ? value.filter((v) => typeof v === 'string') : [])
  } catch {
    return new Set()
  }
}

/**
 * The registry-driven sidebar (frontend.md §3): one section per kind, each a tree by `parent_id`
 * loaded a level at a time (`/tree`). Authors drag entities onto allowed parents (or a section's
 * heading: to the top) and use each row's context menu (new child, rename, pin, move to trash).
 */
export function SidebarTrees({ vault, onNavigate }: { vault: string; onNavigate?: () => void }) {
  const registry = useKindRegistry(vault)
  const editable = useMutations() !== null
  const update = useUpdateLatest(vault)
  const [dragging, setDragging] = useState<TreeNode | null>(null)
  const [collapsed, setCollapsed] = useState(loadCollapsed)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    // Enter follows the link; Space picks the entity up.
    useSensor(KeyboardSensor, {
      keyboardCodes: { start: ['Space'], cancel: ['Escape'], end: ['Space', 'Enter'] },
    }),
  )
  if (registry === undefined) return null

  const toggle = (key: string) => {
    const next = new Set(collapsed)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    setCollapsed(next)
    writeStored(COLLAPSED_KEY, JSON.stringify([...next]))
  }

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    setDragging(null)
    const node = (active.data.current as { node?: TreeNode } | undefined)?.node
    const target = over?.data.current as DropData | undefined
    if (node === undefined || target === undefined) return
    const check = canReparent(registry, node, target.node, target.path)
    if (!check.ok) {
      if (target.node?.id !== node.id) toast.error(check.reason)
      return
    }
    update.mutate(
      { id: node.id, change: { parent_id: target.node?.id ?? null } },
      {
        onSuccess: () => {
          toast.success(
            target.node
              ? `Moved ${node.name} into ${target.node.name}`
              : `Moved ${node.name} to the top`,
          )
        },
      },
    )
  }

  const events = (
    <EventsSection
      vault={vault}
      open={!collapsed.has(EVENTS_KEY)}
      onToggle={() => {
        toggle(EVENTS_KEY)
      }}
      onNavigate={onNavigate}
    />
  )
  const sections = sectionKinds(registry).map((kind) => (
    <KindSection
      key={kind.key}
      vault={vault}
      kind={kind}
      registry={registry}
      editable={editable}
      dragging={dragging}
      open={!collapsed.has(kind.key)}
      onToggle={() => {
        toggle(kind.key)
      }}
      onNavigate={onNavigate}
    />
  ))
  return (
    <>
      <Places
        vault={vault}
        list="pinned"
        title="Pinned"
        registry={registry}
        onNavigate={onNavigate}
      />
      {events}
      {editable ? (
        <DndContext
          sensors={sensors}
          onDragStart={({ active }: DragStartEvent) => {
            setDragging((active.data.current as { node?: TreeNode } | undefined)?.node ?? null)
          }}
          onDragCancel={() => {
            setDragging(null)
          }}
          onDragEnd={onDragEnd}
          accessibility={{
            announcements: announcements(registry),
            screenReaderInstructions: {
              draggable:
                'To move an entity, press space, use the arrow keys to choose its new parent, then press space or enter. Escape cancels.',
            },
          }}
        >
          {sections}
          <DragOverlay dropAnimation={null}>
            {dragging && (
              <div className="rounded-md border bg-popover px-2 py-1 text-sm shadow-md">
                {dragging.name}
              </div>
            )}
          </DragOverlay>
        </DndContext>
      ) : (
        sections
      )}
      <Places
        vault={vault}
        list="recent"
        title="Recent"
        registry={registry}
        onNavigate={onNavigate}
      />
    </>
  )
}

function SectionHeading({
  kind,
  open,
  onToggle,
  dragging,
  registry,
  editable,
  children,
}: {
  kind: Kind
  open: boolean
  onToggle: () => void
  dragging: TreeNode | null
  registry: KindRegistry
  editable: boolean
  children: ReactNode
}) {
  // The heading is the drop target "to the top of this tree".
  const { setNodeRef, isOver } = useDroppable({
    id: `root:${kind.key}`,
    data: { node: null, path: [] } satisfies DropData,
    disabled: !editable,
  })
  const valid = dragging !== null && canReparent(registry, dragging, null).ok
  return (
    <div
      ref={setNodeRef}
      data-tree-row
      className={cn(
        'flex items-center gap-1 rounded-md px-1',
        isOver && (valid ? 'bg-primary/15' : 'bg-destructive/10'),
      )}
    >
      <button
        type="button"
        aria-expanded={open}
        className="flex flex-1 items-center gap-1 py-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
        onClick={onToggle}
      >
        <ChevronRightIcon
          aria-hidden
          className={cn('size-3.5 transition-transform', open && 'rotate-90')}
        />
        {kind.plural}
      </button>
      {children}
    </div>
  )
}

function KindSection({
  vault,
  kind,
  registry,
  editable,
  dragging,
  open,
  onToggle,
  onNavigate,
}: {
  vault: string
  kind: Kind
  registry: KindRegistry
  editable: boolean
  dragging: TreeNode | null
  open: boolean
  onToggle: () => void
  onNavigate: (() => void) | undefined
}) {
  const [creating, setCreating] = useState(false)
  return (
    <section aria-label={kind.plural} className="mt-2 flex flex-col">
      <SectionHeading
        kind={kind}
        open={open}
        onToggle={onToggle}
        dragging={dragging}
        registry={registry}
        editable={editable}
      >
        <Button
          asChild
          variant="ghost"
          size="icon"
          className="size-6 text-muted-foreground"
          title={`All ${kind.plural.toLowerCase()}`}
        >
          <Link
            to="/v/$vault/k/$kind"
            params={{ vault, kind: kind.key }}
            aria-label={`All ${kind.plural.toLowerCase()}`}
            onClick={onNavigate}
          >
            <ListIcon className="size-3.5" />
          </Link>
        </Button>
        {editable && !kind.capabilities.is_system && (
          <Button
            variant="ghost"
            size="icon"
            className="size-6 text-muted-foreground"
            aria-label={`New ${kind.label.toLowerCase()}`}
            title={`New ${kind.label.toLowerCase()}`}
            onClick={() => {
              setCreating(true)
            }}
          >
            <PlusIcon className="size-3.5" />
          </Button>
        )}
      </SectionHeading>
      {open && (
        <TreeLevel
          vault={vault}
          kind={kind}
          registry={registry}
          parent={null}
          path={[]}
          editable={editable}
          dragging={dragging}
          onNavigate={onNavigate}
        />
      )}
      {creating && (
        <CreateEntityDialog
          vault={vault}
          initialKind={kind.key}
          onClose={() => {
            setCreating(false)
          }}
        />
      )}
    </section>
  )
}

interface LevelProps {
  vault: string
  kind: Kind
  registry: KindRegistry
  /** `null`: the section's roots. */
  parent: TreeNode | null
  /** Ancestor ids of this level's nodes, root first. */
  path: readonly string[]
  editable: boolean
  dragging: TreeNode | null
  onNavigate: (() => void) | undefined
}

/** One level of a tree, fetched when shown (a collapsed node loads nothing). */
function TreeLevel(props: LevelProps) {
  const { vault, kind, parent, path } = props
  // The top level of a grouped kind comes in groups (by a text field's value).
  const groupBy = parent === null && kind.groupBy !== null ? kind.groupBy : null
  const level = useTreeLevel(vault, {
    kind: [kind.key],
    ...(parent === null ? {} : { parent: parent.id }),
    ...(groupBy === null ? {} : { group_by: groupBy }),
  })
  const nodes = level.data?.pages.flatMap((page) => page.items) ?? []
  const depth = path.length
  const indent = { paddingLeft: `${depth * 0.75 + 0.25}rem` }
  if (level.isPending) {
    return (
      <p className="py-1 text-xs text-muted-foreground" style={indent}>
        Loading…
      </p>
    )
  }
  if (nodes.length === 0 && parent === null) {
    return (
      <p className="py-1 text-xs text-muted-foreground" style={indent}>
        No {kind.plural.toLowerCase()} yet
      </p>
    )
  }
  const field = kind.fields.find((candidate) => candidate.key === groupBy)
  return (
    <ul className="flex flex-col" aria-label={parent ? `Inside ${parent.name}` : undefined}>
      {groupBy === null
        ? nodes.map((node) => <TreeRow key={node.id} {...props} node={node} />)
        : groupNodes(nodes).map(([group, members]) => {
            const title = group ?? `No ${(field?.label ?? groupBy).toLowerCase()}`
            return (
              <li key={group ?? ''} data-tree-group>
                <p
                  className="truncate pt-1 pl-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase"
                  aria-hidden
                >
                  {title}
                </p>
                <ul className="flex flex-col" aria-label={title}>
                  {members.map((node) => (
                    <TreeRow key={node.id} {...props} node={node} />
                  ))}
                </ul>
              </li>
            )
          })}
      {level.hasNextPage && (
        <li style={indent}>
          <button
            type="button"
            className="py-1 text-xs text-muted-foreground hover:text-foreground"
            disabled={level.isFetchingNextPage}
            onClick={() => {
              void level.fetchNextPage()
            }}
          >
            Show more
          </button>
        </li>
      )}
    </ul>
  )
}

/**
 * Nodes by `group` (case-insensitively, under the most frequent spelling), groups by name with
 * the ungrouped last; nodes keep the tree's order within a group.
 */
export function groupNodes(nodes: readonly TreeNode[]): [string | null, TreeNode[]][] {
  const groups = new Map<string, { spellings: Map<string, number>; members: TreeNode[] }>()
  const loose: TreeNode[] = []
  for (const node of nodes) {
    const value = node.group?.trim() ?? ''
    if (value === '') {
      loose.push(node)
      continue
    }
    const key = value.toLocaleLowerCase()
    const group = groups.get(key) ?? { spellings: new Map<string, number>(), members: [] }
    group.spellings.set(value, (group.spellings.get(value) ?? 0) + 1)
    group.members.push(node)
    groups.set(key, group)
  }
  const named = [...groups.values()].map(({ spellings, members }): [string, TreeNode[]] => {
    const [name] = [...spellings.entries()].sort(
      (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
    )[0] ?? ['']
    return [name, members]
  })
  named.sort((a, b) => a[0].localeCompare(b[0], undefined, { sensitivity: 'base' }))
  return loose.length === 0 ? named : [...named, [null, loose]]
}

function TreeRow({ node, ...props }: LevelProps & { node: TreeNode }) {
  const { vault, kind, registry, path, editable, dragging, onNavigate } = props
  const [open, setOpen] = useState(false)
  const [action, setAction] = useState<'rename' | 'child' | null>(null)
  const params = useParams({ strict: false })
  const pinned = usePlaceList('pinned', vault).some((place) => place.id === node.id)
  const trash = useDeleteEntity(vault)
  const restore = useRestoreEntity(vault)
  const rename = useUpdateLatest(vault)
  const {
    setNodeRef: setDragRef,
    listeners,
    attributes,
    isDragging,
  } = useDraggable({ id: node.id, data: { node }, disabled: !editable })
  const { setNodeRef: setDropRef, isOver } = useDroppable({
    id: `node:${node.id}`,
    data: { node, path } satisfies DropData,
    disabled: !editable,
  })
  const valid = dragging !== null && canReparent(registry, dragging, node, path).ok
  const Icon = registry.kind(node.kind)?.icon ?? kind.icon
  const creatable = childKinds(registry, node.kind)
  const childKind = creatable.find((candidate) => candidate.key === node.kind) ?? creatable[0]
  const current = params.entity === node.id

  return (
    <li>
      <ContextMenu>
        <ContextMenuTrigger asChild>
          <div
            ref={setDropRef}
            className={cn(
              ROW,
              current && 'bg-accent font-medium',
              isDragging && 'opacity-40',
              isOver && (valid ? 'bg-primary/15 ring-1 ring-primary' : 'bg-destructive/10'),
            )}
            style={{ paddingLeft: `${path.length * 0.75}rem` }}
            data-drop={isOver ? (valid ? 'valid' : 'invalid') : undefined}
            data-tree-row
          >
            {node.has_children ? (
              <button
                type="button"
                aria-expanded={open}
                aria-label={`${open ? 'Collapse' : 'Expand'} ${node.name}`}
                className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                onClick={() => {
                  setOpen(!open)
                }}
              >
                <ChevronRightIcon
                  aria-hidden
                  className={cn('size-3.5 transition-transform', open && 'rotate-90')}
                />
              </button>
            ) : (
              <span className="w-[1.125rem] shrink-0" aria-hidden />
            )}
            <Link
              ref={setDragRef}
              {...listeners}
              {...attributes}
              // dnd-kit's role="button" would hide the link from link queries and screen readers.
              role={undefined}
              to="/v/$vault/e/$entity"
              params={{ vault, entity: node.id }}
              aria-current={current ? 'page' : undefined}
              className="flex min-w-0 flex-1 items-center gap-1.5 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={onNavigate}
            >
              <Icon aria-hidden className="size-4 shrink-0" style={{ color: kind.color }} />
              <span className="truncate">{node.name}</span>
            </Link>
            {node.multiversal && node.kind !== 'dimension' && (
              <Badge variant="outline" className="h-4 px-1 text-[10px]" title="Multiversal">
                ∞
              </Badge>
            )}
            <FindingsBadge vault={vault} entityId={node.id} compact />
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent>
          {editable && childKind !== undefined && (
            <ContextMenuItem
              onSelect={() => {
                setAction('child')
              }}
            >
              New child…
            </ContextMenuItem>
          )}
          {editable && (
            <ContextMenuItem
              onSelect={() => {
                setAction('rename')
              }}
            >
              Rename…
            </ContextMenuItem>
          )}
          <ContextMenuItem
            onSelect={() => {
              togglePin(vault, { id: node.id, name: node.name, kind: node.kind })
            }}
          >
            {pinned ? 'Unpin' : 'Pin'}
          </ContextMenuItem>
          {editable && (
            <>
              <ContextMenuSeparator />
              <ContextMenuItem
                variant="destructive"
                onSelect={() => {
                  trash.mutate(
                    { id: node.id },
                    {
                      onSuccess: () => {
                        toast(`Moved ${node.name} to the trash`, {
                          action: {
                            label: 'Undo',
                            onClick: () => {
                              restore.mutate(node.id)
                            },
                          },
                        })
                      },
                    },
                  )
                }}
              >
                Move to trash
              </ContextMenuItem>
            </>
          )}
        </ContextMenuContent>
      </ContextMenu>
      {open && <TreeLevel {...props} parent={node} path={[...path, node.id]} />}
      {action === 'rename' && (
        <RenameDialog
          name={node.name}
          busy={rename.isPending}
          onClose={() => {
            setAction(null)
          }}
          onRename={(name) => {
            rename.mutate(
              { id: node.id, change: { name } },
              {
                onSuccess: () => {
                  setAction(null)
                },
              },
            )
          }}
        />
      )}
      {action === 'child' && childKind !== undefined && (
        <CreateEntityDialog
          vault={vault}
          initialKind={childKind.key}
          initialParent={node}
          onClose={() => {
            setAction(null)
          }}
        />
      )}
    </li>
  )
}

/** Pinned or recent entities (per vault, in `localStorage`). */
function Places({
  vault,
  list,
  title,
  registry,
  onNavigate,
}: {
  vault: string
  list: 'pinned' | 'recent'
  title: string
  registry: KindRegistry
  onNavigate: (() => void) | undefined
}) {
  const places = usePlaceList(list, vault)
  if (places.length === 0) return null
  return (
    <section aria-label={title} className="mt-2 flex flex-col">
      <h2 className="px-2 py-1 text-xs font-medium text-muted-foreground">{title}</h2>
      <ul className="flex flex-col">
        {places.map((place) => {
          const kind = registry.kind(place.kind)
          const Icon = kind?.icon
          return (
            <li key={place.id}>
              <Link
                to="/v/$vault/e/$entity"
                params={{ vault, entity: place.id }}
                className={cn(ROW, 'px-2')}
                onClick={onNavigate}
              >
                {Icon && (
                  <Icon aria-hidden className="size-4 shrink-0" style={{ color: kind.color }} />
                )}
                <span className="truncate">{place.name}</span>
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export type { TreeEntity }
