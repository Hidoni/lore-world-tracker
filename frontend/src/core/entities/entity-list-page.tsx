import { Link } from '@tanstack/react-router'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { FieldDisplay } from '@/core/fields'
import { useKindRegistry, type Kind } from '@/core/registry'
import { certaintyProps, useExistenceQuery } from '@/core/time'
import { useEntities, useEntityList, useMutations, type components, type Query } from '@/data'

import { cn } from '@/lib/utils'

import { CreateEntityDialog } from './create-entity-dialog'

type Field = components['schemas']['FieldOut']
type Sort = NonNullable<Query<'entities_list'>['sort']>

const ROW_HEIGHT = 36
const PAGE_SIZE = 200
const SELECT_CLASS =
  'h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
const SORTS: { value: Sort; label: string }[] = [
  { value: 'name', label: 'Name (A–Z)' },
  { value: '-name', label: 'Name (Z–A)' },
  { value: '-updated', label: 'Recently updated' },
  { value: '-created', label: 'Recently created' },
  { value: 'created', label: 'Oldest first' },
]
// Wide or structured values don't fit a table cell.
const NOT_IN_COLUMNS = new Set(['rich_text', 'long_text', 'time_point', 'duration'])

/** The kind's list columns (module UI config `listColumns`), else its first three short fields. */
export function listFields(kind: Kind): Field[] {
  const fields = kind.fields.filter((field) => !field.archived)
  if (kind.listColumns.length > 0) {
    return kind.listColumns
      .map((key) => fields.find((field) => field.key === key))
      .filter((field): field is Field => field !== undefined)
  }
  return fields
    .filter((field) => !NOT_IN_COLUMNS.has(field.type))
    .sort((a, b) => a.sort - b.sort)
    .slice(0, 3)
}

/**
 * The entities of a kind (frontend.md §7): filter by name and dimension, sort, columns from the
 * kind's UI config. Rows are virtualized and pages of 200 load while scrolling, so long lists
 * (10k+) stay smooth.
 */
export function EntityListPage({ vault, kindKey }: { vault: string; kindKey: string }) {
  const registry = useKindRegistry(vault)
  if (registry === undefined) return null
  const kind = registry.kind(kindKey)
  if (kind === undefined) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-semibold">Unknown kind</h1>
        <p className="text-muted-foreground">
          This vault has no kind “{kindKey}”, or its module is disabled.
        </p>
      </div>
    )
  }
  return <EntityList key={kind.key} vault={vault} kind={kind} />
}

