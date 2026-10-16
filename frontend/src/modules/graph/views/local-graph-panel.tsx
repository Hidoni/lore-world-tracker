import { Link, useNavigate } from '@tanstack/react-router'
import { lazy, Suspense, useState } from 'react'

import type { EntityViewProps } from '@/core/modules'
import { useKindRegistry } from '@/core/registry'
import { useEntityAsOf } from '@/core/time'
import { useGraph, type GraphData } from '@/data'

import { useCanvasData } from './canvas-data'
import { useVisualLink } from './visual-link'

const GraphCanvas = lazy(() => import('./graph-canvas'))
const NO_POSITIONS = {}
const ignore = (): void => undefined

/**
 * The local graph panel on every entity page (docs/modules/graph.md, UI): the entity's
 * neighborhood, one or two steps, at the time cursor, drawn like the global graph. A double click
 * opens a neighbor, `Alt`+drag links two of them, and the graph page opens centered on it. "As a
 * list" shows the same neighbors as links, with how each connects (frontend.md §9.6).
 */
export function LocalGraphPanel({ vault, entityId }: EntityViewProps) {
  const navigate = useNavigate()
  const asOf = useEntityAsOf(vault, entityId)
  const [depth, setDepth] = useState(1)
  const [asList, setAsList] = useState(false)
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
      ) : asList ? (
        <NeighborList
          vault={vault}
          entityId={entityId}
          nodes={nodes}
          edges={graph.data?.edges ?? []}
        />
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

type GraphNode = GraphData['nodes'][number]
type Edge = GraphData['edges'][number]

/**
 * The local graph as a list: the neighbors in the order the graph gives them, each with the
 * connections between it and this entity (for two steps, the ones through others say "via").
 */
function NeighborList({
  vault,
  entityId,
  nodes,
  edges,
}: {
  vault: string
  entityId: string
  nodes: readonly GraphNode[]
  edges: readonly Edge[]
}) {
  const registry = useKindRegistry(vault)
  const names = new Map(nodes.map((node) => [node.id, node.name]))
  // How a connection reads from this entity: the link type's label (its inverse label for a link
  // pointing here) and the link's role, or a mention or parent.
  const describe = (edge: Edge): string => {
    if (edge.kind === 'mention') return 'mention'
    if (edge.kind === 'parent') return 'parent'
    const type = edge.link_type === null ? undefined : registry?.linkType(edge.link_type)
    const outgoing = edge.source === entityId
    const name =
      (outgoing ? type?.label : (type?.inverse_label ?? type?.label)) ?? edge.link_type ?? 'link'
    return edge.label === null || edge.label === '' ? name : `${name} (${edge.label})`
  }
  return (
    <ul aria-label="Neighbors" className="flex flex-col gap-1">
      {nodes
        .filter((node) => node.id !== entityId)
        .map((node) => {
          const direct = edges.filter(
            (edge) =>
              (edge.source === entityId && edge.target === node.id) ||
              (edge.target === entityId && edge.source === node.id),
          )
          const via =
            direct.length > 0
              ? []
              : edges.filter((edge) => edge.source === node.id || edge.target === node.id)
          return (
            <li key={node.id} className="flex flex-wrap gap-x-2">
              <Link
                to="/v/$vault/e/$entity"
                params={{ vault, entity: node.id }}
                className="text-primary underline-offset-2 hover:underline"
              >
                {node.name}
              </Link>
              <span className="text-muted-foreground">
                {registry?.kind(node.kind)?.label ?? node.kind}
                {direct.length > 0
                  ? ` · ${[...new Set(direct.map(describe))].join(', ')}`
                  : via.length > 0
                    ? ` · via ${[...new Set(via.map((edge) => names.get(edge.source === node.id ? edge.target : edge.source) ?? '…'))].join(', ')}`
                    : ''}
              </span>
            </li>
          )
        })}
    </ul>
  )
}
