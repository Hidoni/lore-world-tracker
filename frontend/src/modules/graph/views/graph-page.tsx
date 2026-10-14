import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { lazy, Suspense, useId, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useKindRegistry } from '@/core/registry'
import { useAsOf, useTimeContext } from '@/core/time'
import { useGraph, useTags, type GraphData } from '@/data'

import {
  DEFAULT_FILTERS,
  graphQuery,
  MAX_NODES,
  readPositions,
  readViews,
  viewKey,
  writePositions,
  writeViews,
  type GraphFilters,
  type SavedView,
} from '../filters'
import { CATEGORY_COLORS } from '../styles'
import { useCanvasData } from './canvas-data'
import { useVisualLink } from './visual-link'

const GraphCanvas = lazy(() => import('./graph-canvas'))

type Node = GraphData['nodes'][number]

function toggle(values: readonly string[], value: string): string[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value]
}

function CheckList({
  label,
  options,
  values,
  onChange,
}: {
  label: string
  options: readonly { value: string; label: string }[]
  values: readonly string[]
  onChange: (values: string[]) => void
}) {
  if (options.length === 0) return null
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="mb-1 text-xs font-medium text-muted-foreground">
        {label} {values.length === 0 ? '(all)' : `(${values.length})`}
      </legend>
      <div className="flex max-h-40 flex-col gap-0.5 overflow-y-auto pr-1">
        {options.map((option) => (
          <label key={option.value} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={values.includes(option.value)}
              onChange={() => {
                onChange(toggle(values, option.value))
              }}
            />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

/** The filter panel: what the graph shows (docs/modules/graph.md, UI). */
function FilterPanel({
  vault,
  filters,
  onChange,
}: {
  vault: string
  filters: GraphFilters
  onChange: (filters: GraphFilters) => void
}) {
  const id = useId()
  const registry = useKindRegistry(vault)
  const tags = useTags(vault)
  const set = (change: Partial<GraphFilters>): void => {
    onChange({ ...filters, ...change })
  }
  const flags = [
    ['Mentions', 'mentions'],
    ['Hierarchy', 'hierarchy'],
    ['Orphans', 'orphans'],
  ] as const
  return (
    <aside
      aria-label="Graph filters"
      className="flex w-60 shrink-0 flex-col gap-4 overflow-y-auto p-3"
    >
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${id}-scope`}>Entities of</Label>
        <select
          id={`${id}-scope`}
          className="h-8 rounded-md border bg-transparent px-2 text-sm"
          value={filters.scope}
          onChange={(event) => {
            set({ scope: event.target.value as GraphFilters['scope'] })
          }}
        >
          <option value="context">This dimension</option>
          <option value="all">The whole vault</option>
        </select>
      </div>
      {filters.center !== null && (
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${id}-depth`}>Steps from the center</Label>
          <select
            id={`${id}-depth`}
            className="h-8 rounded-md border bg-transparent px-2 text-sm"
            value={filters.depth}
            onChange={(event) => {
              set({ depth: Number(event.target.value) })
            }}
          >
            {[1, 2, 3, 4].map((depth) => (
              <option key={depth} value={depth}>
                {depth}
              </option>
            ))}
          </select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              set({ center: null })
            }}
          >
            Show the whole graph
          </Button>
        </div>
      )}
      <div className="flex flex-col gap-0.5">
        {flags.map(([label, key]) => (
          <label key={key} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={filters[key]}
              onChange={(event) => {
                set({ [key]: event.target.checked })
              }}
            />
            {label}
          </label>
        ))}
      </div>
      <CheckList
        label="Kinds"
        options={(registry?.kinds ?? []).map((kind) => ({ value: kind.key, label: kind.plural }))}
        values={filters.kinds}
        onChange={(kinds) => {
          set({ kinds })
        }}
      />
      <CheckList
        label="Link types"
        options={(registry?.linkTypes ?? []).map((type) => ({
          value: type.key,
          label: type.label,
        }))}
        values={filters.linkTypes}
        onChange={(linkTypes) => {
          set({ linkTypes })
        }}
      />
      <CheckList
        label="Tags"
        options={(tags.data?.items ?? []).map((tag) => ({ value: tag.id, label: tag.name }))}
        values={filters.tags}
        onChange={(tags) => {
          set({ tags })
        }}
      />
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          onChange({ ...DEFAULT_FILTERS, center: filters.center })
        }}
      >
        Reset filters
      </Button>
    </aside>
  )
}

