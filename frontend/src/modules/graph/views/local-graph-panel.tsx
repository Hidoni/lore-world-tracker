import { Link, useNavigate } from '@tanstack/react-router'
import { lazy, Suspense, useState } from 'react'

import type { EntityViewProps } from '@/core/modules'
import { useEntityAsOf } from '@/core/time'
import { useGraph } from '@/data'

import { useCanvasData } from './canvas-data'
import { useVisualLink } from './visual-link'

const GraphCanvas = lazy(() => import('./graph-canvas'))
const NO_POSITIONS = {}
const ignore = (): void => undefined

/**
 * The local graph panel on every entity page (docs/modules/graph.md, UI): the entity's
 * neighborhood, one or two steps, at the time cursor, drawn like the global graph. A double click
 * opens a neighbor, `Alt`+drag links two of them, and the graph page opens centered on it.
 */
export function LocalGraphPanel({ vault, entityId }: EntityViewProps) {
  const navigate = useNavigate()
  const asOf = useEntityAsOf(vault, entityId)
  const [depth, setDepth] = useState(1)
  const graph = useGraph(vault, { center: entityId, depth, ...(asOf ?? {}) })
  const nodes = graph.data?.nodes ?? []
  const { canvasNodes, canvasEdges } = useCanvasData(vault, nodes, graph.data?.edges)
  const visual = useVisualLink(vault, nodes)
  return (
    <div className="flex flex-col gap-2 text-sm">
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1 text-muted-foreground">
          Steps
          <select
            className="h-7 rounded-md border bg-transparent px-1"
            value={depth}
            onChange={(event) => {
              setDepth(Number(event.target.value))
            }}
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
          </select>
        </label>
        <Link
          to="/v/$vault/m/$module/$"
          params={{ vault, module: 'graph', _splat: `focus/${entityId}` }}
          className="ml-auto text-primary underline-offset-2 hover:underline"
        >
          Open in the graph
        </Link>
      </div>
      {graph.isPending ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : nodes.length <= 1 ? (
        <p className="text-muted-foreground">No connections yet.</p>
      ) : (
        <figure aria-label="Local graph" className="h-64 rounded-md border">
          <Suspense fallback={<p className="p-2 text-muted-foreground">Loading…</p>}>
            <GraphCanvas
              nodes={canvasNodes}
              edges={canvasEdges}
              positions={NO_POSITIONS}
              highlighted={null}
              selected={entityId}
              onSelect={ignore}
              onOpen={(id) => {
                void navigate({ to: '/v/$vault/e/$entity', params: { vault, entity: id } })
              }}
              onPositions={ignore}
              {...(visual.onLink === undefined ? {} : { onLink: visual.onLink })}
            />
          </Suspense>
        </figure>
      )}
      {visual.dialog}
    </div>
  )
}