function EntityList({ vault, kind }: { vault: string; kind: Kind }) {
  const editable = useMutations() !== null
  const [q, setQ] = useState('')
  const [dimension, setDimension] = useState('')
  const [sort, setSort] = useState<Sort>('name')
  const [creating, setCreating] = useState(false)
  const dimensions = useEntities(vault, { kind: ['dimension'], limit: 100 })
  const existence = useExistenceQuery(vault)
  const query: Query<'entities_list'> = {
    ...existence,
    kind: [kind.key],
    sort,
    limit: PAGE_SIZE,
    ...(q.trim() ? { q: q.trim() } : {}),
    ...(dimension ? { dimension } : {}),
  }
  const list = useEntityList(vault, query)
  const rows = list.data?.pages.flatMap((page) => page.items) ?? []
  const fields = listFields(kind)
  const dimensionNames = new Map((dimensions.data?.items ?? []).map((item) => [item.id, item.name]))
  const showDimension = kind.key !== 'dimension'
  const columns = `minmax(12rem,2fr) ${fields.map(() => 'minmax(8rem,1fr)').join(' ')} ${
    showDimension ? 'minmax(8rem,1fr)' : ''
  } 9rem`

  const scroller = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line react-hooks/incompatible-library -- the virtualizer is read in render on purpose
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    // jsdom and the first paint have no layout yet.
    initialRect: { width: 960, height: 640 },
  })
  const items = virtualizer.getVirtualItems()
  const last = items.at(-1)?.index ?? -1
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = list
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && last >= rows.length - 20) void fetchNextPage()
  }, [last, rows.length, hasNextPage, isFetchingNextPage, fetchNextPage])

  const Icon = kind.icon
  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col gap-4 p-6">
      <header className="flex flex-wrap items-center gap-3">
        <Icon aria-hidden className="size-6" style={{ color: kind.color }} />
        <h1 className="text-2xl font-semibold">{kind.plural}</h1>
        {editable && !kind.capabilities.is_system && (
          <Button
            className="ml-auto"
            onClick={() => {
              setCreating(true)
            }}
          >
            New {kind.label.toLowerCase()}
          </Button>
        )}
      </header>
      <div role="search" className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="list-filter">Name</Label>
          <Input
            id="list-filter"
            placeholder="Starts with…"
            value={q}
            onChange={(event) => {
              setQ(event.target.value)
            }}
          />
        </div>
        {showDimension && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="list-dimension">Dimension</Label>
            <select
              id="list-dimension"
              className={SELECT_CLASS}
              value={dimension}
              onChange={(event) => {
                setDimension(event.target.value)
              }}
            >
              <option value="">All</option>
              {(dimensions.data?.items ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="list-sort">Sort</Label>
          <select
            id="list-sort"
            className={SELECT_CLASS}
            value={sort}
            onChange={(event) => {
              setSort(event.target.value as Sort)
            }}
          >
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <p className="ml-auto text-sm text-muted-foreground" aria-live="polite">
          {list.isPending
            ? 'Loading…'
            : `${rows.length}${hasNextPage ? '+' : ''} ${rows.length === 1 ? kind.label.toLowerCase() : kind.plural.toLowerCase()}`}
        </p>
      </div>
      <div
        role="table"
        aria-label={kind.plural}
        aria-rowcount={hasNextPage ? -1 : rows.length + 1}
        className="flex min-h-0 flex-1 flex-col rounded-md border text-sm"
      >
        <div role="rowgroup" className="border-b bg-muted/50">
          <div
            role="row"
            aria-rowindex={1}
            className="grid"
            style={{ gridTemplateColumns: columns }}
          >
            <span role="columnheader" className="px-3 py-2 font-medium">
              Name
            </span>
            {fields.map((field) => (
              <span key={field.key} role="columnheader" className="px-3 py-2 font-medium">
                {field.label}
              </span>
            ))}
            {showDimension && (
              <span role="columnheader" className="px-3 py-2 font-medium">
                Dimension
              </span>
            )}
            <span role="columnheader" className="px-3 py-2 font-medium">
              Updated
            </span>
          </div>
        </div>
        <div ref={scroller} role="rowgroup" className="min-h-64 flex-1 overflow-auto">
          {!list.isPending && rows.length === 0 && (
            <p className="p-6 text-center text-muted-foreground">
              No {kind.plural.toLowerCase()}
              {q.trim() || dimension ? ' match these filters' : ' yet'}.
            </p>
          )}
          <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
            {items.map((item) => {
              const entity = rows[item.index]
              if (entity === undefined) return null
              return (
                <div
                  key={entity.id}
                  role="row"
                  aria-rowindex={item.index + 2}
                  className="absolute inset-x-0 grid items-center border-b hover:bg-accent/50"
                  style={{
                    gridTemplateColumns: columns,
                    height: ROW_HEIGHT,
                    transform: `translateY(${item.start}px)`,
                  }}
                >
                  <span role="cell" className="truncate px-3">
                    <Link
                      to="/v/$vault/e/$entity"
                      params={{ vault, entity: entity.id }}
                      {...certaintyProps(entity.existence)}
                      className={cn(
                        'font-medium hover:underline',
                        certaintyProps(entity.existence).className,
                      )}
                    >
                      {entity.name}
                    </Link>
                  </span>
                  {fields.map((field) => (
                    <span key={field.key} role="cell" className="truncate px-3">
                      <FieldDisplay vault={vault} field={field} value={entity.fields[field.key]} />
                    </span>
                  ))}
                  {showDimension && (
                    <span role="cell" className="truncate px-3 text-muted-foreground">
                      {entity.dimension_id === null
                        ? 'Multiversal'
                        : (dimensionNames.get(entity.dimension_id) ?? '…')}
                    </span>
                  )}
                  <span role="cell" className="truncate px-3 text-muted-foreground">
                    {new Date(entity.updated_at).toLocaleDateString()}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>
      {creating && (
        <CreateEntityDialog
          vault={vault}
          initialKind={kind.key}
          onClose={() => {
            setCreating(false)
          }}
        />
      )}
    </div>
  )
}
