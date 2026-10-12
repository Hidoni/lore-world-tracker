import { Link, useNavigate } from '@tanstack/react-router'
import { MaximizeIcon } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useTimeContext } from '@/core/time'
import { ApiError, useCausality, useEntity, useTimelines, type CausalityGraph } from '@/data'

import { flatten } from '../event-outline'
import { byStart } from './layout'

// React Flow and ELK load with the first graph that has links (frontend.md §12).
const Canvas = lazy(() => import('./causality-canvas'))

const DEPTHS = [1, 2, 3, 4, 5, 6]

/** The graph as a list (frontend.md §9.6): events by start, each with its causes and effects. */
function CausalityList({ vault, graph }: { vault: string; graph: CausalityGraph }) {
  const names = new Map(graph.nodes.map((node) => [node.id, node.name]))
  const listed = (ids: string[]) => ids.map((id) => names.get(id) ?? id).join(', ')
  return (
    <ul aria-label="Events by start" className="flex flex-col gap-1 text-sm">
      {[...graph.nodes].sort(byStart).map((node) => {
        const causes = graph.edges.filter((e) => e.target_id === node.id).map((e) => e.source_id)
        const effects = graph.edges.filter((e) => e.source_id === node.id).map((e) => e.target_id)
        return (
          <li key={node.id} data-testid="causality-item">
            <Link
              to="/v/$vault/e/$entity"
              params={{ vault, entity: node.id }}
              className={
                node.id === graph.focus ? 'font-semibold' : 'underline-offset-2 hover:underline'
              }
            >
              {node.name}
            </Link>
            <span className="text-muted-foreground"> · {node.display.start ?? 'Undated'}</span>
            {causes.length > 0 && (
              <span className="text-muted-foreground"> · caused by {listed(causes)}</span>
            )}
            {effects.length > 0 && (
              <span className="text-muted-foreground"> · leads to {listed(effects)}</span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

/**
 * The causality view (frontend.md §10): the cause → effect graph around an event on the time
 * context's timeline, as a layered diagram (left → right in time) with a list alternative, a
 * depth control and, with several timelines, a timeline select. Compact on event pages (with a
 * link to the full page); the full page can focus the graph on another event.
 */
export function CausalityPanel({
  vault,
  eventId,
  compact,
}: {
  vault: string
  eventId: string
  compact: boolean
}) {
  const navigate = useNavigate()
  const context = useTimeContext(vault)
  const timelines = useTimelines(vault, context.dimensionId)
  const options = flatten(timelines.data?.items ?? [])
  const [depth, setDepth] = useState(compact ? 1 : 2)
  const [asList, setAsList] = useState(false)
  const query = useCausality(vault, context.timelineId, eventId, depth)
  const graph = query.data ?? null
  const notOnTimeline = query.error instanceof ApiError && query.error.status === 404
  const open = (id: string) => {
    void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: id } })
  }
  const focus = (id: string) => {
    void navigate({ to: '/v/$vault/e/$entity/causality', params: { vault, entity: id } })
  }

  const controls = (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <label className="flex items-center gap-1 text-muted-foreground">
        Depth
        <select
          aria-label="Depth"
          className="h-8 rounded-md border border-input bg-transparent px-1 text-sm"
          value={depth}
          onChange={(event) => {
            setDepth(Number(event.target.value))
          }}
        >
          {DEPTHS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
      {options.length > 1 && (
        <select
          aria-label="Timeline"
          className="h-8 rounded-md border border-input bg-transparent px-1 text-sm"
          value={context.timelineId ?? ''}
          onChange={(event) => {
            context.setTimeline(event.target.value)
          }}
        >
          {options.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
      )}
      <label className="flex items-center gap-1 text-muted-foreground">
        <input
          type="checkbox"
          checked={asList}
          onChange={(event) => {
            setAsList(event.target.checked)
          }}
        />
        As a list
      </label>
      {compact && (
        <Button asChild variant="ghost" size="sm">
          <Link to="/v/$vault/e/$entity/causality" params={{ vault, entity: eventId }}>
            <MaximizeIcon aria-hidden /> Full view
          </Link>
        </Button>
      )}
    </div>
  )

  let body
  if (notOnTimeline) {
    body = <p className="text-sm text-muted-foreground">This event isn't on this timeline.</p>
  } else if (graph === null) {
    body = <p className="text-sm text-muted-foreground">Loading…</p>
  } else if (graph.nodes.length <= 1) {
    body = <p className="text-sm text-muted-foreground">No causes or effects on this timeline.</p>
  } else if (asList) {
    body = <CausalityList vault={vault} graph={graph} />
  } else {
    body = (
      <div
        role="figure"
        aria-label="Causality graph"
        className="overflow-hidden rounded-md border"
        style={{ height: compact ? 280 : 'calc(100vh - 220px)', minHeight: 320 }}
      >
        <Suspense fallback={<p className="p-3 text-sm text-muted-foreground">Loading…</p>}>
          <Canvas
            graph={graph}
            compact={compact}
            onOpen={open}
            {...(compact ? {} : { onFocus: focus })}
          />
        </Suspense>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      {controls}
      {body}
      {graph?.truncated === true && (
        <p className="text-xs text-muted-foreground">
          Showing the nearest {graph.nodes.length} events.
        </p>
      )}
    </div>
  )
}

/** The full-page causality view of an event (`/v/$vault/e/$entity/causality`). */
export function CausalityPage({ vault, eventId }: { vault: string; eventId: string }) {
  const entity = useEntity(vault, eventId)
  return (
    <div className="flex flex-col gap-3 p-6">
      <div className="flex flex-wrap items-baseline gap-2">
        <h1 className="text-2xl font-semibold">Causality</h1>
        {entity.data !== undefined && (
          <Link
            to="/v/$vault/e/$entity"
            params={{ vault, entity: eventId }}
            className="text-sm text-muted-foreground underline-offset-2 hover:underline"
          >
            {entity.data.name}
          </Link>
        )}
      </div>
      <CausalityPanel vault={vault} eventId={eventId} compact={false} />
    </div>
  )
}
