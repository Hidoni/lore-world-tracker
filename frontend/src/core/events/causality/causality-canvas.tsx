import '@xyflow/react/dist/style.css'

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import { CrosshairIcon } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import type { CausalityGraph } from '@/data'
import { cn } from '@/lib/utils'

import { layoutCausality, NODE_HEIGHT, NODE_WIDTH } from './layout'

type GraphNode = CausalityGraph['nodes'][number]
// React Flow's node data is a record (an interface has no index signature).
// eslint-disable-next-line @typescript-eslint/consistent-type-definitions
type EventNodeData = { node: GraphNode; focus: boolean; onFocus?: (id: string) => void }
type EventFlowNode = Node<EventNodeData, 'event'>

function EventNode({ data }: NodeProps<EventFlowNode>) {
  const { node, focus, onFocus } = data
  return (
    <div
      data-testid="causality-node"
      data-focus={focus ? '' : undefined}
      title={node.name}
      className={cn(
        'flex flex-col justify-center overflow-hidden rounded-md border bg-card px-2 text-xs shadow-sm',
        focus && 'border-primary ring-2 ring-primary/40',
      )}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <span className="flex items-center gap-1">
        <span className="flex-1 truncate font-medium">{node.name}</span>
        {onFocus !== undefined && !focus && (
          <button
            type="button"
            aria-label={`Focus on ${node.name}`}
            title="Focus the graph here"
            className="nodrag rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={(event) => {
              event.stopPropagation()
              onFocus(node.id)
            }}
          >
            <CrosshairIcon aria-hidden className="size-3" />
          </button>
        )}
      </span>
      <span className="truncate text-muted-foreground">{node.display.start ?? 'Undated'}</span>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  )
}

const NODE_TYPES = { event: EventNode }

/** Fits the view to the graph whenever its layout changes. */
function FitOnLayout({ layout }: { layout: unknown }) {
  const flow = useReactFlow()
  useEffect(() => {
    void flow.fitView({ padding: 0.15, maxZoom: 1.25 })
  }, [flow, layout])
  return null
}

/**
 * The causality graph drawn with React Flow, laid out by ELK (layered, left → right in time).
 * Click opens an event; its crosshair (full page) focuses the graph on it. Loaded lazily with its libraries.
 */
export default function CausalityCanvas({
  graph,
  compact,
  onOpen,
  onFocus,
}: {
  graph: CausalityGraph
  compact: boolean
  onOpen: (id: string) => void
  onFocus?: (id: string) => void
}) {
  const [layout, setLayout] = useState<{
    graph: CausalityGraph
    positions: Map<string, { x: number; y: number }>
  } | null>(null)
  useEffect(() => {
    let current = true
    void layoutCausality(graph).then((positions) => {
      if (current) setLayout({ graph, positions })
    })
    return () => {
      current = false
    }
  }, [graph])

  const nodes = useMemo<EventFlowNode[]>(
    () =>
      layout === null
        ? []
        : layout.graph.nodes.map((node) => ({
            id: node.id,
            type: 'event',
            position: layout.positions.get(node.id) ?? { x: 0, y: 0 },
            data: {
              node,
              focus: node.id === layout.graph.focus,
              ...(onFocus === undefined ? {} : { onFocus }),
            },
            draggable: false,
            connectable: false,
          })),
    [layout, onFocus],
  )
  const edges = useMemo<Edge[]>(
    () =>
      (layout?.graph.edges ?? []).map((edge) => ({
        id: edge.id,
        source: edge.source_id,
        target: edge.target_id,
        markerEnd: { type: MarkerType.ArrowClosed },
        ...(compact || edge.description === null
          ? {}
          : { label: edge.description, labelStyle: { fontSize: 11 } }),
      })),
    [layout, compact],
  )

  if (layout === null) {
    return <p className="p-3 text-sm text-muted-foreground">Laying out…</p>
  }
  return (
    <ReactFlowProvider>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        nodesDraggable={false}
        nodesConnectable={false}
        minZoom={0.1}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          onOpen(node.id)
        }}
      >
        <FitOnLayout layout={layout} />
        <Background gap={24} />
        {!compact && <Controls showInteractive={false} />}
      </ReactFlow>
    </ReactFlowProvider>
  )
}