/** Named filter sets in `localStorage`: save the current one, apply or delete one. */
function SavedViews({
  vault,
  filters,
  onApply,
}: {
  vault: string
  filters: GraphFilters
  onApply: (filters: GraphFilters) => void
}) {
  const [views, setViews] = useState<SavedView[]>(() => readViews(vault))
  const [name, setName] = useState('')
  const update = (next: SavedView[]): void => {
    setViews(next)
    writeViews(vault, next)
  }
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Saved views">
      <select
        aria-label="Saved view"
        className="h-8 rounded-md border bg-transparent px-2 text-sm"
        value=""
        onChange={(event) => {
          const view = views.find((v) => v.name === event.target.value)
          if (view !== undefined) onApply(view.filters)
        }}
      >
        <option value="">{views.length === 0 ? 'No saved views' : 'Apply a saved view…'}</option>
        {views.map((view) => (
          <option key={view.name} value={view.name}>
            {view.name}
          </option>
        ))}
      </select>
      <Input
        aria-label="View name"
        placeholder="Name this view"
        className="h-8 w-40"
        value={name}
        onChange={(event) => {
          setName(event.target.value)
        }}
      />
      <Button
        size="sm"
        variant="outline"
        disabled={name.trim() === ''}
        onClick={() => {
          const trimmed = name.trim()
          update([...views.filter((v) => v.name !== trimmed), { name: trimmed, filters }])
          setName('')
        }}
      >
        Save view
      </Button>
      {views.length > 0 && (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            update([])
          }}
        >
          Forget views
        </Button>
      )}
    </div>
  )
}

/** The selected node: kind, connections, and ways on. */
function Preview({
  vault,
  node,
  onCenter,
  onClose,
}: {
  vault: string
  node: Node
  onCenter: () => void
  onClose: () => void
}) {
  const registry = useKindRegistry(vault)
  return (
    <aside aria-label="Selected entity" className="flex w-64 shrink-0 flex-col gap-2 p-3 text-sm">
      <h2 className="text-base font-medium">{node.name}</h2>
      <p className="text-muted-foreground">
        {registry?.kind(node.kind)?.label ?? node.kind} · {node.degree}{' '}
        {node.degree === 1 ? 'connection' : 'connections'}
      </p>
      {node.existence === 'possible' && (
        <p className="text-muted-foreground italic">Possibly exists then (an uncertain date).</p>
      )}
      <Link
        to="/v/$vault/e/$entity"
        params={{ vault, entity: node.id }}
        className="text-primary underline-offset-2 hover:underline"
      >
        Open {node.name}
      </Link>
      <Button variant="outline" size="sm" onClick={onCenter}>
        Show its neighborhood
      </Button>
      <Button variant="ghost" size="sm" onClick={onClose}>
        Close
      </Button>
    </aside>
  )
}

/**
 * The graph page (`/v/$vault/m/graph`, docs/modules/graph.md): every entity and how they link
 * (links, mentions, hierarchy), or the neighborhood of one, filtered, at the time cursor, drawn
 * with sigma.js and laid out in a worker; or as a list. Filters can be saved as named views, and
 * each view's layout is kept for the next visit.
 */
export default function GraphPage() {
  const vault = useParams({ strict: false }).vault ?? ''
  const navigate = useNavigate()
  const context = useTimeContext(vault)
  const asOf = useAsOf(vault)
  const registry = useKindRegistry(vault)
  // `/m/graph/focus/<entity>` (from an entity's local graph): its neighborhood first.
  const focus = useParams({ strict: false }).entity ?? null
  const [filters, setFilters] = useState<GraphFilters>(() => ({
    ...DEFAULT_FILTERS,
    center: focus,
  }))
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [asList, setAsList] = useState(false)
  // Raised by the truncation notice, back to the server's default when the filters change.
  const [limit, setLimit] = useState<number | undefined>(undefined)
  const query = graphQuery(filters, context.dimensionId, asOf, limit)
  const graph = useGraph(vault, query)
  const key = viewKey(filters)
  const [positions, setPositions] = useState(() => readPositions(vault, key))

  const data = graph.data
  const nodes = useMemo<Node[]>(
    () => (data?.nodes ?? []).filter((node) => filters.orphans || node.degree > 0),
    [data, filters.orphans],
  )
  const { canvasNodes, canvasEdges } = useCanvasData(vault, nodes, data?.edges)
  const needle = search.trim().toLocaleLowerCase()
  const matches = useMemo(
    () =>
      needle === ''
        ? null
        : new Set(
            nodes.filter((n) => n.name.toLocaleLowerCase().includes(needle)).map((n) => n.id),
          ),
    [nodes, needle],
  )
  const chosen = nodes.find((node) => node.id === selected) ?? null
  const visual = useVisualLink(vault, nodes)
  const open = (id: string): void => {
    void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: id } })
  }
  const change = (next: GraphFilters): void => {
    setFilters(next)
    setLimit(undefined)
    setPositions(readPositions(vault, viewKey(next)))
    setSelected(null)
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b px-4 py-2">
        <h1 className="text-lg font-semibold">Graph</h1>
        <Input
          aria-label="Find in the graph"
          placeholder="Find…"
          className="h-8 w-56"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
          }}
          onKeyDown={(event) => {
            const first = matches === null ? undefined : [...matches][0]
            if (event.key === 'Enter' && first !== undefined) setSelected(first)
          }}
        />
        {matches !== null && (
          <span className="text-sm text-muted-foreground" role="status">
            {matches.size} found
          </span>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={asList}
            onChange={(event) => {
              setAsList(event.target.checked)
            }}
          />
          As a list
        </label>
        <SavedViews vault={vault} filters={filters} onApply={change} />
      </header>
      {(data?.truncated === true || asOf !== undefined) && (
        <div className="flex flex-wrap gap-4 border-b px-4 py-1 text-sm text-muted-foreground">
          {data?.truncated === true && (
            <p role="status">
              Too many entities: the {data.nodes.length.toLocaleString()} best connected are shown.
              Filter, or show one entity’s neighborhood, to see the rest.
              {limit === undefined && (
                <Button
                  variant="link"
                  size="sm"
                  className="ml-1 h-auto p-0"
                  onClick={() => {
                    setLimit(MAX_NODES)
                  }}
                >
                  Show up to {MAX_NODES.toLocaleString()}
                </Button>
              )}
            </p>
          )}
          {asOf !== undefined && (
            <p>As of the time cursor: what existed then, and the links valid then.</p>
          )}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <FilterPanel vault={vault} filters={filters} onChange={change} />
        <main
          className="relative min-w-0 flex-1 border-x"
          aria-label="Graph"
          aria-busy={graph.isFetching}
        >
          {graph.isPending ? (
            <p className="p-4 text-sm text-muted-foreground">Loading…</p>
          ) : graph.isError ? (
            <p role="alert" className="p-4 text-sm text-destructive">
              {graph.error.message}
            </p>
          ) : nodes.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">Nothing matches these filters.</p>
          ) : asList ? (
            <ol aria-label="Entities by connections" className="h-full overflow-y-auto p-4 text-sm">
              {nodes.slice(0, 1000).map((node) => (
                <li key={node.id} className="flex gap-2">
                  <button
                    type="button"
                    className="text-primary underline-offset-2 hover:underline"
                    onClick={() => {
                      setSelected(node.id)
                    }}
                  >
                    {node.name}
                  </button>
                  <span className="text-muted-foreground">
                    {registry?.kind(node.kind)?.label ?? node.kind} · {node.degree}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <Suspense fallback={<p className="p-4 text-sm text-muted-foreground">Loading…</p>}>
              <GraphCanvas
                nodes={canvasNodes}
                edges={canvasEdges}
                positions={positions}
                highlighted={matches}
                selected={selected}
                onSelect={setSelected}
                onOpen={open}
                onLink={visual.onLink}
                onPositions={(found) => {
                  setPositions(found)
                  writePositions(vault, key, found)
                }}
              />
            </Suspense>
          )}
          <ul
            aria-label="Legend"
            className="absolute bottom-2 left-2 flex flex-wrap gap-2 rounded-md bg-background/90 p-1 text-xs"
          >
            {Object.entries(CATEGORY_COLORS).map(([category, color]) => (
              <li key={category} className="flex items-center gap-1">
                <span className="inline-block h-0.5 w-4" style={{ backgroundColor: color }} />
                {category}
              </li>
            ))}
          </ul>
        </main>
        {visual.dialog}
        {chosen !== null && (
          <Preview
            vault={vault}
            node={chosen}
            onCenter={() => {
              change({ ...filters, center: chosen.id })
            }}
            onClose={() => {
              setSelected(null)
            }}
          />
        )}
      </div>
    </div>
  )
}
